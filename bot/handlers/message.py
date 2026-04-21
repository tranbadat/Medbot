import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_APPOINTMENT_KEYWORDS = [
    "lịch khám", "đặt lịch", "đặt hẹn", "lịch hẹn", "lịch của tôi",
    "xem lịch", "kiểm tra lịch", "hẹn khám", "lịch tư vấn",
]


async def _upsert_patient(update: Update) -> None:
    from bot.handlers.start import _upsert_patient as _up
    await _up(update)


async def _in_active_doctor_session(chat_id: int) -> bool:
    from db.database import AsyncSessionLocal
    from db.models import Session as DBSession, SessionStatus
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession).where(
                DBSession.telegram_chat_id == chat_id,
                DBSession.status.in_([SessionStatus.active, SessionStatus.pending]),
                DBSession.doctor_id.isnot(None),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None


async def _is_profile_complete(chat_id: int) -> bool:
    from db.database import AsyncSessionLocal
    from db.models import Patient
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Patient.profile_complete).where(Patient.telegram_chat_id == chat_id))
        row = result.scalar_one_or_none()
        return bool(row)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_id = f"tg_{chat_id}"
    text = update.message.text

    await _upsert_patient(update)

    # Show welcome on first interaction (skip if in active doctor session)
    if not context.user_data.get('_welcomed'):
        context.user_data['_welcomed'] = True
        if not await _in_active_doctor_session(chat_id):
            profile_ok = await _is_profile_complete(chat_id)
            if not profile_ok:
                from bot.handlers.start import _main_menu
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                tg_name = update.effective_user.first_name if update.effective_user else "bạn"
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 Cập nhật hồ sơ", callback_data="profile:start"),
                    InlineKeyboardButton("⏭ Bỏ qua", callback_data="profile:skip_all"),
                ]])
                await update.message.reply_text(
                    f"👋 Xin chào *{tg_name}*! Chào mừng đến với MedBot.\n\n"
                    "Để tư vấn chính xác hơn, hãy cho tôi biết thông tin sức khoẻ cơ bản của bạn "
                    "(tuổi, cân nặng, chiều cao). Bạn có thể bỏ qua bất kỳ bước nào.",
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
                return
            from bot.handlers.start import show_welcome
            await show_welcome(update.message.reply_text, update.effective_user)
            return

    # Appointment keyword → show existing or booking button
    msg_lower = text.lower()
    if any(kw in msg_lower for kw in _APPOINTMENT_KEYWORDS):
        await _handle_appointment_query(update, chat_id)
        return

    await update.message.chat.send_action("typing")

    from api.routes.chat import chat_endpoint, ChatRequest

    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        req = ChatRequest(platform="telegram", telegram_chat_id=chat_id, user_id=user_id, message=text)
        result = await chat_endpoint(req, db)

    if result.get("type") == "ai_reply":
        await update.message.reply_text(result["content"])

    elif result.get("type") == "request_doctor":
        from bot.handlers.callback import show_out_of_scope_cta
        await show_out_of_scope_cta(update.message.reply_text, result)

    elif result.get("type") == "forwarded_to_doctor":
        pass  # Already in doctor session — message forwarded, no echo needed


async def _handle_appointment_query(update: Update, chat_id: int) -> None:
    from db.database import AsyncSessionLocal
    from db.models import Appointment, AppointmentStatus, Doctor
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.doctor))
            .where(
                Appointment.telegram_chat_id == chat_id,
                Appointment.status != AppointmentStatus.cancelled,
            )
            .order_by(Appointment.appointment_date)
        )
        appointments = result.scalars().all()

    if appointments:
        lines = ["📅 *Lịch khám của bạn:*\n"]
        for appt in appointments:
            date_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
            status_icon = {"pending": "🕐", "confirmed": "✅", "cancelled": "❌"}.get(appt.status.value, "🕐")
            doctor_str = f" · {appt.doctor.name}" if appt.doctor else ""
            lines.append(f"{status_icon} {date_str}{doctor_str} _{appt.status.value}_")
        lines.append("")
        lines.append("Bạn có muốn đặt thêm lịch mới không?")
        text = "\n".join(lines)
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Đặt lịch mới", callback_data="bk:start")
        ]])
    else:
        text = "Bạn chưa có lịch khám nào. Bạn có muốn đặt lịch không?"
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Đặt lịch khám", callback_data="bk:start")
        ]])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
