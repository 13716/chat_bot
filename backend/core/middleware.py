"""
FastAPI Middleware — Request logging, tracing, error capture
"""
import time
import uuid
import traceback

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging import request_id_var


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log mọi request: method, path, status, duration, request_id."""

    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        # Bỏ qua health check và docs
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Gán request_id duy nhất
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        token = request_id_var.set(req_id)

        start = time.perf_counter()

        # Log request đến
        logger.info(
            f"→ {request.method} {request.url.path}",
            extra={"req_id": req_id},
        )

        try:
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000

            level = "info" if response.status_code < 400 else "warning"
            getattr(logger, level)(
                f"← {response.status_code} {request.method} {request.url.path} "
                f"[{duration_ms:.0f}ms]"
            )

            # Thêm header cho client trace
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Duration-Ms"] = f"{duration_ms:.0f}"
            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"💥 UNHANDLED {request.method} {request.url.path} "
                f"[{duration_ms:.0f}ms] — {type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": req_id},
                headers={"X-Request-ID": req_id},
            )
        finally:
            request_id_var.reset(token)


class LLMTracingMiddleware:
    """
    Context manager để trace mỗi LLM call.
    Dùng trong llm.py và agent.py:
        async with LLMTracer("groq", "llama-3.3-70b") as t:
            ...
        # t.log() sẽ tự ghi kết quả
    """

    def __init__(self, provider: str, model: str, purpose: str = "chat"):
        self.provider = provider
        self.model = model
        self.purpose = purpose
        self._start = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.error: str | None = None

    async def __aenter__(self):
        self._start = time.perf_counter()
        logger.debug(f"🤖 LLM [{self.provider}/{self.model}] start — {self.purpose}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self._start) * 1000
        if exc_type:
            logger.warning(
                f"🤖 LLM [{self.provider}/{self.model}] FAILED [{duration_ms:.0f}ms] "
                f"— {exc_type.__name__}: {exc_val}"
            )
        else:
            logger.info(
                f"🤖 LLM [{self.provider}/{self.model}] OK [{duration_ms:.0f}ms] "
                f"— purpose={self.purpose}"
            )
        return False  # Không suppress exception
