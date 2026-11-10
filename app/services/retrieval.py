"""检索增强问答：先检索片段，再让模型基于片段回答，并返回出处。"""
import logging

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
    hits = db.search_chunks(embeddings.to_pgvector(vec), s.retrieval_top_k)
    log.info("检索完成 question_len=%d hits=%d", len(question), len(hits))

    prompt = PROMPT_TMPL.format(context=_format_context(hits), question=question)
    answer_text, token_in, token_out, latency_ms = llm.ask(prompt)

    sources = [
        {
            "index": i,
            "title": h["title"],
            "page_no": h["page_no"],
            "chunk_index": h["chunk_index"],
            "score": round(float(h["score"]), 4),
            "snippet": h["content"][:120],
        }
        for i, h in enumerate(hits, start=1)
    ]
    return answer_text, sources, token_in, token_out, latency_ms
