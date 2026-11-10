"""HTTP 路由。业务逻辑不写在这里，只做校验、组装、错误码转换。"""
import logging

from fastapi import APIRouter, HTTPException

from app.schemas import AskRequest, AskResponse, HealthResponse
from app.services import db, embeddings, llm, retrieval

log = logging.getLogger("app.api")

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["system"])
def healthz() -> HealthResponse:
    """存活探针：同时报出数据库里的资料规模，方便确认是否已灌库。"""
    ready = db.is_ready()
    stats: dict | None = None
    if ready:
        try:
            stats = db.counts()
        except Exception:  # 统计失败不影响健康判定
            log.warning("统计查询失败", exc_info=True)
    return HealthResponse(
        status="ok",
        db="up" if ready else "down",
        documents=(stats or {}).get("documents"),
        chunks=(stats or {}).get("chunks"),
    )


@router.post("/ask", response_model=AskResponse, tags=["qa"])
def ask(payload: AskRequest) -> AskResponse:
    try:
        answer, sources, token_in, token_out, latency_ms = retrieval.answer(payload.question)
    except embeddings.EmbeddingError as exc:
        log.error("向量化失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"检索服务不可用：{exc}") from exc
    except llm.LLMError as exc:
        log.error("生成失败：%s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        log.error("数据库不可用：%s", exc)
        raise HTTPException(status_code=503, detail=f"数据库不可用：{exc}") from exc

    try:
        query_id = db.save_query(payload.question, answer, latency_ms, token_in, token_out)
    except Exception as exc:
        log.exception("写入 queries 失败")
        raise HTTPException(status_code=500, detail="答案已生成，但记录落库失败") from exc

    return AskResponse(
        answer=answer,
        sources=sources,
        latency_ms=latency_ms,
        token_in=token_in,
        token_out=token_out,
        query_id=query_id,
    )
