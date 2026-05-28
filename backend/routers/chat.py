from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from services.llm import llm_service
from db.database import get_db
from db import models
from routers.profile import UserProfile, build_system_prompt

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatWithSaveRequest(BaseModel):
    messages: list[dict]
    system: str = ""
    conversation_id: Optional[str] = None


@router.post("/stream")
async def chat_stream(req: ChatWithSaveRequest, db: Session = Depends(get_db)):
    messages = req.messages
    full_response = []

    # Inject user profile vào system prompt
    profile = db.query(UserProfile).filter(UserProfile.id == 1).first()
    system = build_system_prompt(profile, req.system) if profile else (req.system or "You are a helpful assistant.")

    async def generate():
        async for token in llm_service.stream(messages, system):
            full_response.append(token)
            yield f"data: {token}\n\n"

        if req.conversation_id:
            try:
                count = db.query(models.Message).filter(
                    models.Message.conversation_id == req.conversation_id
                ).count()
                user_msg = messages[-1]
                db.add(models.Message(
                    conversation_id=req.conversation_id,
                    role=user_msg["role"],
                    content=user_msg["content"],
                    order=count,
                ))
                db.add(models.Message(
                    conversation_id=req.conversation_id,
                    role="assistant",
                    content="".join(full_response),
                    order=count + 1,
                ))
                db.commit()
            except Exception as e:
                from loguru import logger
                logger.error(f"Failed to save messages: {e}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )