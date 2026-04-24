import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import get_db
from db.models import Session as DBSession, Message, SessionStatus, Doctor
from api.websocket import ws_manager
from api.routes.doctor import get_current_doctor

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize_message(m) -> dict:
    return {
        "role": m.role.value,
        "content": m.content,
        "file_type": m.file_type,
        "file_extracted": m.file_extracted,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _load_full_history(db: AsyncSession, session: DBSession) -> list[dict]:
    """Return messages from all previous sessions (closed) + current session for this telegram_chat_id."""
    result = await db.execute(
        select(DBSession)
        .where(
            DBSession.telegram_chat_id == session.telegram_chat_id,
            DBSession.id != session.id,
            DBSession.status == SessionStatus.closed,
        )
        .order_by(DBSession.created_at)
    )
    past_sessions = result.scalars().all()

    all_messages: list[dict] = []

    for ps in past_sessions:
        msgs_result = await db.execute(
            select(Message).where(Message.session_id == ps.id).order_by(Message.created_at)
        )
        msgs = msgs_result.scalars().all()
        if not msgs:
            continue
        date_str = ps.created_at.strftime("%d/%m/%Y") if ps.created_at else "?"
        all_messages.append({"role": "separator", "content": f"── Ca tư vấn {date_str} ──"})
        for m in msgs:
            all_messages.append(_serialize_message(m))

    # Current session messages
    cur_result = await db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
    )
    cur_msgs = cur_result.scalars().all()
    if past_sessions and cur_msgs:
        date_str = session.created_at.strftime("%d/%m/%Y") if session.created_at else "?"
        all_messages.append({"role": "separator", "content": f"── Ca tư vấn {date_str} (hiện tại) ──"})
    for m in cur_msgs:
        all_messages.append(_serialize_message(m))

    return all_messages


class ConnectRequest(BaseModel):
    telegram_chat_id: int
    user_id: str
    doctor_id: str
    session_id: str | None = None
    summary: str | None = None
    specialty: str | None = None
    urgency: str = "medium"


@router.post("/api/session/connect")
async def connect_session(req: ConnectRequest, db: AsyncSession = Depends(get_db)):
    # Get or create session
    session = None
    if req.session_id:
        result = await db.execute(
            select(DBSession).where(DBSession.id == uuid.UUID(req.session_id))
        )
        session = result.scalar_one_or_none()

    if not session:
        result = await db.execute(
            select(DBSession).where(
                DBSession.telegram_chat_id == req.telegram_chat_id,
                DBSession.status == SessionStatus.pending,
            ).order_by(DBSession.created_at.desc()).limit(1)
        )
        session = result.scalars().first()

    if not session:
        session = DBSession(
            telegram_chat_id=req.telegram_chat_id,
            user_id=req.user_id,
            status=SessionStatus.pending,
        )
        db.add(session)
        await db.flush()

    # Verify doctor exists
    result = await db.execute(
        select(Doctor).where(Doctor.id == uuid.UUID(req.doctor_id))
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Doctor not found")

    session.doctor_id = uuid.UUID(req.doctor_id)
    session.status = SessionStatus.pending
    session.specialty_requested = req.specialty
    session.urgency = req.urgency
    if req.summary:
        session.ai_summary = req.summary

    await db.commit()
    await db.refresh(session)

    msg_list = await _load_full_history(db, session)

    case_payload = {
        "case_id": str(session.id),
        "user_id": req.user_id,
        "summary": req.summary or "Không có tóm tắt",
        "specialty": req.specialty or "Chưa xác định",
        "urgency": req.urgency,
        "status": session.status.value,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "messages": msg_list,
    }

    await ws_manager.notify_new_case(req.doctor_id, case_payload)

    return {"session_id": str(session.id), "status": "pending"}


@router.get("/api/doctor/cases/{case_id}/history")
async def get_case_history(
    case_id: str,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DBSession).where(DBSession.id == uuid.UUID(case_id)))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    if str(session.doctor_id) != doctor["sub"]:
        raise HTTPException(403, "Not your session")
    messages = await _load_full_history(db, session)
    return {"messages": messages}
