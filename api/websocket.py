import logging
from fastapi import WebSocket
from typing import Any
import json

logger = logging.getLogger(__name__)

# doctor_id -> list of WebSocket connections
doctor_connections: dict[str, list[WebSocket]] = {}
# session_id -> list of WebSocket connections
session_connections: dict[str, list[WebSocket]] = {}


class ConnectionManager:
    async def connect_doctor(self, doctor_id: str, ws: WebSocket) -> None:
        await ws.accept()
        doctor_connections.setdefault(doctor_id, []).append(ws)
        logger.info(f"Doctor {doctor_id} connected via WebSocket")

    def disconnect_doctor(self, doctor_id: str, ws: WebSocket) -> None:
        if doctor_id in doctor_connections:
            doctor_connections[doctor_id] = [
                c for c in doctor_connections[doctor_id] if c != ws
            ]

    async def connect_session(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        session_connections.setdefault(session_id, []).append(ws)

    def disconnect_session(self, session_id: str, ws: WebSocket) -> None:
        if session_id in session_connections:
            session_connections[session_id] = [
                c for c in session_connections[session_id] if c != ws
            ]

    async def send_to_doctor(self, doctor_id: str, payload: dict) -> None:
        conns = doctor_connections.get(doctor_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_doctor(doctor_id, ws)

    async def broadcast_to_session(self, session_id: str, payload: dict) -> None:
        conns = session_connections.get(session_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_session(session_id, ws)

    async def notify_new_case(self, doctor_id: str, case_payload: dict) -> None:
        await self.send_to_doctor(doctor_id, {"event": "new_case", **case_payload})

    async def relay_user_message(
        self, session_id: str, content: str, doctor_id: str | None = None
    ) -> None:
        payload = {"event": "user_message", "case_id": session_id, "content": content}
        await self.broadcast_to_session(session_id, payload)
        if doctor_id:
            await self.send_to_doctor(doctor_id, payload)

    async def broadcast_session_event(self, session_id: str, payload: dict) -> None:
        """Broadcast an event to both the session channel and the assigned doctor."""
        await self.broadcast_to_session(session_id, payload)


ws_manager = ConnectionManager()
