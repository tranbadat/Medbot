"""
Background task: auto-close doctor sessions that have been idle too long.
Runs every minute, closes sessions where last_activity_at < now - SESSION_TIMEOUT_MINUTES.
Only applies to sessions with a doctor assigned (pending or active).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from core.config import get_settings

logger = logging.getLogger(__name__)


async def _close_stale_sessions() -> None:
    from db.database import AsyncSessionLocal
    from db.models import Session as DBSession, SessionStatus
    from sqlalchemy import select, or_

    config = get_settings()
    if config.SESSION_TIMEOUT_MINUTES <= 0:
        return

    cutoff = datetime.utcnow() - timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)

    # Collect data needed for notification BEFORE closing db session
    notify_list = []  # list of dicts with primitive values only

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession).where(
                DBSession.doctor_id.isnot(None),
                DBSession.status != SessionStatus.closed,
                or_(
                    DBSession.last_activity_at < cutoff,
                    DBSession.last_activity_at.is_(None),  # fallback for old rows
                ),
            )
        )
        stale = result.scalars().all()

        if not stale:
            return

        for session in stale:
            notify_list.append({
                "id": str(session.id),
                "platform": session.platform or "telegram",
                "telegram_chat_id": session.telegram_chat_id,
                "zalo_user_id": session.zalo_user_id,
                "doctor_id": str(session.doctor_id) if session.doctor_id else None,
            })
            session.status = SessionStatus.closed
            logger.info(f"Auto-closed idle session {session.id} (last_activity: {session.last_activity_at})")

        await db.commit()

    # Notify outside DB session using pre-collected plain data
    from bot.relay import send_message
    from api.websocket import ws_manager

    msg = (
        f"⏱ Phiên tư vấn đã tự động kết thúc do không có hoạt động "
        f"trong {config.SESSION_TIMEOUT_MINUTES} phút.\n"
        "Nếu bạn cần hỗ trợ thêm, hãy nhắn tin để bắt đầu phiên mới."
    )

    for info in notify_list:
        try:
            uid = info["zalo_user_id"] if info["platform"] == "zalo" else info["telegram_chat_id"]
            await send_message(info["platform"], uid, msg)
        except Exception as e:
            logger.warning(f"Failed to notify patient for session {info['id']}: {e}")

        try:
            event = {
                "event": "session_timeout",
                "case_id": info["id"],
                "message": f"Phiên đã tự động đóng sau {config.SESSION_TIMEOUT_MINUTES} phút không hoạt động.",
            }
            await ws_manager.broadcast_session_event(info["id"], event)
            if info["doctor_id"]:
                await ws_manager.send_to_doctor(info["doctor_id"], event)
        except Exception as e:
            logger.warning(f"Failed to notify doctor WS for session {info['id']}: {e}")


async def run_session_timeout_loop() -> None:
    """Run forever, checking for idle sessions every 60 seconds."""
    config = get_settings()
    if config.SESSION_TIMEOUT_MINUTES <= 0:
        logger.info("Session timeout disabled (SESSION_TIMEOUT_MINUTES=0)")
        return

    logger.info(
        f"Session timeout task started — idle limit: {config.SESSION_TIMEOUT_MINUTES} min"
    )
    while True:
        try:
            await _close_stale_sessions()
        except Exception as e:
            logger.error(f"Session timeout task error: {e}")
        await asyncio.sleep(60)
