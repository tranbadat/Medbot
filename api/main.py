import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from telegram import Update
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters

from core.config import get_settings
from db.database import init_db
from db.redis_client import close_redis
from bot.relay import set_bot_app

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# Suppress noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("chromadb.telemetry").setLevel(logging.ERROR)
logging.getLogger("chromadb.segment").setLevel(logging.WARNING)
logging.getLogger("posthog").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_telegram_app: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telegram_app

    # Init DB
    await init_db()
    logger.info("Database initialized")

    # Warm up RAG: download embed model + load Chroma index now so the
    # first user request doesn't pay the cold-start cost.
    async def _warm_rag():
        try:
            from core.rag import get_index
            await get_index()
            # Also force the embed model to materialize by encoding a dummy.
            from llama_index.core import Settings as _LS
            if _LS.embed_model is not None:
                _LS.embed_model.get_text_embedding("warmup")
            logger.info("RAG warmed up")
        except Exception as e:
            logger.warning(f"RAG warmup failed: {e}")
    asyncio.create_task(_warm_rag())

    # Init Telegram bot
    _telegram_app = Application.builder().token(settings.TELEGRAM_TOKEN).build()

    from bot.handlers.message import handle_text
    from bot.handlers.file import handle_file, handle_voice
    from bot.handlers.callback import handle_callback
    from bot.handlers.appointment import build_appointment_handler, show_my_appointments, handle_cancel_appt_callback
    from bot.handlers.medicine_reminder import build_medicine_reminder_handler, show_reminders, handle_reminder_callback
    from bot.handlers.profile import build_profile_handler
    from bot.handlers.start import handle_start, handle_menu_callback
    from telegram.ext import CommandHandler

    # ConversationHandlers must be first (highest priority)
    _telegram_app.add_handler(build_appointment_handler())
    _telegram_app.add_handler(build_medicine_reminder_handler())
    _telegram_app.add_handler(build_profile_handler())
    _telegram_app.add_handler(CommandHandler("start", handle_start))
    _telegram_app.add_handler(CommandHandler("menu", handle_start))
    _telegram_app.add_handler(CommandHandler("lich", show_my_appointments))
    _telegram_app.add_handler(CommandHandler("danhsachthuoc", show_reminders))
    _telegram_app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)huỷ lịch|huy lich|xem lịch|lịch của tôi"),
        show_my_appointments,
    ))
    _telegram_app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)danh sách thuốc|xem thuốc|nhắc thuốc của tôi"),
        show_reminders,
    ))
    from bot.handlers.symptoms import handle_symptom_callback
    _telegram_app.add_handler(CallbackQueryHandler(handle_cancel_appt_callback, pattern="^cancel_appt:"))
    _telegram_app.add_handler(CallbackQueryHandler(handle_reminder_callback, pattern="^med:"))
    _telegram_app.add_handler(CallbackQueryHandler(handle_symptom_callback, pattern="^sym:"))
    _telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    _telegram_app.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file)
    )
    _telegram_app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice)
    )
    # Menu callbacks first, then general callback handler
    _telegram_app.add_handler(CallbackQueryHandler(handle_menu_callback, pattern="^menu:"))
    _telegram_app.add_handler(CallbackQueryHandler(handle_callback))

    await _telegram_app.initialize()
    set_bot_app(_telegram_app)

    if settings.WEBHOOK_BASE_URL:
        tg_webhook = f"{settings.WEBHOOK_BASE_URL}/telegram/webhook"
        try:
            await _telegram_app.bot.set_webhook(tg_webhook)
            logger.info(f"Telegram webhook set: {tg_webhook}")
        except Exception as e:
            logger.warning(f"Telegram webhook registration failed (will retry on next request): {e}")
    else:
        logger.warning("WEBHOOK_BASE_URL not set — webhooks not registered")

    if settings.WEBHOOK_BASE_URL and settings.ZALO_OA_ACCESS_TOKEN:
        from core.zalo_client import register_webhook as _zalo_register
        zalo_webhook = f"{settings.WEBHOOK_BASE_URL}/zalo/webhook"
        try:
            await _zalo_register(zalo_webhook)
        except Exception as e:
            logger.warning(f"Zalo webhook registration failed: {e}")
    elif settings.ZALO_OA_ACCESS_TOKEN:
        logger.warning("ZALO_OA_ACCESS_TOKEN set but WEBHOOK_BASE_URL missing — Zalo webhook not registered")

    # Seed test doctor if needed
    await _seed_demo_doctor()

    # Start session idle-timeout background task
    from core.session_timeout import run_session_timeout_loop
    timeout_task = asyncio.create_task(run_session_timeout_loop())

    # Start appointment reminder background task
    from core.appointment_reminder import run_appointment_reminder_loop
    reminder_task = asyncio.create_task(run_appointment_reminder_loop())

    # Start medicine reminder background task
    from core.medicine_reminder_task import run_medicine_reminder_loop
    asyncio.create_task(run_medicine_reminder_loop())

    yield

    timeout_task.cancel()
    reminder_task.cancel()
    await close_redis()
    if _telegram_app:
        await _telegram_app.shutdown()


async def _seed_demo_doctor():
    from db.database import AsyncSessionLocal
    from db.models import Doctor
    from sqlalchemy import select
    import bcrypt as _bcrypt

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Doctor).limit(1))
        if result.scalar_one_or_none():
            return
        pw_hash = _bcrypt.hashpw(b"doctor123", _bcrypt.gensalt()).decode()
        doctor = Doctor(
            name="BS. Nguyễn Minh Tuấn",
            specialty="Nội tổng quát",
            username="doctor1",
            password_hash=pw_hash,
            working_hours="8:00 - 17:00 (T2-T7)",
            is_active=True,
        )
        db.add(doctor)
        await db.commit()
        logger.info("Demo doctor seeded: doctor1 / doctor123")


app = FastAPI(title="MedBot API", version="1.0.0", lifespan=lifespan)

# Mount static dashboards
import os
dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")

# Serve domain verification files (Zalo, Google, etc.) from public/
_public_path = os.path.join(os.path.dirname(__file__), "..", "public")
os.makedirs(_public_path, exist_ok=True)

from fastapi.responses import FileResponse
@app.get("/admin")
async def admin_ui():
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "admin.html")
    return FileResponse(path)

# Include routers
from api.routes.chat import router as chat_router
from api.routes.session import router as session_router
from api.routes.doctor import router as doctor_router
from api.routes.admin import router as admin_router

app.include_router(chat_router)
app.include_router(session_router)
app.include_router(doctor_router)
app.include_router(admin_router)


# Telegram webhook endpoint
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if _telegram_app is None:
        return {"ok": False, "error": "Bot not initialized"}
    update_data = await request.json()
    update = Update.de_json(update_data, _telegram_app.bot)
    await _telegram_app.process_update(update)
    return {"ok": True}


# WebSocket: doctor stream
@app.websocket("/ws/doctor/{doctor_id}")
async def ws_doctor(websocket: WebSocket, doctor_id: str):
    from api.websocket import ws_manager
    await ws_manager.connect_doctor(doctor_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            event = payload.get("event")

            if event == "set_status":
                from db.redis_client import set_doctor_status
                await set_doctor_status(doctor_id, payload.get("status", "online"))

            elif event == "send_message":
                from db.database import AsyncSessionLocal
                from db.models import Session as DBSession, Message, MessageRole, SessionStatus
                from sqlalchemy import select
                import uuid

                case_id = payload.get("case_id")
                content = payload.get("content", "")
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(DBSession).where(DBSession.id == uuid.UUID(case_id)))
                    session = result.scalar_one_or_none()
                    if session:
                        from datetime import datetime as _dt
                        name = payload.get("doctor_name", "Bác sĩ")
                        from bot.relay import send_to_session
                        await send_to_session(session, f"BS. {name}: {content}")
                        msg = Message(session_id=session.id, role=MessageRole.doctor, content=content)
                        db.add(msg)
                        session.last_activity_at = _dt.utcnow()
                        await db.commit()

            elif event == "accept_case":
                from db.database import AsyncSessionLocal
                from db.models import Session as DBSession, SessionStatus
                from sqlalchemy import select
                import uuid

                case_id = payload.get("case_id")
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(DBSession).where(DBSession.id == uuid.UUID(case_id)))
                    session = result.scalar_one_or_none()
                    if session:
                        session.doctor_id = uuid.UUID(doctor_id)
                        session.status = SessionStatus.active
                        await db.commit()
                        from bot.relay import send_to_session
                        doctor_name = payload.get("doctor_name", "bác sĩ")
                        await send_to_session(
                            session,
                            f"✅ BS. {doctor_name} đã nhận ca của bạn. Bạn có thể nhắn tin trực tiếp."
                        )

    except WebSocketDisconnect:
        ws_manager.disconnect_doctor(doctor_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for doctor {doctor_id}: {e}")
        ws_manager.disconnect_doctor(doctor_id, websocket)


# WebSocket: session chat panel
@app.websocket("/ws/session/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    from api.websocket import ws_manager
    await ws_manager.connect_session(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_session(session_id, websocket)


@app.get("/api/telegram/file/{file_id}")
async def telegram_file_proxy(file_id: str):
    """Proxy a Telegram file by file_id so the doctor dashboard can display images."""
    import httpx
    from fastapi.responses import StreamingResponse
    if _telegram_app is None:
        raise HTTPException(503, "Bot not initialized")
    tg_file = await _telegram_app.bot.get_file(file_id)
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", tg_file.file_path) as r:
                async for chunk in r.aiter_bytes(65536):
                    yield chunk
    mime = "image/jpeg"
    if tg_file.file_path and tg_file.file_path.endswith(".png"):
        mime = "image/png"
    return StreamingResponse(stream(), media_type=mime)


@app.get("/zalo/webhook")
async def zalo_webhook_verify(request: Request):
    """Zalo OA webhook verification (GET challenge)."""
    return {"error": 0}


@app.post("/zalo/webhook")
async def zalo_webhook(request: Request):
    if not get_settings().ZALO_APP_SECRET and not get_settings().ZALO_OA_ACCESS_TOKEN:
        return {"error": 0, "message": "Zalo not configured"}
    from bot.zalo.webhook import handle_zalo_webhook
    return await handle_zalo_webhook(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/{filename:path}", include_in_schema=False)
async def serve_public_file(filename: str):
    """Serve static verification files (Zalo, Google, etc.) from public/."""
    import pathlib
    safe = pathlib.Path(_public_path) / filename
    if not str(safe.resolve()).startswith(str(pathlib.Path(_public_path).resolve())):
        raise HTTPException(404)
    if safe.is_file():
        return FileResponse(str(safe))
    raise HTTPException(404)
