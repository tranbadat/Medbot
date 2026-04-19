"""Zalo OA webhook handler."""
import hmac
import hashlib
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from core.config import get_settings

logger = logging.getLogger(__name__)

_APPOINTMENT_KEYWORDS = [
    "lịch khám", "đặt lịch", "đặt hẹn", "lịch hẹn", "lịch của tôi",
    "xem lịch", "kiểm tra lịch", "hẹn khám", "lịch tư vấn",
]

_WELCOME_SHOWN_PREFIX = "zalo_welcomed:"


def _verify_mac(body: bytes, signature_header: str) -> bool:
    secret = get_settings().ZALO_APP_SECRET
    if not secret:
        return True  # dev mode: skip verification
    mac_value = signature_header.split("mac=")[-1] if "mac=" in signature_header else signature_header
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac_value)


# ── Webhook entry ──────────────────────────────────────────────────────────

async def handle_zalo_webhook(request: Request) -> JSONResponse:
    body = await request.body()
    sig = request.headers.get("X-ZaloOA-Signature", "")

    if not _verify_mac(body, sig):
        raise HTTPException(403, "Invalid signature")

    try:
        data = request.state.json_body if hasattr(request.state, "json_body") else __import__("json").loads(body)
    except Exception:
        return JSONResponse({"error": 0})

    event = data.get("event_name", "")
    user_id = (data.get("sender") or {}).get("id") or data.get("user_id_by_app")

    if not user_id:
        return JSONResponse({"error": 0})

    if event == "follow":
        await _handle_follow(user_id)
    elif event in ("user_send_text", "user_send_link"):
        text = (data.get("message") or {}).get("text", "")
        await _handle_text(user_id, text)
    elif event == "user_send_image":
        attachments = (data.get("message") or {}).get("attachments", [])
        await _handle_image(user_id, attachments)
    elif event == "user_send_audio":
        attachments = (data.get("message") or {}).get("attachments", [])
        await _handle_audio_event(user_id, attachments)
    elif event == "user_send_file":
        attachments = (data.get("message") or {}).get("attachments", [])
        await _handle_file_event(user_id, attachments)

    return JSONResponse({"error": 0})


# ── Event handlers ─────────────────────────────────────────────────────────

async def _handle_follow(user_id: str) -> None:
    profile = await _upsert_patient(user_id)
    name = (profile or {}).get("display_name", "bạn")
    await _show_welcome(user_id, name)


async def _handle_text(user_id: str, text: str) -> None:
    if not text.strip():
        return

    profile = await _upsert_patient(user_id)

    # Booking flow takes priority
    from bot.zalo.booking import handle_booking_input
    if await handle_booking_input(user_id, text):
        return

    # Trigger booking start
    if text == "bk:start" or any(kw in text.lower() for kw in _APPOINTMENT_KEYWORDS):
        await _handle_appointment_query(user_id, profile)
        return

    # Welcome trigger from menu button
    if text == "menu:consult":
        from core.zalo_client import send_text
        await send_text(user_id, "🩺 *Tư vấn sức khoẻ*\n\nHãy mô tả triệu chứng hoặc câu hỏi sức khoẻ của bạn.")
        return
    if text == "menu:info":
        await _show_clinic_info(user_id)
        return
    if text == "menu:sos":
        await _show_sos(user_id)
        return

    # Show welcome on first message
    from db.redis_client import get_redis
    r = await get_redis()
    welcomed = await r.get(f"{_WELCOME_SHOWN_PREFIX}{user_id}")
    if not welcomed:
        await r.setex(f"{_WELCOME_SHOWN_PREFIX}{user_id}", 86400 * 30, "1")
        name = (profile or {}).get("display_name", "bạn") if profile else "bạn"
        await _show_welcome(user_id, name)
        return

    # Route to AI chat endpoint
    await _route_to_chat(user_id, text)


async def _handle_image(user_id: str, attachments: list) -> None:
    if not attachments:
        return
    url = (attachments[0].get("payload") or {}).get("url", "")
    if not url:
        return
    await _process_remote_image(user_id, url)


async def _handle_audio_event(user_id: str, attachments: list) -> None:
    from core.zalo_client import send_text
    if not attachments:
        return
    audio_url = (attachments[0].get("payload") or {}).get("url", "")
    if not audio_url:
        await send_text(user_id, "❌ Không tải được file âm thanh.")
        return

    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(audio_url)
            audio_bytes = r.content
    except Exception as e:
        logger.warning(f"Failed to download Zalo audio: {e}")
        await send_text(user_id, "❌ Không tải được file âm thanh. Vui lòng thử lại.")
        return

    await send_text(user_id, "🎙 Đang xử lý bản ghi âm...")
    from core.audio_transcriber import transcribe
    text = await transcribe(audio_bytes, "audio.m4a")
    if not text:
        await send_text(user_id, "❌ Không thể chuyển đổi giọng nói. Vui lòng nhắn tin hoặc thử lại.")
        return

    await send_text(user_id, f"📝 Đã nhận: {text}")
    await _route_to_chat(user_id, text)


async def _handle_file_event(user_id: str, attachments: list) -> None:
    from core.zalo_client import send_text
    await send_text(user_id, "📎 Tôi nhận được file của bạn. Hiện tại tôi chỉ xử lý được hình ảnh và văn bản.")


# ── Helpers ────────────────────────────────────────────────────────────────

async def _upsert_patient(user_id: str) -> dict | None:
    from core.zalo_client import get_user_profile
    from db.database import AsyncSessionLocal
    from db.models import Patient
    from sqlalchemy import select
    from datetime import datetime

    profile = await get_user_profile(user_id)
    name = (profile or {}).get("display_name", "")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Patient).where(Patient.zalo_user_id == user_id))
        patient = result.scalar_one_or_none()
        now = datetime.utcnow()
        if patient:
            patient.last_seen = now
            if name:
                patient.zalo_name = name
        else:
            patient = Patient(
                zalo_user_id=user_id,
                zalo_name=name or f"Zalo_{user_id[-6:]}",
            )
            db.add(patient)
        await db.commit()

    return profile


async def _show_welcome(user_id: str, name: str) -> None:
    from core.zalo_client import send_buttons
    from core.config import get_settings
    settings = get_settings()
    await send_buttons(
        user_id,
        f"👋 Xin chào {name}! Chào mừng đến với {settings.CLINIC_NAME}.\n\n"
        "Tôi là MedBot — trợ lý sức khoẻ AI. Tôi có thể giúp bạn:\n"
        "🩺 Tư vấn sức khoẻ\n📅 Đặt lịch khám\n🏥 Thông tin phòng khám\n🆘 SOS\n\n"
        "Chọn một tuỳ chọn:",
        [
            {"title": "🩺 Tư vấn sức khoẻ", "payload": "menu:consult"},
            {"title": "📅 Đặt lịch khám",   "payload": "bk:start"},
        ],
    )
    from core.zalo_client import send_buttons as _sb
    await _sb(
        user_id, " ",
        [
            {"title": "🏥 Thông tin phòng khám", "payload": "menu:info"},
            {"title": "🆘 SOS / Khẩn cấp",       "payload": "menu:sos"},
        ],
    )


async def _show_clinic_info(user_id: str) -> None:
    from core.zalo_client import send_text
    from core.config import get_settings
    s = get_settings()
    p = s.CLINIC_PHONE.lstrip("0")
    await send_text(
        user_id,
        f"🏥 {s.CLINIC_NAME}\n\n"
        f"📍 Địa chỉ: {s.CLINIC_ADDRESS}\n"
        f"📞 Điện thoại: +84{p}\n"
        f"✉️ Email: {s.CLINIC_EMAIL}\n"
        f"🕐 Giờ làm việc: {s.CLINIC_HOURS}",
    )


async def _show_sos(user_id: str) -> None:
    from core.zalo_client import send_text
    from core.config import get_settings
    s = get_settings()
    p = s.CLINIC_PHONE.lstrip("0")
    await send_text(
        user_id,
        "🆘 Khẩn cấp / SOS\n\n"
        "🚨 Cấp cứu quốc gia: +115\n"
        f"🏥 Phòng khám: +84{p}\n\n"
        "⚠️ Đừng chờ đợi khi có triệu chứng: khó thở, đau ngực, mất ý thức, chảy máu không cầm được.",
    )


async def _handle_appointment_query(user_id: str, profile: dict | None) -> None:
    from core.zalo_client import send_buttons, send_text
    from db.database import AsyncSessionLocal
    from db.models import Appointment, AppointmentStatus
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.doctor))
            .where(
                Appointment.zalo_user_id == user_id,
                Appointment.status != AppointmentStatus.cancelled,
            )
            .order_by(Appointment.appointment_date)
        )
        appointments = result.scalars().all()

    if appointments:
        lines = ["📅 Lịch khám của bạn:\n"]
        for appt in appointments:
            date_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
            icon = {"pending": "🕐", "confirmed": "✅", "cancelled": "❌"}.get(appt.status.value, "🕐")
            doc = appt.doctor.name if appt.doctor else "Chưa phân công"
            lines.append(f"{icon} {date_str} — {doc}")
        await send_buttons(
            user_id,
            "\n".join(lines),
            [{"title": "📅 Đặt lịch mới", "payload": "bk:start"}],
        )
    else:
        await send_buttons(
            user_id,
            "Bạn chưa có lịch khám nào.",
            [{"title": "📅 Đặt lịch khám", "payload": "bk:start"}],
        )

    # Trigger booking if user tapped "bk:start"
    # (handled in handle_booking_input on next message)


async def _route_to_chat(user_id: str, text: str) -> None:
    from core.zalo_client import send_text
    from api.routes.chat import chat_endpoint, ChatRequest
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        req = ChatRequest(
            platform="zalo",
            zalo_user_id=user_id,
            user_id=f"zalo_{user_id}",
            message=text,
        )
        result = await chat_endpoint(req, db)

    if result.get("type") == "ai_reply":
        await send_text(user_id, result["content"])

    elif result.get("type") == "request_doctor":
        doctors = result.get("doctors", [])
        if doctors:
            lines = [f"⚠️ {result.get('reason', 'Câu hỏi cần bác sĩ tư vấn')}\n\nDanh sách bác sĩ đang trực:"]
            for d in doctors:
                lines.append(f"👨‍⚕️ {d['name']} — {d.get('specialty', '')}")
            await send_text(user_id, "\n".join(lines))
            # Show select buttons (up to 3 doctors)
            from core.zalo_client import send_buttons
            urgency = result.get("urgency", "medium")
            btns = [{"title": f"Chọn {d['name']}", "payload": f"sd:{d['id'].replace('-','')}:{urgency[:1]}"} for d in doctors[:3]]
            await send_buttons(user_id, "Chọn bác sĩ để kết nối:", btns)
        else:
            await send_text(
                user_id,
                "⚠️ Câu hỏi này cần bác sĩ tư vấn trực tiếp, nhưng hiện không có bác sĩ trực tuyến.\n"
                "Vui lòng thử lại sau hoặc liên hệ phòng khám.",
            )

    elif result.get("type") == "forwarded_to_doctor":
        pass  # silent — doctor session active


async def _process_remote_image(user_id: str, image_url: str) -> None:
    """Download image from Zalo CDN, process via AI, reply."""
    import httpx
    from core.zalo_client import send_text
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(image_url)
            image_bytes = r.content
    except Exception as e:
        logger.warning(f"Failed to download Zalo image: {e}")
        await send_text(user_id, "❌ Không thể tải ảnh. Vui lòng thử lại.")
        return

    # Check if in doctor session — forward instead of AI
    from db.database import AsyncSessionLocal
    from db.models import Session as DBSession, SessionStatus, Message, MessageRole
    from sqlalchemy import select
    from api.websocket import ws_manager
    from datetime import datetime

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession).where(
                DBSession.zalo_user_id == user_id,
                DBSession.status != SessionStatus.closed,
                DBSession.doctor_id.isnot(None),
            ).limit(1)
        )
        session = result.scalar_one_or_none()

        if session:
            msg = Message(session_id=session.id, role=MessageRole.user, content="[Ảnh]",
                          file_type="image", file_extracted=None)
            db.add(msg)
            session.last_activity_at = datetime.utcnow()
            await db.commit()
            await ws_manager.relay_user_message(str(session.id), "[Ảnh từ bệnh nhân]", str(session.doctor_id))
            return

    # AI processing
    try:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        from core.ai_client import chat as ai_chat
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "Bệnh nhân gửi ảnh qua Zalo. Hãy mô tả và tư vấn nếu có thể."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]
        reply = await ai_chat(messages)
        await send_text(user_id, reply)
    except Exception as e:
        logger.error(f"Image AI processing failed: {e}")
        await send_text(user_id, "Tôi nhận được ảnh nhưng chưa thể xử lý. Bạn có thể mô tả bằng văn bản không?")
