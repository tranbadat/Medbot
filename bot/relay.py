import logging

logger = logging.getLogger(__name__)

_bot_app = None


def set_bot_app(app) -> None:
    global _bot_app
    _bot_app = app


async def send_message(platform: str, user_id: str | int, text: str, parse_mode: str | None = "Markdown") -> None:
    if platform == "zalo":
        from core.zalo_client import send_text
        await send_text(str(user_id), text)
    else:
        if _bot_app is None:
            logger.error("Telegram bot not initialized")
            return
        try:
            kw = {"parse_mode": parse_mode} if parse_mode else {}
            await _bot_app.bot.send_message(chat_id=int(user_id), text=text, **kw)
        except Exception as e:
            logger.error(f"Telegram send_message to {user_id} failed: {e}")


async def send_to_session(session, text: str) -> None:
    """Platform-aware relay using a Session ORM object."""
    if session.platform == "zalo":
        await send_message("zalo", session.zalo_user_id, text)
    else:
        await send_message("telegram", session.telegram_chat_id, text)


async def send_to_appointment(appt, text: str) -> None:
    """Platform-aware relay using an Appointment ORM object."""
    platform = getattr(appt, "platform", "telegram") or "telegram"
    if platform == "zalo":
        await send_message("zalo", appt.zalo_user_id, text)
    else:
        await send_message("telegram", appt.telegram_chat_id, text)
