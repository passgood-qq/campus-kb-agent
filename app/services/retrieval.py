"""检索增强问答：Agent（工具调用）+ 降级兜底。

正常路径：交给 Agent，由模型自己决定检索几次、检索什么。
降级路径：模型不可用或熔断时，直接用检索结果拼原文返回，不报 5xx。
"""
import logging
import re
from collections import namedtuple

from app.config import get_settings
from app.services import agent, db, embeddings, llm

log = logging.getLogger("app.retrieval")

AnswerResult = namedtuple(
    "AnswerResult", "answer sources token_in token_out latency_ms status tool_calls"
)

# 从问题里抽英文标识符：WHERE、HAVING、unique_ptr、3NF 之类
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,}")
EN_STOP = {
    "what", "which", "how", "why", "when", "who", "the", "and", "or",
    "is", "are", "was", "were", "a", "an", "of", "to", "in", "on", "for", "with",
    "vs", "versus", "do", "does", "did", "can", "be", "it", "this", "that", "not",
    "difference", "between", "use", "used", "using",
}
# 注意：不要把 where 放进来 —— 它既是英文疑问词，也是 SQL 关键字。


def extract_terms(question: str, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for m in TERM_RE.findall(question):
        low = m.lower()
        if len(m) < 2 or low in EN_STOP or low in seen:
            continue
        seen.add(low)
        terms.append(m)
    return terms[:limit]


def _search(question: str) -> list[dict]:
    s = get_settings()
    vec = embeddings.embed_one(question)
    return db.search_chunks_hybrid(
        embeddings.to_pgvector(vec), extract_terms(question), s.retrieval_top_k
    )


def _degraded_answer(hits: list[dict]) -> str:
    if not hits:
        return "模型服务当前不可用，且资料库没有检索到相关内容。"
    lines = ["（模型服务暂时不可用，以下为检索到的资料原文，仅供参考）"]
    for i, h in enumerate(hits[:3], start=1):
        page = f" 第 {h['page_no']} 页" if h.get("page_no") else ""
        lines.append(f"\n[{i}] 《{h['title']}》{page}\n{h['content'][:300]}")
    return "".join(lines)


def _to_sources(hits: list[dict]) -> list[dict]:
    return [
        {
            "index": i,
            "title": h["title"],
            "page_no": h.get("page_no"),
            "chunk_index": h["chunk_index"],
            "score": round(float(h.get("score") or 0.0), 4),
            "retrieved_by": h.get("retrieved_by", ""),
            "snippet": h["content"][:120],
        }
        for i, h in enumerate(hits, start=1)
    ]


def answer(question: str) -> AnswerResult:
    try:
        res = agent.run(question)
        return AnswerResult(
            res.answer, res.sources, res.token_in, res.token_out,
            res.latency_ms, "ok", res.tool_calls,
        )
    except (llm.LLMUnavailable, llm.LLMError) as exc:
        kind = "熔断" if isinstance(exc, llm.LLMUnavailable) else "调用失败"
        log.error("模型%s，切换降级：%s", kind, exc)
        hits = _search(question)
        return AnswerResult(
            _degraded_answer(hits), _to_sources(hits), 0, 0, 0, "degraded", []
        )
