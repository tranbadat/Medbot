import redis.asyncio as aioredis
from core.config import get_settings
import json

settings = get_settings()
_redis: aioredis.Redis | None = None

DOCTOR_STATUS_PREFIX = "doctor:status:"
DOCTOR_STATUS_TTL = 3600  # 1 hour


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def set_doctor_status(doctor_id: str, status: str) -> None:
    r = await get_redis()
    await r.setex(f"{DOCTOR_STATUS_PREFIX}{doctor_id}", DOCTOR_STATUS_TTL, status)


async def get_doctor_status(doctor_id: str) -> str:
    r = await get_redis()
    status = await r.get(f"{DOCTOR_STATUS_PREFIX}{doctor_id}")
    return status or "offline"


async def get_online_doctors(specialty: str | None = None) -> list[dict]:
    r = await get_redis()
    keys = await r.keys(f"{DOCTOR_STATUS_PREFIX}*")

    all_online: list[dict] = []
    for key in keys:
        status = await r.get(key)
        if status != "online":
            continue
        doctor_id = key.replace(DOCTOR_STATUS_PREFIX, "")
        meta_raw = await r.get(f"doctor:meta:{doctor_id}")
        if meta_raw:
            all_online.append({**json.loads(meta_raw), "status": "online"})

    if specialty is None or not all_online:
        return all_online

    # 1. Exact match
    exact = [d for d in all_online if d.get("specialty") == specialty]
    if exact:
        return exact

    # 2. Case-insensitive partial match (e.g. "Nội tổng quát" matches "Nội khoa")
    sl = specialty.lower()
    partial = [
        d for d in all_online
        if sl in d.get("specialty", "").lower()
        or d.get("specialty", "").lower() in sl
    ]
    if partial:
        return partial

    # 3. Fallback: return all online doctors so user always has someone to choose
    return all_online


async def set_doctor_meta(doctor_id: str, name: str, specialty: str, working_hours: str = "8:00 - 17:00 (T2-T7)") -> None:
    r = await get_redis()
    data = json.dumps({"id": doctor_id, "name": name, "specialty": specialty, "working_hours": working_hours})
    await r.set(f"doctor:meta:{doctor_id}", data)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
