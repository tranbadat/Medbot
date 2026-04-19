from db.redis_client import get_online_doctors, set_doctor_status, set_doctor_meta, get_doctor_status
from db.database import AsyncSessionLocal
from db.models import Doctor
from sqlalchemy import select


async def get_available_doctors(specialty: str | None = None) -> list[dict]:
    return await get_online_doctors(specialty)


async def sync_doctor_to_redis(doctor: Doctor) -> None:
    await set_doctor_meta(str(doctor.id), doctor.name, doctor.specialty)


async def update_doctor_status(doctor_id: str, status: str) -> None:
    await set_doctor_status(doctor_id, status)


async def get_all_doctors_from_db() -> list[Doctor]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Doctor).where(Doctor.is_active == True))
        return result.scalars().all()
