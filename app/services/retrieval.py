"""检索增强问答：混合检索 → 拼 prompt → 生成答案 → 返回出处。

为什么要混合检索：
  纯向量检索对代码标识符（WHERE / HAVING / unique_ptr / 3NF）不敏感。
  评测里「WHERE 和 HAVING 有什么区别」曾完全召不回数据库文档，
  加上关键词召回并用 RRF 融合后解决。
"""
import logging
import re

from app.config import get_settings
from app.services import db, embeddings, llm

log = logging.getLogger("app.retrieval")

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


def answer(question: str) -> tuple[str, list[dict], int, int, int]:
    """返回 (答案, 出处列表, token_in, token_out, latency_ms)。"""
    s = get_settings()

    vec = embeddings.embed_one(question)
    terms = extract_terms(question)
    hits = db.search_chunks_hybrid(embeddings.to_pgvector(vec), terms, s.retrieval_top_k)
    log.info("检索完成 terms=%s hits=%d", terms, len(hits))

    prompt = PROMPT_TMPL.format(context=_format_context(hits), question=question)
    answer_text, token_in, token_out, latency_ms = llm.ask(prompt)

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
    return answer_text, sources, token_in, token_out, latency_ms
