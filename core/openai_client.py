import openai
from core.config import get_settings
from core.prompts import SYSTEM_PROMPT

settings = get_settings()

_client: openai.AsyncOpenAI | None = None


def get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def chat(
    messages: list[dict],
    rag_context: str | None = None,
    max_tokens: int = 1024,
) -> str:
    client = get_client()

    system = SYSTEM_PROMPT
    if rag_context:
        system += f"\n\nNGUỒN TÀI LIỆU Y TẾ:\n{rag_context}"

    openai_messages = [{"role": "system", "content": system}] + messages

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        messages=openai_messages,
    )
    return response.choices[0].message.content or ""
