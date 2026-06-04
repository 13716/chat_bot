from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import get_settings
from models.schemas import HealthResponse
from routers.chat import router as chat_router
from routers.conversations import router as conv_router
from routers.profile import router as profile_router
from db.database import Base, engine
# 1. Import router mới (sau dòng from routers.profile import ...)
from routers.accounting import router as accounting_router
from routers.agent import router as agent_router
 

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME, docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conv_router)
app.include_router(profile_router)
# 2. Register router (sau dòng app.include_router(profile_router))
app.include_router(accounting_router)
app.include_router(agent_router)

@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.on_event("startup")
async def startup():
    logger.info(f"Starting {settings.APP_NAME}")
    logger.info(f"LLM fallback order: {settings.LLM_FALLBACK_ORDER}")