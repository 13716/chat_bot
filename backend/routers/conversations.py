from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from db.database import get_db
from db import models

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ── Schemas ──────────────────────────────────────────────
class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    order: int

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    title: str
    messages: list[MessageOut] = []

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    role: str
    content: str


# ── Endpoints ─────────────────────────────────────────────
@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    convs = db.query(models.Conversation).order_by(models.Conversation.updated_at.desc()).all()
    return convs


@router.post("", response_model=ConversationOut)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    conv = models.Conversation(title=body.title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("/{conv_id}", response_model=ConversationOut)
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.patch("/{conv_id}", response_model=ConversationOut)
def update_title(conv_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = body.title
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"ok": True}


@router.post("/{conv_id}/messages", response_model=MessageOut)
def add_message(conv_id: str, body: MessageCreate, db: Session = Depends(get_db)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    count = db.query(models.Message).filter(models.Message.conversation_id == conv_id).count()
    msg = models.Message(
        conversation_id=conv_id,
        role=body.role,
        content=body.content,
        order=count,
    )
    db.add(msg)
    # cập nhật updated_at của conversation
    from sqlalchemy.sql import func
    conv.updated_at = func.now()
    db.commit()
    db.refresh(msg)
    return msg