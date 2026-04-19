import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, BigInteger, ForeignKey,
    Enum as SAEnum, DateTime, Boolean, Integer, Date, Time
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class SessionStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    closed = "closed"


class MessageRole(str, enum.Enum):
    user = "user"
    bot = "bot"
    doctor = "doctor"


class DoctorStatus(str, enum.Enum):
    online = "online"
    busy = "busy"
    offline = "offline"


class StaffRole(str, enum.Enum):
    doctor = "doctor"
    nurse = "nurse"


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    specialty = Column(String(100), nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default=StaffRole.doctor.value, nullable=False)
    working_hours = Column(String(100), nullable=True, default="8:00 - 17:00 (T2-T7)")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    shifts = relationship("Shift", back_populates="doctor")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(20), default="telegram", nullable=False)
    telegram_chat_id = Column(BigInteger, nullable=True, index=True)
    zalo_user_id = Column(String(100), nullable=True, index=True)
    user_id = Column(String(100), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=True)
    status = Column(SAEnum(SessionStatus), default=SessionStatus.pending)
    ai_summary = Column(Text, nullable=True)
    specialty_requested = Column(String(100), nullable=True)
    urgency = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("Doctor", back_populates="sessions")
    messages = relationship("Message", back_populates="session", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role = Column(SAEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    file_type = Column(String(20), nullable=True)
    file_extracted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="messages")


class AppointmentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(20), default="telegram", nullable=False)
    telegram_chat_id = Column(BigInteger, nullable=True, index=True)
    zalo_user_id = Column(String(100), nullable=True, index=True)
    patient_name = Column(String(200), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=True)
    appointment_date = Column(DateTime, nullable=False)
    note = Column(Text, nullable=True)
    status = Column(SAEnum(AppointmentStatus), default=AppointmentStatus.pending)
    reminder_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("Doctor", back_populates="appointments")


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=False)
    shift_date = Column(Date, nullable=False)
    start_time = Column(String(5), nullable=False, default="08:00")
    end_time = Column(String(5), nullable=False, default="17:00")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("Doctor", back_populates="shifts")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_name = Column(String(200), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    zalo_user_id = Column(String(100), unique=True, nullable=True, index=True)
    zalo_name = Column(String(200), nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    session_count = Column(Integer, default=0)


class MedicineReminder(Base):
    __tablename__ = "medicine_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(20), default="telegram", nullable=False)
    telegram_chat_id = Column(BigInteger, nullable=True, index=True)
    zalo_user_id = Column(String(100), nullable=True, index=True)
    medicine_name = Column(String(200), nullable=False)
    # comma-separated "HH:MM" strings, e.g. "08:00,12:00,20:00"
    reminder_times = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
