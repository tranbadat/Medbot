import re
import json
import logging

logger = logging.getLogger(__name__)

OUT_OF_SCOPE_PATTERNS = [
    r"kê đơn|đơn thuốc|liều dùng|mg\s*\d|\d+\s*viên",
    r"chẩn đoán|tôi bị bệnh gì|xác nhận bệnh",
    r"phẫu thuật|mổ|can thiệp|thủ thuật",
    r"thuốc\s+\w+\s+\d",
]


def regex_check(text: str) -> bool:
    """Returns True if text matches any out-of-scope pattern."""
    text_lower = text.lower()
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def parse_claude_response(text: str) -> dict | None:
    """
    Returns parsed dict if Claude returned a request_doctor JSON,
    otherwise returns None (meaning in-scope reply).
    """
    text = text.strip()
    # Try to extract JSON block
    try:
        # Look for JSON object in response
        match = re.search(r"\{[^{}]*\"action\"\s*:\s*\"request_doctor\"[^{}]*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, Exception):
        pass

    # Try parsing entire response as JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("action") == "request_doctor":
            return data
    except (json.JSONDecodeError, Exception):
        pass

    return None
