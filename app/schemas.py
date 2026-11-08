from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="用户提出的问题")


class AskResponse(BaseModel):
    answer: str
    latency_ms: int
    token_in: int
    token_out: int
    query_id: int


class HealthResponse(BaseModel):
    status: str
    db: str
