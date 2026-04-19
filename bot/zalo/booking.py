"""
Zalo OA booking flow — text/button based (mirrors Telegram ConversationHandler).
State is stored in Redis key: zalo_booking:{user_id}  (TTL 30 min)
"""
import json
import logging
import calendar
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

_STATE_TTL = 1800  # 30 min
_TIME_SLOTS = [
    f"{h:02d}:{m:02d}"
    for h in range(8, 17)
    for m in (0, 30)
    if not (h == 16 and m == 30)
]


async def _get_state(user_id: str) -> dict:
    from db.redis_client import get_redis
    r = await get_redis()
    raw = await r.get(f"zalo_booking:{user_id}")
    return json.loads(raw) if raw else {}


async def _set_state(user_id: str, state: dict) -> None:
    from db.redis_client import get_redis
    r = await get_redis()
    await r.setex(f"zalo_booking:{user_id}", _STATE_TTL, json.dumps(state))


async def _clear_state(user_id: str) -> None:
    from db.redis_client import get_redis
    r = await get_redis()
    await r.delete(f"zalo_booking:{user_id}")


# ── Entry point ────────────────────────────────────────────────────────────

async def start_booking(user_id: str, suggested_name: str = "") -> None:
    from core.zalo_client import send_buttons
    if suggested_name:
        await _set_state(user_id, {"step": "confirm_name", "name": suggested_name})
        await send_buttons(
            user_id,
            f"Đặt lịch khám\n\nXác nhận tên: *{suggested_name}*",
            [
                {"title": "✅ Dùng tên này", "payload": "bk:name:confirm"},
                {"title": "✏️ Nhập tên khác",  "payload": "bk:name:change"},
            ],
        )
    else:
        await _set_state(user_id, {"step": "type_name"})
        from core.zalo_client import send_text
        await send_text(user_id, "📋 Vui lòng nhập họ và tên của bạn:")


# ── Main dispatcher ────────────────────────────────────────────────────────

async def handle_booking_input(user_id: str, text: str) -> bool:
    """Return True if message was consumed by booking flow, False otherwise."""
    state = await _get_state(user_id)
    if not state:
        return False

    step = state.get("step")

    if step == "confirm_name":
        return await _step_confirm_name(user_id, text, state)
    elif step == "type_name":
        return await _step_type_name(user_id, text, state)
    elif step == "select_date":
        return await _step_select_date(user_id, text, state)
    elif step == "select_time":
        return await _step_select_time(user_id, text, state)
    elif step == "select_doctor":
        return await _step_select_doctor(user_id, text, state)
    elif step == "confirm":
        return await _step_confirm(user_id, text, state)
    return False


# ── Steps ──────────────────────────────────────────────────────────────────

async def _step_confirm_name(user_id: str, text: str, state: dict) -> bool:
    from core.zalo_client import send_text
    if text == "bk:name:confirm":
        state["step"] = "select_date"
        await _set_state(user_id, state)
        await _send_date_picker(user_id)
        return True
    if text == "bk:name:change":
        state["step"] = "type_name"
        await _set_state(user_id, state)
        await send_text(user_id, "✏️ Vui lòng nhập họ và tên của bạn:")
        return True
    return False


async def _step_type_name(user_id: str, text: str, state: dict) -> bool:
    if not text.strip() or text.startswith("bk:"):
        return False
    state["name"] = text.strip()
    state["step"] = "select_date"
    await _set_state(user_id, state)
    await _send_date_picker(user_id)
    return True


async def _step_select_date(user_id: str, text: str, state: dict) -> bool:
    from core.zalo_client import send_text
    if text.startswith("bk:cal:nav:"):
        # bk:cal:nav:YYYY:MM
        parts = text.split(":")
        year, month = int(parts[3]), int(parts[4])
        await _send_date_picker(user_id, year, month)
        return True
    if text.startswith("bk:date:"):
        date_str = text[8:]  # YYYY-MM-DD
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return True
        state["date"] = date_str
        state["step"] = "select_time"
        await _set_state(user_id, state)
        await _send_time_picker(user_id, date_str)
        return True
    return False


async def _step_select_time(user_id: str, text: str, state: dict) -> bool:
    if text.startswith("bk:time:"):
        time_str = text[8:]
        state["time"] = time_str
        state["step"] = "select_doctor"
        await _set_state(user_id, state)
        await _send_doctor_picker(user_id)
        return True
    return False


async def _step_select_doctor(user_id: str, text: str, state: dict) -> bool:
    from core.zalo_client import send_text
    if text == "bk:doctor:any":
        state["doctor_id"] = None
        state["doctor_name"] = "Bất kỳ bác sĩ"
    elif text.startswith("bk:doctor:"):
        doctor_id = text[10:]
        state["doctor_id"] = doctor_id
        # Fetch name
        from db.database import AsyncSessionLocal
        from db.models import Doctor
        from sqlalchemy import select
        import uuid
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(doctor_id)))
            doc = r.scalar_one_or_none()
            state["doctor_name"] = doc.name if doc else "Bác sĩ phòng khám"
    else:
        return False

    state["step"] = "confirm"
    await _set_state(user_id, state)
    await _send_confirmation(user_id, state)
    return True


async def _step_confirm(user_id: str, text: str, state: dict) -> bool:
    from core.zalo_client import send_text
    if text == "bk:confirm:yes":
        await _save_appointment(user_id, state)
        await _clear_state(user_id)
        return True
    if text == "bk:confirm:no":
        await _clear_state(user_id)
        await send_text(user_id, "❌ Đã huỷ đặt lịch. Nhắn tin bất kỳ lúc nào để bắt đầu lại.")
        return True
    return False


# ── UI builders ────────────────────────────────────────────────────────────

async def _send_date_picker(user_id: str, year: int | None = None, month: int | None = None) -> None:
    from core.zalo_client import send_text, send_buttons
    today = date.today()
    year = year or today.year
    month = month or today.month

    prev = date(year, month, 1) - timedelta(days=1)
    nxt = (date(year, month, 28) + timedelta(days=4)).replace(day=1)

    cal = calendar.monthcalendar(year, month)
    available_days = []
    for week in cal:
        for d in week:
            if d == 0:
                continue
            day_date = date(year, month, d)
            if day_date >= today:
                available_days.append(day_date)

    # Send in pages of 3 buttons
    await send_text(user_id, f"📅 Chọn ngày khám — Tháng {month}/{year}:")

    # Navigation
    from core.zalo_client import send_buttons
    await send_buttons(
        user_id,
        "Chuyển tháng:",
        [
            {"title": f"◀ {prev.month}/{prev.year}", "payload": f"bk:cal:nav:{prev.year}:{prev.month}"},
            {"title": f"▶ {nxt.month}/{nxt.year}", "payload": f"bk:cal:nav:{nxt.year}:{nxt.month}"},
        ],
    )

    # Days — max 3 per button message, send multiple messages
    for i in range(0, min(len(available_days), 9), 3):
        chunk = available_days[i:i+3]
        btns = [{"title": d.strftime("%d/%m (%a)").replace("Mon","T2").replace("Tue","T3")
                  .replace("Wed","T4").replace("Thu","T5").replace("Fri","T6")
                  .replace("Sat","T7").replace("Sun","CN"),
                  "payload": f"bk:date:{d.isoformat()}"} for d in chunk]
        await send_buttons(user_id, " ", btns)


async def _send_time_picker(user_id: str, date_str: str) -> None:
    from core.zalo_client import send_text, send_buttons
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    await send_text(user_id, f"🕐 Chọn giờ khám — {d.strftime('%d/%m/%Y')}:")
    for i in range(0, len(_TIME_SLOTS), 3):
        chunk = _TIME_SLOTS[i:i+3]
        btns = [{"title": t, "payload": f"bk:time:{t}"} for t in chunk]
        await send_buttons(user_id, " ", btns)


async def _send_doctor_picker(user_id: str) -> None:
    from core.zalo_client import send_text, send_buttons
    from db.database import AsyncSessionLocal
    from db.models import Doctor
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Doctor).where(Doctor.is_active == True).limit(9))
        doctors = result.scalars().all()

    await send_text(user_id, "👨‍⚕️ Chọn bác sĩ:")
    # "Any doctor" option first
    await send_buttons(user_id, "Bất kỳ bác sĩ nào", [{"title": "✅ Bất kỳ bác sĩ", "payload": "bk:doctor:any"}])
    # Doctor list
    for i in range(0, len(doctors), 3):
        chunk = doctors[i:i+3]
        btns = [{"title": f"{d.name} ({d.specialty})", "payload": f"bk:doctor:{str(d.id).replace('-','')}"} for d in chunk]
        await send_buttons(user_id, " ", btns)


async def _send_confirmation(user_id: str, state: dict) -> None:
    from core.zalo_client import send_buttons
    d = datetime.strptime(state["date"], "%Y-%m-%d").date()
    text = (
        f"📋 Xác nhận đặt lịch\n\n"
        f"👤 Tên: {state.get('name', '')}\n"
        f"📅 Ngày: {d.strftime('%d/%m/%Y')}\n"
        f"🕐 Giờ: {state.get('time', '')}\n"
        f"👨‍⚕️ Bác sĩ: {state.get('doctor_name', 'Bất kỳ')}"
    )
    await send_buttons(
        user_id, text,
        [
            {"title": "✅ Xác nhận đặt lịch", "payload": "bk:confirm:yes"},
            {"title": "❌ Huỷ",               "payload": "bk:confirm:no"},
        ],
    )


async def _save_appointment(user_id: str, state: dict) -> None:
    from core.zalo_client import send_text
    from db.database import AsyncSessionLocal
    from db.models import Appointment
    import uuid as _uuid

    dt_str = f"{state['date']} {state['time']}"
    appt_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

    doctor_id = None
    if state.get("doctor_id"):
        # doctor_id was stored without dashes
        raw = state["doctor_id"]
        try:
            doctor_id = _uuid.UUID(raw) if "-" in raw else _uuid.UUID(
                f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
            )
        except Exception:
            doctor_id = None

    async with AsyncSessionLocal() as db:
        appt = Appointment(
            platform="zalo",
            zalo_user_id=user_id,
            patient_name=state.get("name", ""),
            doctor_id=doctor_id,
            appointment_date=appt_dt,
        )
        db.add(appt)
        await db.commit()

    await send_text(
        user_id,
        f"✅ Đã đặt lịch thành công!\n\n"
        f"📅 {appt_dt.strftime('%d/%m/%Y %H:%M')}\n"
        f"👨‍⚕️ {state.get('doctor_name', 'Bất kỳ')}\n\n"
        "Phòng khám sẽ xác nhận và nhắc bạn trước 1 tiếng.",
    )
