import calendar
import logging
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────
CONFIRM_NAME, TYPE_NAME, SELECT_DATE, SELECT_TIME, SELECT_DOCTOR, CONFIRM = range(6)

# Time slots 08:00–16:30 every 30 min
_TIME_SLOTS = [
    f"{h:02d}:{m:02d}"
    for h in range(8, 17)
    for m in (0, 30)
    if not (h == 16 and m == 30)
]


# ── Calendar builder ───────────────────────────────────────────────────────

def _calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    today = date.today()
    cal = calendar.monthcalendar(year, month)
    month_name = f"Tháng {month}/{year}"

    prev_month = date(year, month, 1) - timedelta(days=1)
    next_month = date(year, month, 28) + timedelta(days=4)
    next_month = next_month.replace(day=1)

    rows = []
    # Navigation row
    rows.append([
        InlineKeyboardButton("◀", callback_data=f"cal:nav:{prev_month.year}:{prev_month.month}"),
        InlineKeyboardButton(month_name, callback_data="cal:noop"),
        InlineKeyboardButton("▶", callback_data=f"cal:nav:{next_month.year}:{next_month.month}"),
    ])
    # Day-of-week headers
    rows.append([InlineKeyboardButton(d, callback_data="cal:noop") for d in ["T2","T3","T4","T5","T6","T7","CN"]])
    # Day grid
    for week in cal:
        row = []
        for day_num in week:
            if day_num == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal:noop"))
            else:
                d = date(year, month, day_num)
                if d < today:
                    row.append(InlineKeyboardButton("·", callback_data="cal:noop"))
                else:
                    row.append(InlineKeyboardButton(
                        str(day_num),
                        callback_data=f"cal:day:{year}:{month}:{day_num}",
                    ))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _time_keyboard(year: int, month: int, day: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, slot in enumerate(_TIME_SLOTS):
        h, m = slot.split(":")
        row.append(InlineKeyboardButton(slot, callback_data=f"ts:{year}:{month}:{day}:{h}:{m}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def _doctor_keyboard() -> InlineKeyboardMarkup:
    from db.database import AsyncSessionLocal
    from db.models import Doctor
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Doctor).where(Doctor.is_active == True).order_by(Doctor.name)
        )
        doctors = result.scalars().all()

    rows = []
    for doc in doctors:
        hours = doc.working_hours or "8:00-17:00"
        label = f"👨‍⚕️ {doc.name} · {doc.specialty}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bk:doc:{str(doc.id).replace('-','')}")])
    rows.append([InlineKeyboardButton("⏭ Không chọn cụ thể", callback_data="bk:doc:skip")])
    return InlineKeyboardMarkup(rows)


def _summary_text(data: dict) -> str:
    dt: datetime = data.get("datetime")
    date_str = dt.strftime("%d/%m/%Y %H:%M") if dt else "?"
    doctor_str = data.get("doctor_name") or "Sẽ được phân công"
    return (
        f"📋 *Xác nhận đặt lịch*\n\n"
        f"👤 Họ tên: {data.get('name', '?')}\n"
        f"📅 Ngày giờ: {date_str}\n"
        f"👨‍⚕️ Bác sĩ: {doctor_str}"
    )


# ── Entry ──────────────────────────────────────────────────────────────────

async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["booking"] = {}

    tg_user = update.effective_user
    tg_name = tg_user.full_name if tg_user else ""

    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text

    if tg_name:
        context.user_data["booking"]["_tg_name"] = tg_name
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Dùng tên: {tg_name}", callback_data="bk:name:confirm"),
            InlineKeyboardButton("✏️ Nhập tên khác", callback_data="bk:name:edit"),
        ]])
        await reply(
            "📝 *Đặt lịch khám*\n\nXác nhận họ tên đặt lịch:",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        return CONFIRM_NAME
    else:
        await reply("📝 *Đặt lịch khám*\n\nVui lòng nhập *họ và tên*:", parse_mode="Markdown")
        return TYPE_NAME


# ── Name step ─────────────────────────────────────────────────────────────

async def handle_name_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "bk:name:confirm":
        context.user_data["booking"]["name"] = context.user_data["booking"].pop("_tg_name")
        return await _show_calendar(query.message.reply_text, context)
    else:
        await query.message.reply_text("Vui lòng nhập họ và tên:")
        return TYPE_NAME


async def receive_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["booking"]["name"] = update.message.text.strip()
    return await _show_calendar(update.message.reply_text, context)


async def _show_calendar(reply_fn, context: ContextTypes.DEFAULT_TYPE) -> int:
    today = date.today()
    markup = _calendar_keyboard(today.year, today.month)
    await reply_fn("📅 Chọn *ngày khám*:", parse_mode="Markdown", reply_markup=markup)
    return SELECT_DATE


# ── Date / Time step ───────────────────────────────────────────────────────

async def handle_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cal:noop":
        return SELECT_DATE

    if data.startswith("cal:nav:"):
        _, _, year, month = data.split(":")
        markup = _calendar_keyboard(int(year), int(month))
        await query.edit_message_reply_markup(markup)
        return SELECT_DATE

    if data.startswith("cal:day:"):
        _, _, year, month, day = data.split(":")
        context.user_data["booking"]["_date"] = (int(year), int(month), int(day))
        markup = _time_keyboard(int(year), int(month), int(day))
        d_str = f"{day}/{month}/{year}"
        await query.edit_message_text(
            f"📅 Ngày: *{d_str}*\n\n🕐 Chọn *giờ khám*:",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        return SELECT_TIME

    return SELECT_DATE


async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, year, month, day, hour, minute = query.data.split(":")
    dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
    context.user_data["booking"]["datetime"] = dt
    context.user_data["booking"].pop("_date", None)

    markup = await _doctor_keyboard()
    await query.edit_message_text(
        f"📅 *{dt.strftime('%d/%m/%Y %H:%M')}*\n\n👨‍⚕️ Chọn *bác sĩ* (tuỳ chọn):",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    return SELECT_DOCTOR


# ── Doctor step ────────────────────────────────────────────────────────────

async def handle_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "bk:doc:skip":
        context.user_data["booking"]["doctor_id"] = None
        context.user_data["booking"]["doctor_name"] = None
    else:
        nodash = data.split(":")[-1]
        doctor_id = f"{nodash[:8]}-{nodash[8:12]}-{nodash[12:16]}-{nodash[16:20]}-{nodash[20:]}"
        from db.database import AsyncSessionLocal
        from db.models import Doctor as DBDoctor
        from sqlalchemy import select
        import uuid
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(DBDoctor).where(DBDoctor.id == uuid.UUID(doctor_id)))
            doc = result.scalar_one_or_none()
        context.user_data["booking"]["doctor_id"] = doctor_id if doc else None
        context.user_data["booking"]["doctor_name"] = doc.name if doc else None

    text = _summary_text(context.user_data["booking"])
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Xác nhận", callback_data="bk:confirm"),
        InlineKeyboardButton("❌ Huỷ", callback_data="bk:cancel"),
    ]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    return CONFIRM


# ── Confirm step ───────────────────────────────────────────────────────────

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "bk:cancel":
        context.user_data.pop("booking", None)
        await query.edit_message_text("❌ Đã huỷ đặt lịch.")
        return ConversationHandler.END

    booking = context.user_data.get("booking", {})
    chat_id = update.effective_chat.id

    from db.database import AsyncSessionLocal
    from db.models import Appointment, AppointmentStatus
    import uuid

    async with AsyncSessionLocal() as db:
        appt = Appointment(
            telegram_chat_id=chat_id,
            patient_name=booking["name"],
            doctor_id=uuid.UUID(booking["doctor_id"]) if booking.get("doctor_id") else None,
            appointment_date=booking["datetime"],
            status=AppointmentStatus.pending,
        )
        db.add(appt)
        await db.commit()
        await db.refresh(appt)

    dt: datetime = booking["datetime"]
    doctor_str = booking.get("doctor_name") or "Sẽ được phân công"
    await query.edit_message_text(
        f"✅ *Đặt lịch thành công!*\n\n"
        f"📋 Mã lịch: `{str(appt.id)[:8]}`\n"
        f"👤 Tên: {booking['name']}\n"
        f"📅 Ngày giờ: {dt.strftime('%d/%m/%Y %H:%M')}\n"
        f"👨‍⚕️ Bác sĩ: {doctor_str}\n\n"
        f"Phòng khám sẽ xác nhận lịch hẹn sớm nhất có thể. 🙏",
        parse_mode="Markdown",
    )
    context.user_data.pop("booking", None)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("booking", None)
    await update.message.reply_text("❌ Đã huỷ đặt lịch.")
    return ConversationHandler.END


# ── Build handler ──────────────────────────────────────────────────────────

def build_appointment_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_booking, pattern="^bk:start$"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)đặt lịch|đặt hẹn"),
                start_booking,
            ),
        ],
        states={
            CONFIRM_NAME: [CallbackQueryHandler(handle_name_choice, pattern="^bk:name:")],
            TYPE_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name_text)],
            SELECT_DATE:  [CallbackQueryHandler(handle_calendar, pattern="^cal:")],
            SELECT_TIME:  [CallbackQueryHandler(handle_time, pattern="^ts:")],
            SELECT_DOCTOR:[CallbackQueryHandler(handle_doctor, pattern="^bk:doc:")],
            CONFIRM:      [CallbackQueryHandler(confirm_booking, pattern="^bk:(confirm|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True,
        per_user=False,
        allow_reentry=True,
    )
