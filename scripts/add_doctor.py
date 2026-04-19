#!/usr/bin/env python3
"""
Add a doctor to the database.

Usage (inside container):
    python scripts/add_doctor.py

Usage (from host via Docker):
    docker compose exec app python scripts/add_doctor.py

Or pass args directly:
    python scripts/add_doctor.py --name "BS. Nguyễn Văn A" --specialty "Nội tổng quát" \
        --username bsnguyenvana --password secret123
"""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from sqlalchemy import select
from db.database import AsyncSessionLocal, init_db
from db.models import Doctor


async def add_doctor(name: str, specialty: str, username: str, password: str, working_hours: str) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Doctor).where(Doctor.username == username))
        if existing.scalar_one_or_none():
            print(f"[ERROR] Username '{username}' already exists.")
            return

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        doctor = Doctor(name=name, specialty=specialty, username=username, password_hash=password_hash, working_hours=working_hours)
        db.add(doctor)
        await db.commit()
        await db.refresh(doctor)
        print(f"[OK] Doctor created:")
        print(f"     ID           : {doctor.id}")
        print(f"     Name         : {doctor.name}")
        print(f"     Specialty    : {doctor.specialty}")
        print(f"     Working hours: {doctor.working_hours}")
        print(f"     Username     : {doctor.username}")


def prompt_if_missing(args):
    if not args.name:
        args.name = input("Tên bác sĩ (vd: BS. Nguyễn Văn A): ").strip()
    if not args.specialty:
        args.specialty = input("Chuyên khoa (vd: Nội tổng quát): ").strip()
    if not args.working_hours:
        args.working_hours = input("Giờ làm việc [8:00 - 17:00 (T2-T7)]: ").strip() or "8:00 - 17:00 (T2-T7)"
    if not args.username:
        args.username = input("Username đăng nhập: ").strip()
    if not args.password:
        import getpass
        args.password = getpass.getpass("Mật khẩu: ")
        confirm = getpass.getpass("Xác nhận mật khẩu: ")
        if args.password != confirm:
            print("[ERROR] Mật khẩu không khớp.")
            sys.exit(1)
    return args


def main():
    parser = argparse.ArgumentParser(description="Add a doctor account to MedBot.")
    parser.add_argument("--name", default="", help="Full name, e.g. 'BS. Nguyễn Văn A'")
    parser.add_argument("--specialty", default="", help="Specialty, e.g. 'Nội tổng quát'")
    parser.add_argument("--working-hours", default="", dest="working_hours", help="e.g. '8:00 - 17:00 (T2-T7)'")
    parser.add_argument("--username", default="", help="Login username")
    parser.add_argument("--password", default="", help="Login password")
    args = parser.parse_args()

    args = prompt_if_missing(args)

    if not all([args.name, args.specialty, args.username, args.password]):
        print("[ERROR] All fields are required.")
        sys.exit(1)

    asyncio.run(add_doctor(args.name, args.specialty, args.username, args.password, args.working_hours))


if __name__ == "__main__":
    main()
