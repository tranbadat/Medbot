"""
Profile collection ConversationHandler.
Collects: display_name, age, weight_kg, height_cm, phone (all skippable).
Entry: CallbackQueryHandler("profile:start")
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, CommandHandler, filters,
)

logger = logging.getLogger(__name__)

ASK_NAME, ASK_AGE, ASK_WEIGHT, ASK_HEIGHT, ASK_PHONE = range(5)

_SKIP_BTN = InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Bỏ qua", callback_data="prof:skip")]])


async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["prof"] = {}
    tg_name = (update.effective_user.first_name or "bạn") if update.effective_user else "bạn"

    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👤 Dùng '{tg_name}'", callback_data="prof:use_tg_name"),
        InlineKeyboardButton("⏭ Bỏ qua", callback_data="prof:skip"),
    ]])
    await reply(
        "📋 *Hồ sơ sức khoẻ*\n\n"
        "Thông tin này giúp tôi tư vấn chính xác hơn. "
        "Bạn có thể bỏ qua bất kỳ bước nào.\n\n"
        "👤 *Tên hiển thị của bạn?*",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    return ASK_NAME


# ── Name ──────────────────────────────────────────────────────────────────────

async def _ask_age(reply_fn) -> int:
    await reply_fn(
        "🎂 *Tuổi của bạn?* (nhập số hoặc bỏ qua)",
        parse_mode="Markdown",
        reply_markup=_SKIP_BTN,
    )
    return ASK_AGE


async def handle_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "prof:use_tg_name":
        context.user_data["prof"]["display_name"] = update.effective_user.first_name
    return await _ask_age(query.message.reply_text)


async def handle_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if name and not name.startswith("/"):
        context.user_data["prof"]["display_name"] = name
    return await _ask_age(update.message.reply_text)


# ── Age ───────────────────────────────────────────────────────────────────────

async def _ask_weight(reply_fn) -> int:
    await reply_fn(
        "⚖️ *Cân nặng của bạn (kg)?* (nhập số hoặc bỏ qua)",
        parse_mode="Markdown",
        reply_markup=_SKIP_BTN,
    )
    return ASK_WEIGHT


async def handle_age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _ask_weight(query.message.reply_text)


async def handle_age_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text.strip())
        if 1 <= age <= 120:
            context.user_data["prof"]["age"] = age
        else:
            await update.message.reply_text("Tuổi không hợp lệ. Vui lòng nhập lại:", reply_markup=_SKIP_BTN)
            return ASK_AGE
    except ValueError:
        await update.message.reply_text("Vui lòng nhập số tuổi (ví dụ: 35):", reply_markup=_SKIP_BTN)
        return ASK_AGE
    return await _ask_weight(update.message.reply_text)


# ── Weight ────────────────────────────────────────────────────────────────────

async def _ask_height(reply_fn) -> int:
    await reply_fn(
        "📏 *Chiều cao của bạn (cm)?* (nhập số hoặc bỏ qua)",
        parse_mode="Markdown",
        reply_markup=_SKIP_BTN,
    )
    return ASK_HEIGHT


async def handle_weight_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _ask_height(query.message.reply_text)


async def handle_weight_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        weight = int(update.message.text.strip())
        if 1 <= weight <= 300:
            context.user_data["prof"]["weight_kg"] = weight
        else:
            await update.message.reply_text("Cân nặng không hợp lệ. Vui lòng nhập lại:", reply_markup=_SKIP_BTN)
            return ASK_WEIGHT
    except ValueError:
        await update.message.reply_text("Vui lòng nhập số kg (ví dụ: 60):", reply_markup=_SKIP_BTN)
        return ASK_WEIGHT
    return await _ask_height(update.message.reply_text)


# ── Height ────────────────────────────────────────────────────────────────────

async def _ask_phone(reply_fn) -> int:
    await reply_fn(
        "📞 *Số điện thoại* (để phòng khám liên lạc, tuỳ chọn):",
        parse_mode="Markdown",
        reply_markup=_SKIP_BTN,
    )
    return ASK_PHONE


async def handle_height_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _ask_phone(query.message.reply_text)


async def handle_height_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        height = int(update.message.text.strip())
        if 50 <= height <= 250:
            context.user_data["prof"]["height_cm"] = height
        else:
            await update.message.reply_text("Chiều cao không hợp lệ. Vui lòng nhập lại:", reply_markup=_SKIP_BTN)
            return ASK_HEIGHT
    except ValueError:
        await update.message.reply_text("Vui lòng nhập số cm (ví dụ: 165):", reply_markup=_SKIP_BTN)
        return ASK_HEIGHT
    return await _ask_phone(update.message.reply_text)


# ── Phone → Save ──────────────────────────────────────────────────────────────

async def handle_phone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _save_profile(query.message.reply_text, update, context)


async def handle_phone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    if phone and not phone.startswith("/"):
        context.user_data["prof"]["phone"] = phone
    return await _save_profile(update.message.reply_text, update, context)


async def _save_profile(reply_fn, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    prof = context.user_data.pop("prof", {})

    from db.database import AsyncSessionLocal
    from db.models import Patient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Patient).where(Patient.telegram_chat_id == chat_id))
        patient = result.scalar_one_or_none()
        if patient:
            if prof.get("display_name"):
                patient.display_name = prof["display_name"]
            if prof.get("age"):
                patient.age = prof["age"]
            if prof.get("weight_kg"):
                patient.weight_kg = prof["weight_kg"]
            if prof.get("height_cm"):
                patient.height_cm = prof["height_cm"]
            if prof.get("phone"):
                patient.phone = prof["phone"]
            patient.profile_complete = True
            await db.commit()

    tg_name = (update.effective_user.first_name or "") if update.effective_user else ""
    name = prof.get("display_name") or tg_name or "bạn"
    lines = [f"✅ *Hồ sơ đã lưu!*\n", f"👤 Tên: {name}"]
    if prof.get("age"):
        lines.append(f"🎂 Tuổi: {prof['age']}")
    if prof.get("weight_kg"):
        lines.append(f"⚖️ Cân nặng: {prof['weight_kg']} kg")
    if prof.get("height_cm"):
        lines.append(f"📏 Chiều cao: {prof['height_cm']} cm")
    if prof.get("phone"):
        lines.append(f"📞 SĐT: {prof['phone']}")

    from bot.handlers.start import _main_menu
    await reply_fn(
        "\n".join(lines) + "\n\nBạn có thể bắt đầu tư vấn sức khoẻ!",
        parse_mode="Markdown",
        reply_markup=_main_menu(),
    )
    return ConversationHandler.END


async def _skip_all_and_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Mark profile complete without data (user cancelled whole flow)."""
    context.user_data.pop("prof", None)
    chat_id = update.effective_chat.id

    from db.database import AsyncSessionLocal
    from db.models import Patient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Patient).where(Patient.telegram_chat_id == chat_id))
        patient = result.scalar_one_or_none()
        if patient:
            patient.profile_complete = True
            await db.commit()

    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text

    from bot.handlers.start import _main_menu
    await reply("Đã bỏ qua. Bạn có thể cập nhật hồ sơ sau bằng lệnh /hoso.", reply_markup=_main_menu())
    return ConversationHandler.END


def build_profile_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(profile_start, pattern="^profile:start$"),
            CommandHandler("hoso", profile_start),
        ],
        states={
            ASK_NAME: [
                CallbackQueryHandler(handle_name_callback, pattern="^prof:(use_tg_name|skip)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_text),
            ],
            ASK_AGE: [
                CallbackQueryHandler(handle_age_callback, pattern="^prof:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_age_text),
            ],
            ASK_WEIGHT: [
                CallbackQueryHandler(handle_weight_callback, pattern="^prof:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_text),
            ],
            ASK_HEIGHT: [
                CallbackQueryHandler(handle_height_callback, pattern="^prof:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_height_text),
            ],
            ASK_PHONE: [
                CallbackQueryHandler(handle_phone_callback, pattern="^prof:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _skip_all_and_end),
            CallbackQueryHandler(_skip_all_and_end, pattern="^prof:cancel$"),
        ],
        per_chat=True,
        per_user=False,
        per_message=False,
        allow_reentry=True,
    )
