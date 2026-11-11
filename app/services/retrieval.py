"""检索增强问答：混合检索 → 拼 prompt → 生成答案 → 返回出处。

降级策略：
  模型不可用（熔断打开）时，不报错，直接返回检索到的资料原文，status="degraded"。
  这比返回 502 更有用 —— 用户至少能看到"资料里写了什么"。
"""
import logging
import re
from collections import namedtuple

from app.config import get_settings
from app.services import db, embeddings, llm

log = logging.getLogger("app.retrieval")

AnswerResult = namedtuple(
    "AnswerResult", "answer sources token_in token_out latency_ms status"
)

PROMPT_TMPL = """你是课程资料助手。只能依据下面提供的资料回答。

资料：
{context}

问题：{question}

要求：
1. 用中文回答，简洁准确。
2. 如果资料里没有相关内容，直接回答"资料里没有找到相关内容"，不要编造。
3. 引用了哪段资料，就在句末用 [1] [2] 这样的编号标注。"""

# 从问题里抽英文标识符：WHERE、HAVING、unique_ptr、3NF 之类
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,}")
EN_STOP = {
    "what", "which", "how", "why", "when", "who", "the", "and", "or",
    "is", "are", "was", "were", "a", "an", "of", "to", "in", "on", "for", "with",
    "vs", "versus", "do", "does", "did", "can", "be", "it", "this", "that", "not",
    "difference", "between", "use", "used", "using",
}
# 注意：不要把 where 放进来 —— 它既是英文疑问词，也是 SQL 关键字，
# 当停用词过滤掉会导致「WHERE 和 HAVING 的区别」只抽出 HAVING。


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


def _format_context(hits: list[dict]) -> str:
    if not hits:
        return "（资料库为空或没有检索到相关内容）"
    blocks = []
    for i, h in enumerate(hits, start=1):
        page = f"第 {h['page_no']} 页" if h["page_no"] else "无页码"
        blocks.append(f"[{i}] 出自《{h['title']}》{page}\n{h['content']}")
    return "\n\n".join(blocks)


def _degraded_answer(hits: list[dict]) -> str:
    """模型不可用时的兜底：直接把检索到的原文摘录给用户。"""
    if not hits:
        return "模型服务当前不可用，且资料库没有检索到相关内容。"
    lines = ["（模型服务暂时不可用，以下为检索到的资料原文，仅供参考）"]
    for i, h in enumerate(hits[:3], start=1):
        page = f" 第 {h['page_no']} 页" if h["page_no"] else ""
        lines.append(f"\n[{i}] 《{h['title']}》{page}\n{h['content'][:300]}")
    return "".join(lines)


def answer(question: str) -> AnswerResult:
    s = get_settings()

    vec = embeddings.embed_one(question)
    terms = extract_terms(question)
    hits = db.search_chunks_hybrid(embeddings.to_pgvector(vec), terms, s.retrieval_top_k)
    log.info("检索完成 terms=%s hits=%d", terms, len(hits))

    prompt = PROMPT_TMPL.format(context=_format_context(hits), question=question)

    status = "ok"
    try:
        answer_text, token_in, token_out, latency_ms = llm.ask(prompt)
    except (llm.LLMUnavailable, llm.LLMError) as exc:
        # 两种情况都降级，区别只在日志：
        #   LLMUnavailable —— 熔断打开，压根没调，降级是"快速失败"
        #   LLMError       —— 调了但重试耗尽，降级是"兜底"
        kind = "熔断" if isinstance(exc, llm.LLMUnavailable) else "调用失败"
        log.error("模型%s，切换降级：%s", kind, exc)
        answer_text = _degraded_answer(hits)
        token_in = token_out = latency_ms = 0
        status = "degraded"

    sources = [
        {
            "index": i,
            "title": h["title"],
            "page_no": h["page_no"],
            "chunk_index": h["chunk_index"],
            "score": round(float(h.get("score") or 0.0), 4),
            "retrieved_by": h.get("retrieved_by", ""),
            "snippet": h["content"][:120],
        }
        for i, h in enumerate(hits, start=1)
    ]
    return AnswerResult(answer_text, sources, token_in, token_out, latency_ms, status)
