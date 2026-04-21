import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

URGENCY_MAP = {"l": "low", "m": "medium", "h": "high"}


async def show_out_of_scope_cta(reply_fn, result: dict) -> None:
    """Show 3-CTA message when AI decides the question needs a doctor."""
    from core.config import get_settings
    from bot.handlers.start import _fmt_phone
    s = get_settings()
    phone_fmt = _fmt_phone(s.CLINIC_PHONE)
    reason = result.get("reason", "Câu hỏi này cần bác sĩ tư vấn trực tiếp")
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Đặt lịch khám", callback_data="bk:start"),
        InlineKeyboardButton(f"📞 Gọi ngay", url=f"tel:{phone_fmt}"),
        InlineKeyboardButton("👨‍⚕️ Gặp bác sĩ", callback_data="cta:doctor"),
    ]])
    await reply_fn(
        f"⚠️ *{reason}*\n\nBạn có thể:",
        parse_mode="Markdown",
        reply_markup=markup,
    )


def _nodash_to_uuid(nodash: str) -> str:
    return f"{nodash[:8]}-{nodash[8:12]}-{nodash[12:16]}-{nodash[16:20]}-{nodash[20:]}"


def _doctor_card_text(doctor: dict, index: int, total: int) -> str:
    name = doctor.get("name", "Bác sĩ")
    specialty = doctor.get("specialty", "")
    hours = doctor.get("working_hours", "8:00 - 17:00 (T2-T7)")
    return (
        f"👨‍⚕️ *{name}*\n"
        f"🩺 Chuyên khoa: {specialty}\n"
        f"🕐 Giờ làm việc: {hours}\n"
        f"🟢 Đang trực tuyến\n\n"
        f"_{index + 1} / {total} bác sĩ_"
    )


def _carousel_keyboard(doctors: list, index: int, urgency: str) -> InlineKeyboardMarkup:
    doctor = doctors[index]
    nodash = doctor["id"].replace("-", "")
    nav_row = []
    if len(doctors) > 1:
        prev_idx = (index - 1) % len(doctors)
        next_idx = (index + 1) % len(doctors)
        nav_row.append(InlineKeyboardButton("◀", callback_data=f"dc:{prev_idx}:{urgency}"))
        nav_row.append(InlineKeyboardButton("▶", callback_data=f"dc:{next_idx}:{urgency}"))
    select_row = [InlineKeyboardButton("✅ Chọn bác sĩ này", callback_data=f"sd:{nodash}:{urgency}")]
    rows = [select_row]
    if nav_row:
        rows.insert(0, nav_row)
    return InlineKeyboardMarkup(rows)


async def send_doctor_carousel(
    send_fn,
    doctors: list,
    index: int,
    urgency: str,
    header: str = "🏥 *Chọn bác sĩ tư vấn*\n\n",
) -> None:
    """Send or edit a message with the doctor carousel."""
    doctor = doctors[index]
    text = header + _doctor_card_text(doctor, index, len(doctors))
    markup = _carousel_keyboard(doctors, index, urgency)
    await send_fn(text, parse_mode="Markdown", reply_markup=markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""

    # ── Carousel navigation: dc:{index}:{urgency} ──────────────────────────
    if data.startswith("dc:"):
        parts = data.split(":")
        index = int(parts[1])
        urgency = parts[2] if len(parts) > 2 else "m"

        from db.redis_client import get_online_doctors
        doctors = await get_online_doctors()
        if not doctors:
            await query.edit_message_text("Hiện không có bác sĩ nào trực tuyến.")
            return

        index = index % len(doctors)
        doctor = doctors[index]
        text = "🏥 *Chọn bác sĩ tư vấn*\n\n" + _doctor_card_text(doctor, index, len(doctors))
        markup = _carousel_keyboard(doctors, index, urgency)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return

    # ── Select doctor: sd:{uuid_nodash}:{urgency} ──────────────────────────
    if data.startswith("sd:"):
        parts = data.split(":")
        if len(parts) < 2:
            return

        doctor_id = _nodash_to_uuid(parts[1])
        urgency = URGENCY_MAP.get(parts[2] if len(parts) > 2 else "m", "medium")

        chat_id = update.effective_chat.id
        user_id = f"tg_{chat_id}"

        from db.database import AsyncSessionLocal
        from db.models import Doctor
        from sqlalchemy import select
        import uuid

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(doctor_id)))
            doctor = result.scalar_one_or_none()

            if not doctor:
                await query.edit_message_text("Bác sĩ không còn khả dụng. Vui lòng chọn lại.")
                return

            from api.routes.session import ConnectRequest, connect_session
            req = ConnectRequest(
                telegram_chat_id=chat_id,
                user_id=user_id,
                doctor_id=doctor_id,
                specialty=doctor.specialty,
                urgency=urgency,
                summary=f"User yêu cầu tư vấn về {doctor.specialty}",
            )
            await connect_session(req, db)

        await query.edit_message_text(
            f"✅ Đã gửi yêu cầu đến *{doctor.name}*.\nVui lòng chờ bác sĩ xác nhận.",
            parse_mode="Markdown",
        )
        return

    # ── Out-of-scope CTA: cta:doctor ──────────────────────────────────────
    if data.startswith("cta:"):
        action = data[4:]
        if action == "doctor":
            await _handle_cta_doctor(query, update)
        return


async def _handle_cta_doctor(query, update: Update) -> None:
    """Generate AI summary of conversation then show doctor carousel."""
    chat_id = update.effective_chat.id

    from db.database import AsyncSessionLocal
    from db.models import Session as DBSession, Message, SessionStatus
    from sqlalchemy import select

    summary = "Người dùng cần tư vấn sức khoẻ"

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession)
            .where(DBSession.telegram_chat_id == chat_id,
                   DBSession.status == SessionStatus.pending)
            .order_by(DBSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session:
            msgs_result = await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at)
                .limit(20)
            )
            messages = msgs_result.scalars().all()
            if messages:
                history = [{"role": m.role.value, "content": m.content} for m in messages]
                try:
                    from core.ai_client import chat as ai_chat
                    history_for_summary = history + [{
                        "role": "user",
                        "content": "Tóm tắt vấn đề sức khoẻ của người dùng trong 2-3 câu ngắn gọn.",
                    }]
                    summary = await ai_chat(history_for_summary, max_tokens=150)
                except Exception as e:
                    logger.warning(f"AI summary failed: {e}")

    from db.redis_client import get_online_doctors
    doctors = await get_online_doctors()
    if doctors:
        await send_doctor_carousel(
            query.message.reply_text,
            doctors,
            index=0,
            urgency="m",
            header=f"👨‍⚕️ *Kết nối bác sĩ*\n\n📋 _{summary}_\n\n",
        )
    else:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Đặt lịch khám", callback_data="bk:start"),
        ]])
        await query.message.reply_text(
            "⚠️ Hiện không có bác sĩ nào trực tuyến.\n"
            "Bạn có thể đặt lịch khám để được tư vấn.",
            reply_markup=markup,
        )
