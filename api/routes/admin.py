import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import bcrypt
import jwt

from db.database import get_db
from db.models import (
    Doctor, Session as DBSession, Message, Appointment, Shift, Patient,
    SessionStatus, AppointmentStatus, StaffRole,
)
from core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")
settings = get_settings()


# ── Auth ───────────────────────────────────────────────────────────────────

def _create_admin_token() -> str:
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


async def get_admin(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], settings.JWT_SECRET, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise HTTPException(403, "Admin only")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


class AdminLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def admin_login(req: AdminLoginRequest):
    if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    return {"token": _create_admin_token(), "username": req.username}


# ── Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(_: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    from db.redis_client import get_online_doctors

    total_doctors = (await db.execute(select(func.count()).select_from(Doctor).where(Doctor.is_active == True))).scalar()
    total_nurses = (await db.execute(select(func.count()).select_from(Doctor).where(Doctor.is_active == True, Doctor.role == StaffRole.nurse.value))).scalar()
    active_sessions = (await db.execute(select(func.count()).select_from(DBSession).where(DBSession.status == SessionStatus.active))).scalar()
    pending_sessions = (await db.execute(select(func.count()).select_from(DBSession).where(DBSession.status == SessionStatus.pending))).scalar()
    total_patients = (await db.execute(select(func.count()).select_from(Patient))).scalar()

    today = datetime.utcnow().date()
    today_appointments = (await db.execute(
        select(func.count()).select_from(Appointment)
        .where(func.date(Appointment.appointment_date) == today)
    )).scalar()

    online_doctors = await get_online_doctors()

    return {
        "total_doctors": total_doctors,
        "total_nurses": total_nurses,
        "online_doctors": len(online_doctors),
        "active_sessions": active_sessions,
        "pending_sessions": pending_sessions,
        "total_patients": total_patients,
        "today_appointments": today_appointments,
    }


# ── Staff CRUD ─────────────────────────────────────────────────────────────

class StaffCreateRequest(BaseModel):
    name: str
    specialty: str
    username: str
    password: str
    working_hours: str = "8:00 - 17:00 (T2-T7)"
    role: str = "doctor"


class StaffUpdateRequest(BaseModel):
    name: str | None = None
    specialty: str | None = None
    working_hours: str | None = None
    role: str | None = None
    is_active: bool | None = None


@router.get("/staff")
async def list_staff(_: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    from db.redis_client import get_doctor_status
    result = await db.execute(select(Doctor).order_by(Doctor.role, Doctor.name))
    staff = result.scalars().all()
    out = []
    for s in staff:
        status = await get_doctor_status(str(s.id))
        out.append({
            "id": str(s.id),
            "name": s.name,
            "specialty": s.specialty,
            "role": s.role if isinstance(s.role, str) else s.role.value,
            "working_hours": s.working_hours,
            "is_active": s.is_active,
            "status": status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"staff": out}


@router.post("/staff")
async def create_staff(req: StaffCreateRequest, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Doctor).where(Doctor.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username đã tồn tại")

    if req.role not in (StaffRole.doctor.value, StaffRole.nurse.value):
        raise HTTPException(400, "role phải là 'doctor' hoặc 'nurse'")

    pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    doctor = Doctor(
        name=req.name, specialty=req.specialty, username=req.username,
        password_hash=pw_hash, working_hours=req.working_hours,
        role=req.role, is_active=True,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return {"id": str(doctor.id), "name": doctor.name, "role": doctor.role if isinstance(doctor.role, str) else doctor.role.value}


@router.put("/staff/{staff_id}")
async def update_staff(staff_id: str, req: StaffUpdateRequest, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(staff_id)))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Không tìm thấy")
    if req.name is not None: doctor.name = req.name
    if req.specialty is not None: doctor.specialty = req.specialty
    if req.working_hours is not None: doctor.working_hours = req.working_hours
    if req.role is not None: doctor.role = req.role
    if req.is_active is not None: doctor.is_active = req.is_active
    await db.commit()
    return {"ok": True}


@router.delete("/staff/{staff_id}")
async def deactivate_staff(staff_id: str, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(staff_id)))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Không tìm thấy")
    doctor.is_active = False
    await db.commit()
    return {"ok": True}


# ── Shifts ─────────────────────────────────────────────────────────────────

class ShiftCreateRequest(BaseModel):
    doctor_id: str
    shift_date: str        # "YYYY-MM-DD"
    start_time: str = "08:00"
    end_time: str = "17:00"
    note: str = ""


@router.get("/shifts")
async def list_shifts(
    doctor_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    _: dict = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date
    from sqlalchemy.orm import selectinload
    q = select(Shift).options(selectinload(Shift.doctor)).order_by(Shift.shift_date, Shift.start_time)
    if doctor_id:
        q = q.where(Shift.doctor_id == uuid.UUID(doctor_id))
    if from_date:
        q = q.where(Shift.shift_date >= date.fromisoformat(from_date))
    if to_date:
        q = q.where(Shift.shift_date <= date.fromisoformat(to_date))

    result = await db.execute(q)
    shifts = result.scalars().all()
    return {"shifts": [
        {
            "id": str(s.id),
            "doctor_id": str(s.doctor_id),
            "doctor_name": s.doctor.name if s.doctor else "",
            "shift_date": s.shift_date.isoformat(),
            "start_time": s.start_time,
            "end_time": s.end_time,
            "note": s.note,
        }
        for s in shifts
    ]}


@router.post("/shifts")
async def create_shift(req: ShiftCreateRequest, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    from datetime import date
    shift = Shift(
        doctor_id=uuid.UUID(req.doctor_id),
        shift_date=date.fromisoformat(req.shift_date),
        start_time=req.start_time,
        end_time=req.end_time,
        note=req.note or None,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return {"id": str(shift.id)}


@router.delete("/shifts/{shift_id}")
async def delete_shift(shift_id: str, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Shift).where(Shift.id == uuid.UUID(shift_id)))
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(404, "Không tìm thấy")
    await db.delete(shift)
    await db.commit()
    return {"ok": True}


# ── Appointments ───────────────────────────────────────────────────────────

@router.get("/appointments")
async def list_appointments(
    doctor_id: str | None = None,
    status: str | None = None,
    _: dict = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    q = select(Appointment).options(selectinload(Appointment.doctor)).order_by(Appointment.appointment_date)
    if doctor_id:
        q = q.where(Appointment.doctor_id == uuid.UUID(doctor_id))
    if status:
        q = q.where(Appointment.status == AppointmentStatus(status))
    result = await db.execute(q)
    appts = result.scalars().all()
    return {"appointments": [
        {
            "id": str(a.id),
            "patient_name": a.patient_name,
            "telegram_chat_id": a.telegram_chat_id,
            "doctor_id": str(a.doctor_id) if a.doctor_id else None,
            "doctor_name": a.doctor.name if a.doctor else "Chưa phân công",
            "appointment_date": a.appointment_date.isoformat(),
            "status": a.status.value,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in appts
    ]}


class AppointmentStatusUpdate(BaseModel):
    status: str
    doctor_id: str | None = None


@router.patch("/appointments/{appt_id}")
async def update_appointment(appt_id: str, req: AppointmentStatusUpdate, _: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Appointment).where(Appointment.id == uuid.UUID(appt_id)))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(404, "Không tìm thấy")
    appt.status = AppointmentStatus(req.status)
    if req.doctor_id:
        appt.doctor_id = uuid.UUID(req.doctor_id)
    await db.commit()

    # Notify patient via Telegram if confirmed
    if req.status == "confirmed":
        from bot.relay import send_to_appointment
        dt_str = appt.appointment_date.strftime("%d/%m/%Y %H:%M")
        doc_name = appt.doctor.name if appt.doctor else "bác sĩ phòng khám"
        await send_to_appointment(
            appt,
            f"✅ Lịch khám của bạn đã được xác nhận!\n"
            f"📅 {dt_str}\n👨‍⚕️ {doc_name}\n\nVui lòng đến đúng giờ."
        )
    return {"ok": True}


# ── Patients ───────────────────────────────────────────────────────────────

@router.get("/patients")
async def list_patients(_: dict = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Patient, func.count(DBSession.id).label("session_count"))
        .outerjoin(DBSession, DBSession.telegram_chat_id == Patient.telegram_chat_id)
        .group_by(Patient.id)
        .order_by(Patient.last_seen.desc())
    )
    rows = result.all()
    return {"patients": [
        {
            "id": str(p.id),
            "telegram_chat_id": p.telegram_chat_id,
            "name": p.telegram_name or "Ẩn danh",
            "username": p.telegram_username,
            "first_seen": p.first_seen.isoformat() if p.first_seen else None,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            "session_count": count,
        }
        for p, count in rows
    ]}


# ── Sessions overview ──────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(
    status: str | None = None,
    _: dict = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    q = select(DBSession).options(selectinload(DBSession.doctor)).order_by(DBSession.created_at.desc()).limit(100)
    if status:
        q = q.where(DBSession.status == SessionStatus(status))
    result = await db.execute(q)
    sessions = result.scalars().all()
    return {"sessions": [
        {
            "id": str(s.id),
            "user_id": s.user_id,
            "telegram_chat_id": s.telegram_chat_id,
            "doctor_id": str(s.doctor_id) if s.doctor_id else None,
            "doctor_name": s.doctor.name if s.doctor else None,
            "status": s.status.value,
            "specialty": s.specialty_requested,
            "urgency": s.urgency,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sessions
    ]}
