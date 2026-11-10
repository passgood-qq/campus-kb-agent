from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="用户提出的问题")


class Source(BaseModel):
    """答案引用的一段资料。index 与答案里的 [1] [2] 对应。"""

    index: int
    title: str
    page_no: int | None = None
    chunk_index: int
    score: float = Field(description="向量余弦相似度；关键词召回的片段为 0")
    retrieved_by: str = Field(default="", description="vector / keyword / both")
    snippet: str = Field(description="片段前 120 字")


class AskResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    latency_ms: int
    token_in: int
    token_out: int
    query_id: int


class HealthResponse(BaseModel):
    status: str
    db: str
    documents: int | None = None
    chunks: int | None = None
