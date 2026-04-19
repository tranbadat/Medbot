import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

URGENCY_MAP = {"l": "low", "m": "medium", "h": "high"}


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
