"""
Unified AI client — routes to Claude or OpenAI based on AI_ENGINE config.
All callers import from here instead of claude_client / openai_client directly.
"""
from core.config import get_settings

settings = get_settings()


async def chat(
    messages: list[dict],
    rag_context: str | None = None,
    max_tokens: int = 1024,
) -> str:
    if settings.AI_ENGINE == "openai":
        from core.openai_client import chat as _chat
    else:
        from core.claude_client import chat as _chat
    return await _chat(messages, rag_context=rag_context, max_tokens=max_tokens)
