import anthropic
from core.config import get_settings
from core.prompts import SYSTEM_PROMPT

settings = get_settings()

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
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

    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text
