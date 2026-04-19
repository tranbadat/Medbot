import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🩺 Tư vấn sức khoẻ", callback_data="menu:consult"),
            InlineKeyboardButton("📅 Lịch khám", callback_data="menu:appointment"),
        ],
        [
            InlineKeyboardButton("🏥 Thông tin phòng khám", callback_data="menu:info"),
            InlineKeyboardButton("🆘 SOS / Khẩn cấp", callback_data="menu:sos"),
        ],
    ])


async def show_welcome(reply_fn, tg_user) -> None:
    name = tg_user.first_name if tg_user else "bạn"
    await reply_fn(
        f"👋 Xin chào *{name}*! Chào mừng đến với *{settings.CLINIC_NAME}*.\n\n"
        f"Tôi là MedBot — trợ lý sức khoẻ AI của phòng khám. Tôi có thể giúp bạn:\n\n"
        f"🩺 *Tư vấn sức khoẻ* — hỏi đáp triệu chứng, phòng ngừa bệnh\n"
        f"📅 *Lịch khám* — đặt lịch hoặc xem lịch đã đặt\n"
        f"🏥 *Thông tin* — địa chỉ, giờ làm việc, dịch vụ\n"
        f"🆘 *SOS* — số khẩn cấp và gọi nhanh\n\n"
        f"Chọn một tuỳ chọn hoặc nhắn tin trực tiếp:",
        parse_mode="Markdown",
        reply_markup=_main_menu(),
    )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _upsert_patient(update)
    context.user_data['_welcomed'] = True
    await show_welcome(update.message.reply_text, update.effective_user)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu:consult":
        await query.message.reply_text(
            "🩺 *Tư vấn sức khoẻ*\n\nHãy mô tả triệu chứng hoặc câu hỏi sức khoẻ của bạn. "
            "Tôi sẽ tư vấn và kết nối bác sĩ nếu cần.",
            parse_mode="Markdown",
        )

    elif data == "menu:appointment":
        await _show_appointments(query, update.effective_chat.id)

    elif data == "menu:info":
        await _show_clinic_info(query)

    elif data == "menu:sos":
        await _show_sos(query)

    elif data == "menu:back":
        await query.message.reply_text(
            "Chọn một tuỳ chọn:",
            reply_markup=_main_menu(),
        )


def _fmt_phone(phone: str) -> str:
    """Format phone for Telegram auto-link: strip leading 0, add +84."""
    p = phone.strip()
    if p.startswith("0"):
        p = "+84" + p[1:]
    elif not p.startswith("+"):
        p = "+84" + p
    return p


async def _show_clinic_info(query) -> None:
    s = settings
    phone_fmt = _fmt_phone(s.CLINIC_PHONE)
    text = (
        f"🏥 *{s.CLINIC_NAME}*\n\n"
        f"📍 *Địa chỉ:* {s.CLINIC_ADDRESS}\n"
        f"📞 *Điện thoại:* {phone_fmt}\n"
        f"✉️ *Email:* {s.CLINIC_EMAIL}\n"
        f"🕐 *Giờ làm việc:* {s.CLINIC_HOURS}\n\n"
        f"_Nhấn vào số điện thoại trên để gọi trực tiếp_"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Menu", callback_data="menu:back"),
    ]])
    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def _show_sos(query) -> None:
    s = settings
    phone_fmt = _fmt_phone(s.CLINIC_PHONE)
    text = (
        "🆘 *Khẩn cấp / SOS*\n\n"
        "Nếu bạn hoặc người thân đang trong tình trạng khẩn cấp, "
        "hãy nhấn vào số điện thoại bên dưới để gọi ngay:\n\n"
        f"🚨 Cấp cứu quốc gia: *+115*\n"
        f"🏥 Phòng khám: *{phone_fmt}*\n\n"
        "⚠️ _Đừng chờ đợi khi có triệu chứng: khó thở, đau ngực, mất ý thức, chảy máu không cầm được._"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Menu", callback_data="menu:back"),
    ]])
    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def _show_appointments(query, chat_id: int) -> None:
    from db.database import AsyncSessionLocal
    from db.models import Appointment, AppointmentStatus
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
        rows = []
        for appt in appointments:
            date_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
            icon = {"pending": "🕐", "confirmed": "✅", "cancelled": "❌"}.get(appt.status.value, "🕐")
            doc_name = appt.doctor.name if appt.doctor else "Chưa phân công"
            lines.append(f"{icon} {date_str} — {doc_name}")
            if appt.status.value != "cancelled":
                rows.append([InlineKeyboardButton(
                    f"❌ Huỷ lịch {date_str}",
                    callback_data=f"cancel_appt:{str(appt.id)}",
                )])
        rows.append([InlineKeyboardButton("📅 Đặt lịch mới", callback_data="bk:start")])
        rows.append([InlineKeyboardButton("🔙 Menu", callback_data="menu:back")])
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    else:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Đặt lịch khám", callback_data="bk:start")],
            [InlineKeyboardButton("🔙 Menu", callback_data="menu:back")],
        ])
        await query.message.reply_text(
            "Bạn chưa có lịch khám nào.\nBạn có muốn đặt lịch không?",
            reply_markup=markup,
        )


async def _upsert_patient(update: Update) -> None:
    tg_user = update.effective_user
    if not tg_user:
        return
    chat_id = update.effective_chat.id
    from db.database import AsyncSessionLocal
    from db.models import Patient
    from sqlalchemy import select
    from datetime import datetime

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Patient).where(Patient.telegram_chat_id == chat_id))
        patient = result.scalar_one_or_none()
        if patient:
            patient.last_seen = datetime.utcnow()
            patient.telegram_name = tg_user.full_name
            patient.telegram_username = tg_user.username
        else:
            patient = Patient(
                telegram_chat_id=chat_id,
                telegram_name=tg_user.full_name,
                telegram_username=tg_user.username,
            )
            db.add(patient)
        await db.commit()
