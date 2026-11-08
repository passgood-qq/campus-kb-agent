"""HTTP 路由。业务逻辑不写在这里，只做校验、组装、错误码转换。"""
import logging

from fastapi import APIRouter, HTTPException

from app.schemas import AskRequest, AskResponse, HealthResponse
from app.services import db, llm

log = logging.getLogger("app.api")

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["system"])
def healthz() -> HealthResponse:
    """存活探针：服务起来就算 ok；db 字段反映数据库是否可用。"""
    return HealthResponse(status="ok", db="up" if db.is_ready() else "down")


@router.post("/ask", response_model=AskResponse, tags=["qa"])
def ask(payload: AskRequest) -> AskResponse:
    try:
        answer, token_in, token_out, latency_ms = llm.ask(payload.question)
    except llm.LLMError as exc:
        log.error("问答失败：%s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        query_id = db.save_query(payload.question, answer, latency_ms, token_in, token_out)
    except Exception as exc:
        log.exception("写入 queries 失败")
        raise HTTPException(status_code=500, detail="答案已生成，但记录落库失败") from exc

    return AskResponse(
        answer=answer,
        latency_ms=latency_ms,
        token_in=token_in,
        token_out=token_out,
        query_id=query_id,
    )
