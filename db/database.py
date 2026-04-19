from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    from db.models import Base
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe column additions for existing deployments
        await conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS working_hours VARCHAR(100) DEFAULT '8:00 - 17:00 (T2-T7)'"))
        await conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'doctor'"))
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP DEFAULT NOW()"))
        await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN DEFAULT FALSE"))
        # Multi-platform support
        await conn.execute(text("ALTER TABLE patients ALTER COLUMN telegram_chat_id DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS zalo_user_id VARCHAR(100) UNIQUE"))
        await conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS zalo_name VARCHAR(200)"))
        await conn.execute(text("ALTER TABLE sessions ALTER COLUMN telegram_chat_id DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS platform VARCHAR(20) NOT NULL DEFAULT 'telegram'"))
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS zalo_user_id VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE appointments ALTER COLUMN telegram_chat_id DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS platform VARCHAR(20) NOT NULL DEFAULT 'telegram'"))
        await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS zalo_user_id VARCHAR(100)"))
        # Medicine reminders (create_all handles the table; extra safety no-ops)
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS medicine_reminders ("
            "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
            "platform VARCHAR(20) NOT NULL DEFAULT 'telegram', "
            "telegram_chat_id BIGINT, "
            "zalo_user_id VARCHAR(100), "
            "medicine_name VARCHAR(200) NOT NULL, "
            "reminder_times VARCHAR(500) NOT NULL, "
            "is_active BOOLEAN DEFAULT TRUE, "
            "created_at TIMESTAMP DEFAULT NOW())"
        ))
