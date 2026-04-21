"""
Symptom chip picker for Telegram.
12 default chips shown; "Xem thêm" expands to all 30.
Severity scoring → triage CTA.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# (id, label, severity_weight, show_default)
SYMPTOMS = [
    # 12 default — most common
    ("S01", "🌡️ Sốt",          2, True),
    ("S02", "😮‍💨 Khó thở", 3, True),
    ("S03", "🤕 Đau đầu",       1, True),
    ("S04", "🤧 Ho",            1, True),
    ("S05", "😫 Mệt mỏi",       1, True),
    ("S06", "🤢 Buồn nôn",      1, True),
    ("S07", "💢 Đau ngực",      3, True),
    ("S08", "🦵 Đau khớp",      1, True),
    ("S09", "🧊 Ớn lạnh",       1, True),
    ("S10", "😵 Chóng mặt",     2, True),
    ("S11", "🤒 Đau họng",      1, True),
    ("S12", "🏃 Tiêu chảy",     2, True),
    # 18 extra
    ("S13", "💦 Đổ mồ hôi",     1, False),
    ("S14", "⚖️ Sụt cân",       2, False),
    ("S15", "😴 Ngủ lơ mơ",     2, False),
    ("S16", "🤯 Lú lẫn",        3, False),
    ("S17", "⚡ Tê bì tay chân", 2, False),
    ("S18", "🌬️ Thở khò khè",  2, False),
    ("S19", "💓 Tim đập nhanh",  2, False),
    ("S20", "📉 Huyết áp thấp",  2, False),
    ("S21", "🦵 Phù chân",       2, False),
    ("S22", "🩸 Chảy máu",       3, False),
    ("S23", "🔒 Táo bón",        1, False),
    ("S24", "😣 Đau bụng",       2, False),
    ("S25", "🫧 Đầy bụng",       1, False),
    ("S26", "💪 Đau cơ",         1, False),
    ("S27", "🚶 Yếu liệt",       3, False),
    ("S28", "🔴 Phát ban",       1, False),
    ("S29", "🚽 Tiểu buốt",      2, False),
    ("S30", "👁️ Mắt đỏ",        1, False),
]

_WEIGHT_MAP = {s[0]: s[2] for s in SYMPTOMS}
_LABEL_MAP  = {s[0]: s[1] for s in SYMPTOMS}


def _symptom_keyboard(selected: list[str], show_all: bool = False) -> InlineKeyboardMarkup:
    pool = SYMPTOMS if show_all else [s for s in SYMPTOMS if s[3]]
    rows = []
    row: list = []
    for sym_id, label, _, _ in pool:
        btn_label = f"✅ {label}" if sym_id in selected else label
        row.append(InlineKeyboardButton(btn_label, callback_data=f"sym:toggle:{sym_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if not show_all:
        rows.append([InlineKeyboardButton("➕ Xem thêm (18 triệu chứng)", callback_data="sym:expand")])
    else:
        rows.append([InlineKeyboardButton("➖ Thu gọn", callback_data="sym:collapse")])

    count = len(selected)
    label = f"🩺 Tư vấn ngay ({count} triệu chứng)" if count else "🩺 Tư vấn ngay"
    rows.append([
        InlineKeyboardButton(label, callback_data="sym:submit"),
        InlineKeyboardButton("❌ Huỷ", callback_data="sym:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


_PICKER_TEXT = (
    "🩺 *Chọn triệu chứng của bạn*\n\n"
    "Nhấn vào triệu chứng để chọn (có thể chọn nhiều). "
    "Sau đó nhấn *Tư vấn ngay*."
)


async def show_symptom_picker(reply_fn, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["symptoms"] = {"selected": [], "show_all": False}
    await reply_fn(_PICKER_TEXT, parse_mode="Markdown", reply_markup=_symptom_keyboard([]))


async def handle_symptom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    state = context.user_data.setdefault("symptoms", {"selected": [], "show_all": False})
    selected: list[str] = state.setdefault("selected", [])
    show_all: bool = state.get("show_all", False)

    if data == "sym:cancel":
        context.user_data.pop("symptoms", None)
        await query.edit_message_text("❌ Đã huỷ.")
        return

    if data.startswith("sym:toggle:"):
        sym_id = data[len("sym:toggle:"):]
        if sym_id in selected:
            selected.remove(sym_id)
        else:
            selected.append(sym_id)
        await query.edit_message_text(_PICKER_TEXT, parse_mode="Markdown",
                                      reply_markup=_symptom_keyboard(selected, show_all))
        return

    if data == "sym:expand":
        state["show_all"] = True
        await query.edit_message_text(_PICKER_TEXT, parse_mode="Markdown",
                                      reply_markup=_symptom_keyboard(selected, True))
        return

    if data == "sym:collapse":
        state["show_all"] = False
        await query.edit_message_text(_PICKER_TEXT, parse_mode="Markdown",
                                      reply_markup=_symptom_keyboard(selected, False))
        return

    if data == "sym:submit":
        if not selected:
            await query.answer("Vui lòng chọn ít nhất một triệu chứng!", show_alert=True)
            return

        total_weight = sum(_WEIGHT_MAP.get(s, 1) for s in selected)
        labels = [_LABEL_MAP.get(s, s) for s in selected]
        symptoms_text = ", ".join(labels)
        context.user_data.pop("symptoms", None)

        triage = "high" if total_weight >= 6 else ("medium" if total_weight >= 3 else "low")

        await query.edit_message_text(f"🔍 Đang phân tích {len(selected)} triệu chứng...")

        chat_id = update.effective_chat.id
        user_id = f"tg_{chat_id}"
        message_text = f"Tôi đang có các triệu chứng: {symptoms_text}"

        from api.routes.chat import chat_endpoint, ChatRequest
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            req = ChatRequest(platform="telegram", telegram_chat_id=chat_id,
                              user_id=user_id, message=message_text)
            result = await chat_endpoint(req, db)

        if result.get("type") == "ai_reply":
            content = result["content"]
            if triage == "high":
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🆘 SOS", callback_data="menu:sos"),
                    InlineKeyboardButton("👨‍⚕️ Gặp bác sĩ ngay", callback_data="cta:doctor"),
                ]])
                await query.message.reply_text(
                    f"🔴 *Triệu chứng nghiêm trọng — cần khám ngay!*\n\n{content}",
                    parse_mode="Markdown", reply_markup=markup,
                )
            elif triage == "medium":
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Đặt lịch khám", callback_data="bk:start"),
                    InlineKeyboardButton("👨‍⚕️ Gặp bác sĩ", callback_data="cta:doctor"),
                ]])
                await query.message.reply_text(content, parse_mode="Markdown", reply_markup=markup)
            else:
                await query.message.reply_text(content, parse_mode="Markdown")

        elif result.get("type") == "request_doctor":
            from bot.handlers.callback import show_out_of_scope_cta
            await show_out_of_scope_cta(query.message.reply_text, result)
