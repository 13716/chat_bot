import asyncio
from typing import AsyncGenerator
from loguru import logger
from core.config import get_settings

settings = get_settings()


class LLMService:
    """
    Fallback chain: Groq → Gemini → OpenAI → Anthropic
    Tự động skip provider nếu:
      - Không có API key
      - Quota hết (RateLimitError)
      - Lỗi kết nối
    """

    async def stream(
        self,
        messages: list[dict],
        system: str = "You are a helpful assistant.",
    ) -> AsyncGenerator[str, None]:
        for provider in settings.LLM_FALLBACK_ORDER:
            try:
                logger.info(f"Trying provider: {provider}")
                async for token in self._stream(provider, messages, system):
                    yield token
                return  # thành công → dừng fallback
            except Exception as e:
                logger.warning(f"Provider {provider} failed: {e}")
                continue

        yield "[ERROR] All providers failed. Check API keys or quota."

    async def _stream(
        self,
        provider: str,
        messages: list[dict],
        system: str,
    ) -> AsyncGenerator[str, None]:
        if provider == "deepseek":
            async for token in self._deepseek(messages, system):
                yield token
        elif provider == "groq":
            async for token in self._groq(messages, system):
                yield token
        elif provider == "gemini":
            async for token in self._gemini(messages, system):
                yield token
        elif provider == "openai":
            async for token in self._openai(messages, system):
                yield token
        elif provider == "anthropic":
            async for token in self._anthropic(messages, system):
                yield token

    # ── Deepseek ──────────────────────────────────────────
    async def _deepseek(self, messages, system) -> AsyncGenerator[str, None]:
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("No DEEPSEEK_API_KEY")
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
        stream = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token

    # ── Groq ──────────────────────────────────────────────
    async def _groq(self, messages, system) -> AsyncGenerator[str, None]:
        if not settings.GROQ_API_KEY:
            raise ValueError("No GROQ_API_KEY")
        from groq import AsyncGroq
        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        stream = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token

    # ── Gemini ────────────────────────────────────────────
    async def _gemini(self, messages, system) -> AsyncGenerator[str, None]:
        if not settings.GEMINI_API_KEY:
            raise ValueError("No GEMINI_API_KEY")
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system,
        )
        # Gemini dùng sync stream → wrap trong thread
        history = [
            {"role": m["role"] if m["role"] != "assistant" else "model",
             "parts": [m["content"]]}
            for m in messages[:-1]
        ]
        chat = model.start_chat(history=history)
        response = await asyncio.to_thread(
            chat.send_message, messages[-1]["content"], stream=True
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text

    # ── OpenAI ────────────────────────────────────────────
    async def _openai(self, messages, system) -> AsyncGenerator[str, None]:
        if not settings.OPENAI_API_KEY:
            raise ValueError("No OPENAI_API_KEY")
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        stream = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token

    # ── Anthropic ─────────────────────────────────────────
    async def _anthropic(self, messages, system) -> AsyncGenerator[str, None]:
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("No ANTHROPIC_API_KEY")
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        async with client.messages.stream(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text


# Singleton
llm_service = LLMService()