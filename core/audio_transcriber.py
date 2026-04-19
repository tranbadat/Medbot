"""Transcribe audio to text using OpenAI Whisper API."""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


async def transcribe(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """Send audio bytes to Whisper, return transcribed text or None on failure."""
    try:
        from openai import AsyncOpenAI
        from core.config import get_settings
        config = get_settings()

        # Use OpenAI key regardless of AI_ENGINE setting — Whisper is OpenAI-only
        if not config.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set — audio transcription unavailable")
            return None

        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

        suffix = os.path.splitext(filename)[1].lower() or ".ogg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=(filename, f),
                    language="vi",        # hint Vietnamese; Whisper auto-detects if wrong
                    response_format="text",
                )
            text = response.strip() if isinstance(response, str) else str(response).strip()
            logger.info(f"Transcribed audio ({len(audio_bytes)} bytes): {text[:80]}")
            return text or None
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        return None
