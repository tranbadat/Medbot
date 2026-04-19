"""
Background task: send Telegram reminder 1 hour before appointment.
Runs every minute, finds appointments in the [55min, 65min] window ahead.
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_REMIND_BEFORE_MINUTES = 60
_CHECK_WINDOW_MINUTES = 5   # run every 5 min, look ±5 min around the 60-min mark


async def _send_reminders() -> None:
    from db.database import AsyncSessionLocal
    from db.models import Appointment, AppointmentStatus
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    now = datetime.utcnow()
    window_start = now + timedelta(minutes=_REMIND_BEFORE_MINUTES - _CHECK_WINDOW_MINUTES)
    window_end   = now + timedelta(minutes=_REMIND_BEFORE_MINUTES + _CHECK_WINDOW_MINUTES)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.doctor))
            .where(
                Appointment.status != AppointmentStatus.cancelled,
                Appointment.reminder_sent == False,
                Appointment.appointment_date >= window_start,
                Appointment.appointment_date <= window_end,
            )
        )
        appointments = result.scalars().all()

        if not appointments:
            return

        for appt in appointments:
            appt.reminder_sent = True

        await db.commit()

    from bot.relay import send_to_appointment

    for appt in appointments:
        dt_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
        doctor_str = f"👨‍⚕️ Bác sĩ: {appt.doctor.name}\n" if appt.doctor else ""
        try:
            await send_to_appointment(
                appt,
                f"⏰ *Nhắc lịch khám*\n\n"
                f"Bạn có lịch khám sau *1 tiếng* nữa.\n\n"
                f"📅 Thời gian: *{dt_str}*\n"
                f"{doctor_str}"
                f"\nVui lòng chuẩn bị đến đúng giờ. Nếu cần huỷ hoặc đổi lịch, "
                f"hãy liên hệ phòng khám sớm nhất có thể.",
            )
            logger.info(f"Reminder sent for appointment {appt.id} at {dt_str}")
        except Exception as e:
            logger.warning(f"Failed to send reminder for appointment {appt.id}: {e}")


async def run_appointment_reminder_loop() -> None:
    """Run forever, checking for upcoming appointments every 5 minutes."""
    logger.info("Appointment reminder task started")
    while True:
        try:
            await _send_reminders()
        except Exception as e:
            logger.error(f"Appointment reminder task error: {e}")
        await asyncio.sleep(_CHECK_WINDOW_MINUTES * 60)
