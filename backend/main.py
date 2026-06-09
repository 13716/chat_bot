from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import get_settings
from core.logging import setup_logging
from core.middleware import RequestLoggingMiddleware
from models.schemas import HealthResponse
from routers.chat import router as chat_router
from routers.conversations import router as conv_router
from routers.profile import router as profile_router
from db.database import Base, engine
from routers.accounting import router as accounting_router
from routers.agent import router as agent_router
from routers.admin import router as admin_router

settings = get_settings()

# ── Setup logging sớm nhất có thể ────────────────────────────────────────
setup_logging(debug=settings.DEBUG)

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME, docs_url="/docs")

# ── Middleware — thứ tự quan trọng (LIFO: cái add sau chạy trước) ─────────
app.add_middleware(RequestLoggingMiddleware)          # Request trace + error capture
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(chat_router)
app.include_router(conv_router)
app.include_router(profile_router)
app.include_router(accounting_router)
app.include_router(agent_router)
app.include_router(admin_router)


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.on_event("startup")
async def startup():
    logger.info(f"🚀 Starting {settings.APP_NAME}")
    logger.info(f"LLM fallback order: {settings.LLM_FALLBACK_ORDER}")
    logger.info(f"Debug mode: {settings.DEBUG}")
