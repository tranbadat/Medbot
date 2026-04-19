"""
Telegram conversation handler for medicine reminders.
States: TYPE_MEDICINE → SELECT_TIMES → CONFIRM
Time selection uses an inline button grid (tap to toggle, done to confirm).
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)

logger = logging.getLogger(__name__)

TYPE_MEDICINE, SELECT_TIMES, CONFIRM = range(3)

# Common medication times shown as toggleable buttons
_SLOT_GRID = [
    ["06:00", "07:00", "08:00", "09:00"],
    ["10:00", "11:00", "12:00", "13:00"],
    ["14:00", "15:00", "16:00", "17:00"],
    ["18:00", "19:00", "20:00", "21:00"],
    ["22:00"],
]


def _time_picker_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for row_slots in _SLOT_GRID:
        row = []
        for slot in row_slots:
            label = f"✅ {slot}" if slot in selected else slot
            row.append(InlineKeyboardButton(label, callback_data=f"med:toggle:{slot}"))
        rows.append(row)
    # Done / cancel row
    done_label = f"✔ Xong ({len(selected)} giờ)" if selected else "✔ Xong"
    rows.append([
        InlineKeyboardButton(done_label, callback_data="med:times:done"),
        InlineKeyboardButton("❌ Huỷ", callback_data="med:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


# ── Entry ──────────────────────────────────────────────────────────────────

async def start_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["reminder"] = {}
    msg = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()
    await msg.reply_text(
        "💊 *Đặt nhắc uống thuốc*\n\n"
        "Vui lòng nhập *tên thuốc* cần nhắc:",
        parse_mode="Markdown",
    )
    return TYPE_MEDICINE


# ── Step 1: medicine name ──────────────────────────────────────────────────

async def receive_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name or name.startswith("/"):
        await update.message.reply_text("Vui lòng nhập tên thuốc hợp lệ.")
        return TYPE_MEDICINE

    context.user_data["reminder"]["medicine_name"] = name
    context.user_data["reminder"]["selected_times"] = []

    await update.message.reply_text(
        f"💊 Thuốc: *{name}*\n\n"
        "⏰ *Chọn giờ uống thuốc* (có thể chọn nhiều giờ):",
        parse_mode="Markdown",
        reply_markup=_time_picker_keyboard([]),
    )
    return SELECT_TIMES


# ── Step 2: time picker (button grid) ─────────────────────────────────────

async def handle_time_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "med:cancel":
        context.user_data.pop("reminder", None)
        await query.edit_message_text("❌ Đã huỷ.")
        return ConversationHandler.END

    selected: list[str] = context.user_data["reminder"].setdefault("selected_times", [])

    if data.startswith("med:toggle:"):
        slot = data[len("med:toggle:"):]
        if slot in selected:
            selected.remove(slot)
        else:
            selected.append(slot)
        selected.sort()
        name = context.user_data["reminder"]["medicine_name"]
        selected_display = " / ".join(selected) if selected else "_chưa chọn_"
        await query.edit_message_text(
            f"💊 Thuốc: *{name}*\n"
            f"⏰ Đã chọn: {selected_display}\n\n"
            "Chọn thêm giờ hoặc nhấn *✔ Xong*:",
            parse_mode="Markdown",
            reply_markup=_time_picker_keyboard(selected),
        )
        return SELECT_TIMES

    if data == "med:times:done":
        if not selected:
            await query.answer("Vui lòng chọn ít nhất một giờ!", show_alert=True)
            return SELECT_TIMES

        context.user_data["reminder"]["reminder_times"] = ",".join(selected)
        name = context.user_data["reminder"]["medicine_name"]
        times_display = " — ".join(selected)

        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Xác nhận", callback_data="med:confirm"),
            InlineKeyboardButton("🔄 Chọn lại", callback_data="med:reselect"),
            InlineKeyboardButton("❌ Huỷ", callback_data="med:cancel"),
        ]])
        await query.edit_message_text(
            f"📋 *Xác nhận nhắc uống thuốc:*\n\n"
            f"💊 Thuốc: *{name}*\n"
            f"⏰ Giờ uống: *{times_display}*\n\n"
            f"Mỗi giờ tôi sẽ nhắc bạn *3 lần*:\n"
            f"• 5 phút trước giờ uống\n"
            f"• Đúng giờ uống\n"
            f"• 5 phút sau (nhắc cuối)",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        return CONFIRM

    return SELECT_TIMES


# ── Step 3: confirm ────────────────────────────────────────────────────────

async def confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "med:cancel":
        context.user_data.pop("reminder", None)
        await query.edit_message_text("❌ Đã huỷ. Nhắn *nhắc thuốc* bất kỳ lúc nào để bắt đầu lại.", parse_mode="Markdown")
        return ConversationHandler.END

    if query.data == "med:reselect":
        selected = context.user_data["reminder"].get("selected_times", [])
        name = context.user_data["reminder"]["medicine_name"]
        selected_display = " / ".join(selected) if selected else "_chưa chọn_"
        await query.edit_message_text(
            f"💊 Thuốc: *{name}*\n"
            f"⏰ Đã chọn: {selected_display}\n\n"
            "Chọn thêm giờ hoặc nhấn *✔ Xong*:",
            parse_mode="Markdown",
            reply_markup=_time_picker_keyboard(selected),
        )
        return SELECT_TIMES

    # med:confirm
    reminder = context.user_data.get("reminder", {})
    chat_id = update.effective_chat.id

    from db.database import AsyncSessionLocal
    from db.models import MedicineReminder

    async with AsyncSessionLocal() as db:
        rec = MedicineReminder(
            platform="telegram",
            telegram_chat_id=chat_id,
            medicine_name=reminder["medicine_name"],
            reminder_times=reminder["reminder_times"],
        )
        db.add(rec)
        await db.commit()

    times_display = " — ".join(reminder["reminder_times"].split(","))
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Xem danh sách nhắc", callback_data="med:list"),
    ]])
    await query.edit_message_text(
        f"✅ *Đã đặt nhắc uống thuốc!*\n\n"
        f"💊 *{reminder['medicine_name']}* lúc {times_display}\n\n"
        f"Tôi sẽ nhắc bạn 3 lần mỗi khung giờ 🔔",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    context.user_data.pop("reminder", None)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("reminder", None)
    await update.message.reply_text("❌ Đã huỷ.")
    return ConversationHandler.END


# ── List & cancel reminders ────────────────────────────────────────────────

async def show_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text

    chat_id = update.effective_chat.id

    from db.database import AsyncSessionLocal
    from db.models import MedicineReminder
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MedicineReminder).where(
                MedicineReminder.telegram_chat_id == chat_id,
                MedicineReminder.is_active == True,
            ).order_by(MedicineReminder.created_at)
        )
        reminders = result.scalars().all()

    if not reminders:
        await reply(
            "📋 Bạn chưa có nhắc uống thuốc nào.\nNhắn *nhắc thuốc* để thêm mới.",
            parse_mode="Markdown",
        )
        return

    rows = []
    lines = ["📋 *Danh sách nhắc uống thuốc:*\n"]
    for r in reminders:
        times_display = " / ".join(r.reminder_times.split(","))
        lines.append(f"💊 *{r.medicine_name}* — {times_display}")
        rows.append([InlineKeyboardButton(
            f"🗑 Xoá: {r.medicine_name}",
            callback_data=f"med:del:{str(r.id)}",
        )])

    rows.append([InlineKeyboardButton("➕ Thêm nhắc mới", callback_data="med:new")])
    await reply(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "med:list":
        await show_reminders(update, context)

    elif data == "med:new":
        await start_reminder(update, context)

    elif data.startswith("med:del:"):
        reminder_id = data[8:]
        from db.database import AsyncSessionLocal
        from db.models import MedicineReminder
        from sqlalchemy import select
        import uuid as _uuid

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MedicineReminder).where(
                    MedicineReminder.id == _uuid.UUID(reminder_id),
                    MedicineReminder.telegram_chat_id == update.effective_chat.id,
                )
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.is_active = False
                await db.commit()
                await query.edit_message_text(
                    f"🗑 Đã xoá nhắc uống *{rec.medicine_name}*.",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text("❌ Không tìm thấy nhắc này.")


# ── Build handler ──────────────────────────────────────────────────────────

def build_medicine_reminder_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("nhacthuoc", start_reminder),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND
                & filters.Regex(r"(?i)nhắc\s*thuốc|nhac\s*thuoc|uống\s*thuốc|uong\s*thuoc"),
                start_reminder,
            ),
            CallbackQueryHandler(start_reminder, pattern="^med:new$"),
        ],
        states={
            TYPE_MEDICINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_medicine)],
            SELECT_TIMES:  [CallbackQueryHandler(handle_time_toggle, pattern="^med:(toggle:|times:done|cancel)")],
            CONFIRM:       [CallbackQueryHandler(confirm_reminder, pattern="^med:(confirm|reselect|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_chat=True,
        per_user=False,
        per_message=False,
        allow_reentry=True,
    )
