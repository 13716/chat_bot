from pydantic import BaseModel


class Message(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    system: str = "You are a helpful assistant."


class HealthResponse(BaseModel):
    status: str
    app: str