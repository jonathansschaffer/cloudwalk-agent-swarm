from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's message or question.",
        examples=["What are the fees of the Maquininha Smart?"],
    )


class ChatResponse(BaseModel):
    response: str = Field(description="The agent's response to the user.")
    agent_used: str = Field(description="Which agent handled the request.")
    intent_detected: str = Field(description="The classified intent of the message.")
    ticket_id: Optional[str] = Field(
        default=None, description="Support ticket ID, if one was created."
    )
    escalated: bool = Field(
        default=False, description="Whether the conversation was escalated to a human."
    )
    language: str = Field(description="Detected language of the user's message.")


class HealthResponse(BaseModel):
    status: str
    knowledge_base_loaded: bool
    documents_indexed: int
