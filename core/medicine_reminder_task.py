"""
Background task: send medicine reminder notifications.
For each active reminder and each scheduled time, sends 3 notifications:
  - T-5 min : "5 phút nữa đến giờ uống thuốc"
  - T+0     : "Đến giờ uống thuốc rồi!"
  - T+5 min : "Nhắc lần cuối"
Uses Redis to deduplicate (one send per phase per reminder per day).
Runs every 60 seconds.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
logger = logging.getLogger(__name__)

_PHASES = [
    ("pre5",  -5, "⏰ *5 phút nữa* đến giờ uống thuốc!\n\n💊 Chuẩn bị uống: *{name}* lúc {slot}"),
    ("on",     0, "⏰ *Đến giờ uống thuốc rồi!*\n\n💊 Uống ngay: *{name}*"),
    ("post5", +5, "⏰ Nhắc lần cuối — đã uống *{name}* chưa? 💊"),
]


async def _check_and_notify() -> None:
    from db.database import AsyncSessionLocal
    from db.models import MedicineReminder
    from sqlalchemy import select
    from db.redis_client import get_redis
    from bot.relay import send_message

    now = datetime.now(VN_TZ)
    today_str = now.strftime("%Y-%m-%d")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MedicineReminder).where(MedicineReminder.is_active == True)
        )
        reminders = result.scalars().all()

    r = await get_redis()

    for reminder in reminders:
        for slot_str in reminder.reminder_times.split(","):
            slot_str = slot_str.strip()
            if not slot_str:
                continue
            try:
                h, m = map(int, slot_str.split(":"))
            except ValueError:
                continue

            slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

            for phase_key, delta_min, msg_tpl in _PHASES:
                fire_dt = slot_dt + timedelta(minutes=delta_min)
                diff = abs((now - fire_dt).total_seconds())
                if diff > 30:  # only fire within ±30 s of target
                    continue

                redis_key = f"med_remind:{reminder.id}:{today_str}:{slot_str}:{phase_key}"
                already = await r.get(redis_key)
                if already:
                    continue

                msg = msg_tpl.format(name=reminder.medicine_name, slot=slot_str)
                try:
                    uid = reminder.zalo_user_id if reminder.platform == "zalo" else reminder.telegram_chat_id
                    await send_message(reminder.platform, uid, msg, parse_mode="Markdown")
                    await r.setex(redis_key, 86400, "1")  # 24 h TTL
                    logger.info(
                        f"Medicine reminder sent: {reminder.medicine_name} "
                        f"chat={uid} phase={phase_key} slot={slot_str}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send medicine reminder {reminder.id}: {e}")


async def run_medicine_reminder_loop() -> None:
    """Run forever, checking every 60 seconds."""
    logger.info("Medicine reminder task started")
    while True:
        try:
            await _check_and_notify()
        except Exception as e:
            logger.error(f"Medicine reminder task error: {e}")
        await asyncio.sleep(60)
