"""
Anthropic async client factory.
Agents call get_async_anthropic() and use the SDK directly — no LangChain wrapper.
"""
from functools import lru_cache

import anthropic

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def get_async_anthropic() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def complete(prompt: str, temperature: float = 0.2) -> str:
    """Single-turn text completion. Used by all specialist agents."""
    client = get_async_anthropic()
    response = await client.messages.create(
        model=settings.default_model,
        max_tokens=settings.agent_max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
