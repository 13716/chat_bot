from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import Optional
from db.database import get_db, Base

router = APIRouter(prefix="/profile", tags=["profile"])


# ── Model ─────────────────────────────────────────────────
class UserProfile(Base):
    __tablename__ = "user_profile"
    id = Column(Integer, primary_key=True, default=1)
    name = Column(Text, default="")
    age = Column(Integer, nullable=True)
    preferences = Column(Text, default="")
    extra = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Schemas ───────────────────────────────────────────────
class ProfileOut(BaseModel):
    name: str
    age: Optional[int]
    preferences: str
    extra: str

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    preferences: Optional[str] = None
    extra: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────
@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter(UserProfile.id == 1).first()
    if not profile:
        profile = UserProfile(id=1)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.put("", response_model=ProfileOut)
def update_profile(body: ProfileUpdate, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter(UserProfile.id == 1).first()
    if not profile:
        profile = UserProfile(id=1)
        db.add(profile)

    if body.name is not None: profile.name = body.name
    if body.age is not None: profile.age = body.age
    if body.preferences is not None: profile.preferences = body.preferences
    if body.extra is not None: profile.extra = body.extra

    db.commit()
    db.refresh(profile)
    return profile


# ── Helper: build system prompt với profile ───────────────
def build_system_prompt(profile: UserProfile, base: str = "") -> str:
    parts = []
    if profile.name:
        parts.append(f"The user's name is {profile.name}.")
    if profile.age:
        parts.append(f"They are {profile.age} years old.")
    if profile.preferences:
        parts.append(f"Their preferences: {profile.preferences}.")
    if profile.extra:
        parts.append(f"Additional context: {profile.extra}.")

    if not parts:
        return base or "You are a helpful assistant."

    profile_ctx = " ".join(parts)
    base_prompt = base or "You are a helpful assistant."
    return f"{base_prompt}\n\nUser context: {profile_ctx} Always address the user by name when appropriate."