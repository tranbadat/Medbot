import os
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

MIME_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram voice messages and audio files via Whisper transcription."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    tg_voice = update.message.voice or update.message.audio

    if not tg_voice:
        return

    await update.message.chat.send_action("typing")

    if tg_voice.file_size and tg_voice.file_size > 25 * 1024 * 1024:
        await update.message.reply_text("File âm thanh vượt quá 25MB.")
        return

    try:
        file_obj = await tg_voice.get_file()
        audio_bytes = await file_obj.download_as_bytearray()
    except Exception as e:
        logger.error(f"Failed to download voice: {e}")
        await update.message.reply_text("Không tải được file âm thanh. Vui lòng thử lại.")
        return

    from core.audio_transcriber import transcribe
    filename = f"voice_{chat_id}.ogg"
    if hasattr(tg_voice, "file_name") and tg_voice.file_name:
        filename = tg_voice.file_name

    await update.message.reply_text("🎙 Đang xử lý bản ghi âm...")
    text = await transcribe(bytes(audio_bytes), filename)

    if not text:
        await update.message.reply_text(
            "❌ Không thể chuyển đổi giọng nói thành văn bản. "
            "Vui lòng nhắn tin hoặc thử lại."
        )
        return

    # Echo transcription so user can see what was understood
    await update.message.reply_text(f"📝 *Đã nhận:* _{text}_", parse_mode="Markdown")

    # Booking intent via voice → guide with text (can't use interactive buttons)
    import re as _re
    if _re.search(r"(?i)đặt\s*lịch|đặt\s*hẹn|book.*appoint|đăng\s*ký\s*khám", text):
        await update.message.reply_text(
            "📅 *Đặt lịch khám*\n\n"
            "Để đặt lịch, vui lòng nhắn *tin nhắn văn bản* theo một trong các cách:\n\n"
            "1️⃣ Nhắn: *đặt lịch* — trợ lý sẽ hướng dẫn từng bước\n"
            "2️⃣ Dùng menu: /start → chọn 📅 Lịch khám\n\n"
            "_Lưu ý: ghi âm không hỗ trợ quy trình đặt lịch vì cần chọn ngày/giờ bằng nút bấm._",
            parse_mode="Markdown",
        )
        return

    # Route through normal chat flow
    from api.routes.chat import chat_endpoint, ChatRequest
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        req = ChatRequest(
            platform="telegram",
            telegram_chat_id=chat_id,
            user_id=f"tg_{chat_id}",
            message=text,
        )
        result = await chat_endpoint(req, db)

    if result.get("type") == "ai_reply":
        await update.message.reply_text(result["content"])
    elif result.get("type") == "request_doctor":
        doctors = result.get("doctors", [])
        if doctors:
            urgency_code = {"low": "l", "medium": "m", "high": "h"}.get(result.get("urgency", "medium"), "m")
            from bot.handlers.callback import send_doctor_carousel
            await send_doctor_carousel(
                lambda t, **kw: update.message.reply_text(t, **kw),
                doctors, index=0, urgency=urgency_code,
                header=f"⚠️ {result.get('reason', 'Cần bác sĩ tư vấn')}\n\n",
            )
        else:
            await update.message.reply_text(
                "⚠️ Câu hỏi này cần bác sĩ tư vấn, nhưng hiện không có bác sĩ trực tuyến."
            )
    # forwarded_to_doctor: silent


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = f"tg_{chat_id}"
    caption = update.message.caption or ""

    await update.message.chat.send_action("typing")

    # Determine file object
    if update.message.document:
        tg_file = update.message.document
        mime = tg_file.mime_type or "application/octet-stream"
    elif update.message.photo:
        tg_file = update.message.photo[-1]
        mime = "image/jpeg"
    else:
        await update.message.reply_text("Không nhận diện được file. Vui lòng gửi PDF, DOCX hoặc ảnh.")
        return

    if tg_file.file_size and tg_file.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("File vượt quá 20MB. Vui lòng nén hoặc chụp ảnh từng trang.")
        return

    ext = MIME_EXT.get(mime, ".bin")
    tmp_path = None
    try:
        file_obj = await tg_file.get_file()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name

        await file_obj.download_to_drive(tmp_path)

        from core.file_processor import process_file, cleanup_temp_file
        file_result = process_file(tmp_path, mime)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        logger.error(f"File processing error: {e}")
        await update.message.reply_text("Có lỗi khi xử lý file. Vui lòng thử lại.")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    from core.ai_client import chat as ai_chat
    from core.rag import retrieve_context
    from core.scope_checker import parse_claude_response
    from core.file_processor import build_content
    from core.config import get_settings
    from db.redis_client import get_online_doctors

    engine = get_settings().AI_ENGINE
    user_message = caption or "Tôi đã gửi một file."
    file_content = build_content(file_result, user_message, engine)
    messages = [{"role": "user", "content": file_content}]
    rag_context = await retrieve_context(user_message)
    reply_text = await ai_chat(messages, rag_context=rag_context)

    scope_data = parse_claude_response(reply_text)

    from db.database import AsyncSessionLocal
    from api.routes.chat import _get_or_create_session, _save_message, ChatRequest
    from db.models import MessageRole, SessionStatus
    from datetime import datetime

    file_type = file_result.get("file_type")
    file_extracted = file_result.get("content") if file_result["type"] == "text" else tg_file.file_id

    async with AsyncSessionLocal() as db:
        req = ChatRequest(platform="telegram", telegram_chat_id=chat_id, user_id=user_id, message=user_message)
        session = await _get_or_create_session(db, req)

        # Doctor session active — forward file, skip AI
        if session.doctor_id and session.status != SessionStatus.closed:
            await _save_message(db, session, MessageRole.user, user_message, file_type=file_type, file_extracted=file_extracted)
            session.last_activity_at = datetime.utcnow()
            await db.commit()
            from api.websocket import ws_manager
            await ws_manager.relay_user_message(str(session.id), f"[File: {user_message}]", str(session.doctor_id))
            return

        await _save_message(db, session, MessageRole.user, user_message, file_type=file_type, file_extracted=file_extracted)

        if scope_data:
            await db.commit()
            doctors = await get_online_doctors(scope_data.get("specialty"))
            if doctors:
                urgency_code = {"low": "l", "medium": "m", "high": "h"}.get(scope_data.get("urgency", "medium"), "m")
                buttons = [
                    [InlineKeyboardButton(
                        f"👨‍⚕️ {d['name']} ({d['specialty']})",
                        callback_data=f"sd:{d['id'].replace('-', '')}:{urgency_code}",
                    )]
                    for d in doctors
                ]
                markup = InlineKeyboardMarkup(buttons)
                await update.message.reply_text(
                    f"⚠️ {scope_data.get('reason', 'File này cần bác sĩ xem xét')}\n\nChọn bác sĩ:",
                    reply_markup=markup,
                )
            else:
                await update.message.reply_text(
                    "⚠️ File này cần bác sĩ xem xét, nhưng hiện không có bác sĩ trực tuyến."
                )
        else:
            await _save_message(db, session, MessageRole.bot, reply_text)
            await db.commit()
            await update.message.reply_text(reply_text)
