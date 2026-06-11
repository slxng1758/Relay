"""
LLM provider factory – returns a LangChain chat model based on settings.
Agents import get_llm() and never hard-code provider/model strings.
"""
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_llm(
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    streaming: bool = False,
) -> BaseChatModel:
    _provider = provider or settings.default_llm_provider
    _model = model or settings.default_model
    _temp = temperature if temperature is not None else settings.agent_temperature

    logger.debug("llm.factory", provider=_provider, model=_model, temperature=_temp)

    if _provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=_model,
            anthropic_api_key=settings.anthropic_api_key,
            temperature=_temp,
            max_tokens=settings.agent_max_tokens,
            streaming=streaming,
        )

    if _provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=_model,
            openai_api_key=settings.openai_api_key,
            temperature=_temp,
            max_tokens=settings.agent_max_tokens,
            streaming=streaming,
        )

    raise ValueError(f"Unsupported LLM provider: {_provider}")