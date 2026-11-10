"""向量化封装。与 llm.py 同构：所有外部异常统一收敛成 EmbeddingError。"""
import logging
from functools import lru_cache

from openai import OpenAI

from app.config import get_settings

log = logging.getLogger("app.embeddings")


class EmbeddingError(RuntimeError):
    """向量服务不可用或返回异常。"""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    s = get_settings()
    if not s.embedding_api_key:
        raise EmbeddingError("未配置 EMBEDDING_API_KEY")
    return OpenAI(
        api_key=s.embedding_api_key,
        base_url=s.embedding_base_url,
        timeout=30,
        max_retries=1,
    )


def embed_batch(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    """批量向量化。接口一次能收多条，比逐条调用快得多。"""
    if not texts:
        return []
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        part = texts[i : i + batch_size]
        try:
            resp = _client().embeddings.create(model=s.embedding_model, input=part)
        except Exception as exc:
            raise EmbeddingError(
                f"embedding 调用失败：{type(exc).__name__}: {exc}"
            ) from exc
        out.extend(d.embedding for d in resp.data)
    log.info("embedding 完成 count=%d dim=%d", len(out), len(out[0]) if out else 0)
    return out


def embed_one(text: str) -> list[float]:
    return embed_batch([text])[0]


def to_pgvector(vec: list[float]) -> str:
    """转成 pgvector 能吃的字面量：'[0.1,0.2,...]'。"""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
