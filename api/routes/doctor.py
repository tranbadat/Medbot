import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt

from db.database import get_db
from db.models import Session as DBSession, Message, MessageRole, SessionStatus, Doctor, Appointment, AppointmentStatus
from db.redis_client import set_doctor_status, set_doctor_meta
from api.websocket import ws_manager
from core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


# ----- Auth helpers -----

def create_token(doctor_id: str, name: str, specialty: str) -> str:
    payload = {
        "sub": doctor_id,
        "name": name,
        "specialty": specialty,
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])


async def get_current_doctor(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        return decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


# ----- Routes -----

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/doctor/login")
async def doctor_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    import bcrypt as _bcrypt
    result = await db.execute(select(Doctor).where(Doctor.username == req.username))
    doctor = result.scalar_one_or_none()
    if not doctor or not _bcrypt.checkpw(req.password.encode(), doctor.password_hash.encode()):
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    token = create_token(str(doctor.id), doctor.name, doctor.specialty)
    await set_doctor_meta(str(doctor.id), doctor.name, doctor.specialty, doctor.working_hours or "8:00 - 17:00 (T2-T7)")
    await set_doctor_status(str(doctor.id), "online")
    return {"token": token, "doctor_id": str(doctor.id), "name": doctor.name, "specialty": doctor.specialty}


class StatusRequest(BaseModel):
    status: str  # online | busy | offline


@router.post("/api/doctor/status")
async def set_status(
    req: StatusRequest,
    doctor: dict = Depends(get_current_doctor),
):
    if req.status not in ("online", "busy", "offline"):
        raise HTTPException(400, "Invalid status")
    await set_doctor_status(doctor["sub"], req.status)
    return {"ok": True}


class SendRequest(BaseModel):
    case_id: str
    content: str


@router.post("/api/doctor/send")
async def doctor_send(
    req: SendRequest,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSession).where(DBSession.id == uuid.UUID(req.case_id))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    if str(session.doctor_id) != doctor["sub"]:
        raise HTTPException(403, "Not your session")

    doctor_name = doctor.get("name", "Bác sĩ")
    relay_text = f"*{doctor_name}*\n{req.content}"

    from bot.relay import send_to_session
    await send_to_session(session, relay_text)

    msg = Message(session_id=session.id, role=MessageRole.doctor, content=req.content)
    db.add(msg)
    await db.commit()

    # Broadcast back to doctor dashboard so UI is driven by server, not local push
    from api.websocket import ws_manager
    await ws_manager.send_to_doctor(doctor["sub"], {
        "event": "doctor_message",
        "case_id": req.case_id,
        "content": req.content,
        "doctor_name": doctor_name,
    })

    return {"ok": True}


class AcceptRequest(BaseModel):
    case_id: str


@router.post("/api/doctor/accept")
async def accept_case(
    req: AcceptRequest,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSession).where(DBSession.id == uuid.UUID(req.case_id))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    session.doctor_id = uuid.UUID(doctor["sub"])
    session.status = SessionStatus.active
    await db.commit()

    from bot.relay import send_to_session
    doctor_name = doctor.get("name", "bác sĩ")
    prefix = "" if doctor_name.startswith("BS.") else "BS. "
    await send_to_session(
        session,
        f"✅ {prefix}{doctor_name} đã nhận ca của bạn. Bạn có thể nhắn tin trực tiếp.",
    )

    return {"ok": True, "session_id": str(session.id)}


class TransferRequest(BaseModel):
    case_id: str
    to_doctor_id: str


@router.post("/api/doctor/transfer")
async def transfer_case(
    req: TransferRequest,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSession).where(DBSession.id == uuid.UUID(req.case_id))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    if str(session.doctor_id) != doctor["sub"]:
        raise HTTPException(403, "Not your session")

    old_doctor_id = str(session.doctor_id)
    session.doctor_id = uuid.UUID(req.to_doctor_id)
    session.status = SessionStatus.pending
    await db.commit()

    await ws_manager.send_to_doctor(
        req.to_doctor_id,
        {"event": "case_transferred", "case_id": req.case_id, "from_doctor_id": old_doctor_id},
    )

    return {"ok": True}


class CloseRequest(BaseModel):
    case_id: str
    close_note: str = ""


@router.post("/api/doctor/close")
async def close_case(
    req: CloseRequest,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSession).where(DBSession.id == uuid.UUID(req.case_id))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    session.status = SessionStatus.closed
    if req.close_note:
        session.ai_summary = (session.ai_summary or "") + f"\n[Bác sĩ ghi chú]: {req.close_note}"
    await db.commit()

    await ws_manager.broadcast_to_session(
        req.case_id, {"event": "case_closed", "case_id": req.case_id}
    )

    from bot.relay import send_to_session
    await send_to_session(session, "✅ Ca tư vấn đã kết thúc. Cảm ơn bạn đã sử dụng MedBot!")

    return {"ok": True}


@router.get("/api/doctor/appointments")
async def get_doctor_appointments(
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.doctor_id == uuid.UUID(doctor["sub"]),
            Appointment.status != AppointmentStatus.cancelled,
        )
        .order_by(Appointment.appointment_date)
    )
    appts = result.scalars().all()
    return {"appointments": [
        {
            "id": str(a.id),
            "patient_name": a.patient_name,
            "appointment_date": a.appointment_date.isoformat(),
            "status": a.status.value,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in appts
    ]}


class AppointmentUpdate(BaseModel):
    status: str  # "confirmed" | "cancelled"


@router.patch("/api/doctor/appointments/{appt_id}")
async def update_appointment_status(
    appt_id: str,
    req: AppointmentUpdate,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.doctor))
        .where(
            Appointment.id == uuid.UUID(appt_id),
            Appointment.doctor_id == uuid.UUID(doctor["sub"]),
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(404, "Không tìm thấy lịch hẹn")
    if req.status not in ("confirmed", "cancelled"):
        raise HTTPException(400, "status phải là 'confirmed' hoặc 'cancelled'")

    appt.status = AppointmentStatus(req.status)
    await db.commit()

    if req.status == "confirmed":
        from bot.relay import send_to_appointment
        dt_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
        doc_name = appt.doctor.name if appt.doctor else "bác sĩ"
        await send_to_appointment(
            appt,
            f"✅ Lịch khám của bạn đã được xác nhận!\n"
            f"📅 {dt_str}\n👨‍⚕️ {doc_name}\n\nVui lòng đến đúng giờ."
        )
    return {"ok": True}


@router.get("/api/doctor/cases")
async def get_doctor_cases(
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSession).where(
            DBSession.doctor_id == uuid.UUID(doctor["sub"]),
            DBSession.status != SessionStatus.closed,
        ).order_by(DBSession.updated_at.desc())
    )
    sessions = result.scalars().all()
    return {
        "cases": [
            {
                "id": str(s.id),
                "user_id": s.user_id,
                "status": s.status.value,
                "specialty": s.specialty_requested,
                "urgency": s.urgency,
                "summary": s.ai_summary,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ]
    }


@router.post("/api/doctor/cases/{case_id}/delegate")
async def delegate_to_bot(
    case_id: str,
    doctor: dict = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db),
):
    """Doctor delegates answering to AI bot for the last user message."""
    result = await db.execute(select(DBSession).where(DBSession.id == uuid.UUID(case_id)))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    if str(session.doctor_id) != doctor["sub"]:
        raise HTTPException(403, "Not your session")

    # Get last user message
    last_msg_result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.role == MessageRole.user)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_msg = last_msg_result.scalar_one_or_none()
    if not last_msg:
        raise HTTPException(400, "No user message to respond to")

    # Get recent conversation history
    history_result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at)
        .limit(20)
    )
    history = [
        {"role": "user" if m.role == MessageRole.user else "assistant", "content": m.content}
        for m in history_result.scalars().all()
    ]

    # Get RAG context
    from core.rag import retrieve_context
    rag_context = await retrieve_context(last_msg.content)

    # Call AI
    from core.ai_client import chat as ai_chat
    from core.scope_checker import parse_claude_response
    ai_reply = await ai_chat(history, rag_context=rag_context)

    # Check if AI flagged this as out-of-scope (request_doctor action)
    parsed = parse_claude_response(ai_reply)
    if isinstance(parsed, dict) and parsed.get("action") == "request_doctor":
        reason = parsed.get("reason", "câu hỏi vượt phạm vi")
        specialty = parsed.get("specialty", "")
        notify_msg = (
            f"⚠️ Bot không thể trả lời câu hỏi này ({reason}"
            + (f" — chuyên khoa: {specialty}" if specialty else "")
            + "). Vui lòng trả lời trực tiếp."
        )
        await ws_manager.send_to_doctor(doctor["sub"], {
            "event": "delegate_rejected",
            "case_id": case_id,
            "content": notify_msg,
        })
        return {"ok": False, "reason": notify_msg}

    # Send to patient
    from bot.relay import send_to_session
    await send_to_session(session, ai_reply)

    # Save as bot message
    bot_msg = Message(session_id=session.id, role=MessageRole.bot, content=ai_reply)
    db.add(bot_msg)
    await db.commit()

    # Broadcast to doctor dashboard
    await ws_manager.send_to_doctor(doctor["sub"], {
        "event": "doctor_message",
        "case_id": case_id,
        "content": f"🤖 [MedBot AI]\n{ai_reply}",
        "doctor_name": "MedBot AI",
    })

    return {"ok": True, "reply": ai_reply}
