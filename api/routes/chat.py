import os
import uuid
import logging
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import get_db
from db.models import Session as DBSession, Message, MessageRole, SessionStatus
from core.ai_client import chat as ai_chat
from core.rag import retrieve_context
from core.scope_checker import regex_check, parse_claude_response
from core.file_processor import process_file, build_content, cleanup_temp_file
from core.config import get_settings as _get_settings
from db.redis_client import get_online_doctors

logger = logging.getLogger(__name__)
router = APIRouter()

MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class ChatRequest(BaseModel):
    platform: str = "telegram"          # "telegram" | "zalo"
    telegram_chat_id: int | None = None
    zalo_user_id: str | None = None
    user_id: str
    message: str
    session_id: str | None = None


async def _get_or_create_session(
    db: AsyncSession,
    req: "ChatRequest",
) -> DBSession:
    if req.session_id:
        result = await db.execute(
            select(DBSession).where(DBSession.id == uuid.UUID(req.session_id))
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    if req.platform == "zalo":
        filter_cond = DBSession.zalo_user_id == req.zalo_user_id
        new_kwargs = {"platform": "zalo", "zalo_user_id": req.zalo_user_id}
    else:
        filter_cond = DBSession.telegram_chat_id == req.telegram_chat_id
        new_kwargs = {"platform": "telegram", "telegram_chat_id": req.telegram_chat_id}

    result = await db.execute(
        select(DBSession)
        .where(filter_cond, DBSession.status != SessionStatus.closed)
        .order_by(DBSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session:
        return session

    session = DBSession(user_id=req.user_id, status=SessionStatus.pending, **new_kwargs)
    db.add(session)
    await db.flush()
    return session


async def _get_session_history(db: AsyncSession, session: DBSession) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at)
        .limit(20)
    )
    messages = result.scalars().all()
    history = []
    for m in messages:
        role = "user" if m.role == MessageRole.user else "assistant"
        history.append({"role": role, "content": m.content})
    return history


async def _save_message(
    db: AsyncSession,
    session: DBSession,
    role: MessageRole,
    content: str,
    file_type: str | None = None,
    file_extracted: str | None = None,
) -> None:
    from datetime import datetime
    msg = Message(
        session_id=session.id,
        role=role,
        content=content,
        file_type=file_type,
        file_extracted=file_extracted,
    )
    db.add(msg)
    session.last_activity_at = datetime.utcnow()


_CLINIC_KEYWORDS = [
    "phòng khám", "cơ sở y tế", "địa chỉ", "giờ làm việc", "giờ mở cửa",
    "đặt lịch", "bác sĩ", "chuyên khoa", "dịch vụ", "bảng giá", "chi phí",
    "khám bao nhiêu", "liên hệ", "số điện thoại", "website", "medbot",
    "bác sĩ nào", "ai đang trực", "đang online", "trực tuyến", "giới thiệu bác sĩ",
]


async def _build_extra_context(message: str) -> str | None:
    """Inject online doctor list when user asks about doctors or the clinic."""
    msg_lower = message.lower()
    if not any(kw in msg_lower for kw in _CLINIC_KEYWORDS):
        return None

    doctors = await get_online_doctors()
    if not doctors:
        return "DANH SÁCH BÁC SĨ ĐANG TRỰC TUYẾN: Hiện không có bác sĩ nào đang online."

    lines = ["DANH SÁCH BÁC SĨ ĐANG TRỰC TUYẾN:"]
    for d in doctors:
        lines.append(f"- {d['name']} | Chuyên khoa: {d['specialty']} | Trạng thái: Online")
    return "\n".join(lines)


async def _handle_out_of_scope(scope_data: dict, specialty: str | None) -> dict:
    doctors = await get_online_doctors(specialty)
    return {
        "type": "request_doctor",
        "reason": scope_data.get("reason", "Câu hỏi ngoài phạm vi AI"),
        "specialty": scope_data.get("specialty", specialty or "Nội tổng quát"),
        "urgency": scope_data.get("urgency", "medium"),
        "doctors": doctors,
    }


@router.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    session = await _get_or_create_session(db, req)

    # Doctor is assigned → forward everything, bot must not interfere.
    if session.doctor_id and session.status != SessionStatus.closed:
        await _save_message(db, session, MessageRole.user, req.message)
        await db.commit()
        from api.websocket import ws_manager
        await ws_manager.relay_user_message(
            str(session.id), req.message, str(session.doctor_id)
        )
        return {"type": "forwarded_to_doctor", "session_id": str(session.id)}

    # Regex pre-check
    if regex_check(req.message):
        scope_data = {
            "reason": "Câu hỏi liên quan đến thuốc / chẩn đoán / thủ thuật",
            "specialty": "Nội tổng quát",
            "urgency": "medium",
        }
        await _save_message(db, session, MessageRole.user, req.message)
        await db.commit()
        return await _handle_out_of_scope(scope_data, None)

    history = await _get_session_history(db, session)
    history.append({"role": "user", "content": req.message})

    rag_context = await retrieve_context(req.message)
    extra_context = await _build_extra_context(req.message)
    if extra_context:
        rag_context = (rag_context or "") + "\n\n" + extra_context

    reply_text = await ai_chat(history, rag_context=rag_context or None)

    scope_data = parse_claude_response(reply_text)
    if scope_data:
        await _save_message(db, session, MessageRole.user, req.message)
        await db.commit()
        return await _handle_out_of_scope(scope_data, scope_data.get("specialty"))

    await _save_message(db, session, MessageRole.user, req.message)
    await _save_message(db, session, MessageRole.bot, reply_text)
    await db.commit()
    return {"type": "ai_reply", "content": reply_text, "session_id": str(session.id)}


@router.post("/api/chat/file")
async def chat_file_endpoint(
    file: UploadFile = File(...),
    chat_id: int = Form(...),
    user_id: str = Form(...),
    caption: str = Form(default=""),
    session_id: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    suffix = os.path.splitext(file.filename or "")[1].lower()
    mime = MIME_MAP.get(suffix, file.content_type or "application/octet-stream")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(400, "File vượt quá 20MB")
            tmp.write(content)

        file_result = process_file(tmp_path, mime)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        cleanup_temp_file(tmp_path)

    _file_req = ChatRequest(platform="telegram", telegram_chat_id=chat_id, user_id=user_id, message="", session_id=session_id)
    session = await _get_or_create_session(db, _file_req)
    user_message = caption or "Tôi đã gửi một file."

    # Doctor is assigned → save file message and forward, no AI call.
    if session.doctor_id and session.status != SessionStatus.closed:
        file_type = file_result.get("file_type")
        if file_result["type"] == "text":
            file_extracted = file_result.get("content")
        else:
            file_extracted = f"data:{file_result['media_type']};base64,{file_result['data']}"
        await _save_message(
            db, session, MessageRole.user, user_message,
            file_type=file_type, file_extracted=file_extracted
        )
        await db.commit()
        from api.websocket import ws_manager
        await ws_manager.relay_user_message(
            str(session.id), user_message, str(session.doctor_id)
        )
        return {"type": "forwarded_to_doctor", "session_id": str(session.id)}

    engine = _get_settings().AI_ENGINE
    file_content = build_content(file_result, user_message, engine)
    messages = [{"role": "user", "content": file_content}]

    rag_context = await retrieve_context(user_message)
    reply_text = await ai_chat(messages, rag_context=rag_context)

    scope_data = parse_claude_response(reply_text)

    file_type = file_result.get("file_type")
    if file_result["type"] == "text":
        file_extracted = file_result.get("content")
    else:
        # Base64-encode image so dashboard can render it as a data URI
        file_extracted = f"data:{file_result['media_type']};base64,{file_result['data']}"

    await _save_message(
        db, session, MessageRole.user, user_message,
        file_type=file_type, file_extracted=file_extracted
    )

    if scope_data:
        await db.commit()
        return await _handle_out_of_scope(scope_data, scope_data.get("specialty"))

    await _save_message(db, session, MessageRole.bot, reply_text)
    await db.commit()
    return {"type": "ai_reply", "content": reply_text, "session_id": str(session.id)}


@router.get("/api/doctors/online")
async def doctors_online(specialty: str | None = None):
    doctors = await get_online_doctors(specialty)
    return {"doctors": doctors}
