"""
LLM-based intent classifier for user messages.

Returns one of a fixed set of intents so the bot can route to the right
handler (appointment view/book, medicine list/add, clinic info, SOS, doctor
call, menu, health question, other).
"""
import json
import logging
import re

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

INTENTS = {
    "menu",
    "appointment_view",
    "appointment_book",
    "appointment_cancel",
    "medicine_list",
    "medicine_add",
    "clinic_info",
    "sos",
    "call_doctor",
    "health_question",
    "other",
}

CLASSIFIER_PROMPT = """Bạn là bộ phân loại ý định cho chatbot y tế MedBot.
Phân loại tin nhắn của người dùng vào ĐÚNG MỘT nhãn trong danh sách:

- menu: người dùng muốn mở menu chính, xem các chức năng (vd: "menu", "trang chủ", "bắt đầu lại").
- appointment_view: xem lịch hẹn đã đặt với bác sĩ (vd: "lịch của tôi", "xem lịch khám").
- appointment_book: đặt lịch khám mới (vd: "đặt lịch", "tôi muốn khám").
- appointment_cancel: huỷ lịch khám.
- medicine_list: xem danh sách nhắc uống thuốc đã cài (vd: "lịch nhắc thuốc", "danh sách thuốc").
- medicine_add: tạo nhắc uống thuốc mới (vd: "nhắc tôi uống thuốc", "đặt nhắc thuốc").
- clinic_info: hỏi thông tin phòng khám: địa chỉ, giờ làm việc, giá, dịch vụ.
- sos: tình huống khẩn cấp, cần gọi cấp cứu, số khẩn.
- call_doctor: muốn nói chuyện trực tiếp với bác sĩ.
- health_question: hỏi về sức khoẻ, triệu chứng, dinh dưỡng, phòng bệnh, thuốc OTC.
- other: không thuộc các nhóm trên hoặc không rõ.

Nếu tin nhắn mơ hồ giữa appointment và medicine (vd chỉ có từ "lịch"), chọn "menu".
Nếu có dấu hiệu nguy hiểm (đau ngực, khó thở, bất tỉnh, chảy máu không cầm), chọn "sos".

CHỈ trả về JSON đúng dạng, không thêm văn bản:
{"intent": "<nhãn>", "confidence": <0.0-1.0>}"""


async def _classify_openai(text: str) -> dict | None:
    from core.openai_client import get_client
    client = get_client()
    try:
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=60,
            temperature=0,
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        return _parse(resp.choices[0].message.content or "")
    except Exception as e:
        logger.warning(f"intent classify (openai) failed: {e}")
        return None


async def _classify_claude(text: str) -> dict | None:
    from core.claude_client import get_client
    client = get_client()
    try:
        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=60,
            system=CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        return _parse(resp.content[0].text)
    except Exception as e:
        logger.warning(f"intent classify (claude) failed: {e}")
        return None


def _parse(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    intent = str(data.get("intent", "")).strip()
    if intent not in INTENTS:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"intent": intent, "confidence": confidence}


async def classify_intent(text: str) -> dict | None:
    text = (text or "").strip()
    if not text or len(text) > 500:
        return None
    if settings.AI_ENGINE == "openai":
        return await _classify_openai(text)
    return await _classify_claude(text)
