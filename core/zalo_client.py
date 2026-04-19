"""Zalo OA API v3.0 client."""
import logging
import httpx
from core.config import get_settings

logger = logging.getLogger(__name__)
_BASE = "https://openapi.zalo.me/v3.0/oa"


def _headers() -> dict:
    return {"access_token": get_settings().ZALO_OA_ACCESS_TOKEN}


async def send_text(user_id: str, text: str) -> bool:
    payload = {
        "recipient": {"user_id": user_id},
        "message": {"text": text},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_BASE}/message/cs", json=payload, headers=_headers())
            data = r.json()
            if data.get("error") != 0:
                logger.warning(f"Zalo send_text error: {data}")
                return False
        return True
    except Exception as e:
        logger.error(f"Zalo send_text exception: {e}")
        return False


async def send_buttons(user_id: str, text: str, buttons: list[dict]) -> bool:
    """Send a button-template message. Each button: {title, payload} for postback
    or {title, url} for open-url. Max 3 buttons per message."""
    zalo_buttons = []
    for btn in buttons[:3]:
        if "url" in btn:
            zalo_buttons.append({"title": btn["title"], "type": "oa.open.url", "payload": {"url": btn["url"]}})
        else:
            zalo_buttons.append({"title": btn["title"], "type": "oa.query.hide", "payload": btn.get("payload", btn["title"])})

    payload = {
        "recipient": {"user_id": user_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": zalo_buttons,
                },
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_BASE}/message/cs", json=payload, headers=_headers())
            data = r.json()
            if data.get("error") != 0:
                logger.warning(f"Zalo send_buttons error: {data}")
                return False
        return True
    except Exception as e:
        logger.error(f"Zalo send_buttons exception: {e}")
        return False


async def send_list(user_id: str, elements: list[dict]) -> bool:
    """Send a list-template message.
    Each element: {title, subtitle, image_url (opt), buttons (opt list of {title,payload/url})}
    """
    zalo_elements = []
    for el in elements[:4]:  # Zalo max 4 elements
        ze: dict = {"title": el.get("title", ""), "subtitle": el.get("subtitle", "")}
        if el.get("image_url"):
            ze["image_url"] = el["image_url"]
        if el.get("buttons"):
            ze_btns = []
            for btn in el["buttons"][:1]:  # 1 button per element in list
                if "url" in btn:
                    ze_btns.append({"title": btn["title"], "type": "oa.open.url", "payload": {"url": btn["url"]}})
                else:
                    ze_btns.append({"title": btn["title"], "type": "oa.query.hide", "payload": btn.get("payload", btn["title"])})
            ze["default_action"] = ze_btns[0] if ze_btns else {}
        zalo_elements.append(ze)

    payload = {
        "recipient": {"user_id": user_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "list",
                    "elements": zalo_elements,
                },
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_BASE}/message/cs", json=payload, headers=_headers())
            data = r.json()
            if data.get("error") != 0:
                logger.warning(f"Zalo send_list error: {data}")
                return False
        return True
    except Exception as e:
        logger.error(f"Zalo send_list exception: {e}")
        return False


async def upload_image(image_bytes: bytes, filename: str = "image.jpg") -> str | None:
    """Upload image, return attachment_id for reuse."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{_BASE}/upload/image",
                files={"file": (filename, image_bytes, "image/jpeg")},
                headers=_headers(),
            )
            data = r.json()
            if data.get("error") != 0:
                logger.warning(f"Zalo upload_image error: {data}")
                return None
            return data.get("data", {}).get("attachment_id")
    except Exception as e:
        logger.error(f"Zalo upload_image exception: {e}")
        return None


async def send_image_by_id(user_id: str, attachment_id: str) -> bool:
    payload = {
        "recipient": {"user_id": user_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "media",
                    "elements": [{"media_type": "image", "attachment_id": attachment_id}],
                },
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_BASE}/message/cs", json=payload, headers=_headers())
            return r.json().get("error") == 0
    except Exception as e:
        logger.error(f"Zalo send_image exception: {e}")
        return False


async def register_webhook(callback_url: str) -> bool:
    """Register OA webhook URL — called on app startup."""
    events = [
        "user_send_text", "user_send_image", "user_send_file",
        "user_send_sticker", "follow", "unfollow",
    ]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://openapi.zalo.me/v2.0/oa/setwebhook",
                json={"callback_url": callback_url, "events": events},
                headers=_headers(),
            )
            data = r.json()
            if data.get("error") != 0:
                logger.warning(f"Zalo register_webhook error: {data}")
                return False
            logger.info(f"Zalo webhook registered: {callback_url}")
            return True
    except Exception as e:
        logger.error(f"Zalo register_webhook exception: {e}")
        return False


async def get_user_profile(user_id: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_BASE}/getprofile", params={"user_id": user_id}, headers=_headers())
            data = r.json()
            if data.get("error") != 0:
                return None
            return data.get("data")
    except Exception as e:
        logger.error(f"Zalo get_user_profile exception: {e}")
        return None
