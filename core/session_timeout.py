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
    from sqlalchemy import select

    config = get_settings()
    if config.SESSION_TIMEOUT_MINUTES <= 0:
        return

    cutoff = datetime.utcnow() - timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession).where(
                DBSession.doctor_id.isnot(None),
                DBSession.status != SessionStatus.closed,
                DBSession.last_activity_at < cutoff,
            )
        )
        stale = result.scalars().all()

        if not stale:
            return

        for session in stale:
            session.status = SessionStatus.closed
            logger.info(
                f"Auto-closed idle session {session.id} "
                f"(last activity: {session.last_activity_at})"
            )

        await db.commit()

    # Notify patients and doctors outside the DB transaction
    from bot.relay import send_to_session
    from api.websocket import ws_manager

    for session in stale:
        try:
            await send_to_session(
                session,
                f"⏱ Phiên tư vấn đã tự động kết thúc do không có hoạt động "
                f"trong {config.SESSION_TIMEOUT_MINUTES} phút.\n"
                "Nếu bạn cần hỗ trợ thêm, hãy nhắn tin để bắt đầu phiên mới."
            )
        except Exception as e:
            logger.warning(f"Failed to notify patient for session {session.id}: {e}")

        try:
            event = {
                "event": "session_timeout",
                "case_id": str(session.id),
                "message": f"Phiên đã tự động đóng sau {config.SESSION_TIMEOUT_MINUTES} phút không hoạt động.",
            }
            await ws_manager.broadcast_session_event(str(session.id), event)
            if session.doctor_id:
                await ws_manager.send_to_doctor(str(session.doctor_id), event)
        except Exception as e:
            logger.warning(f"Failed to notify doctor WS for session {session.id}: {e}")


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
