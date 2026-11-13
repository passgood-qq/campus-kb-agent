"""Agent 可调用的工具：定义 schema 并分发执行。

工具是 Agent 与外部世界交互的唯一入口，所以这里做三件事：
  1. 用 JSON Schema 精确描述参数（模型据此生成调用）
  2. 分发时做参数校验与异常兜底（工具失败不能让整轮对话崩掉）
  3. 返回结构化文本，便于模型继续推理
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.config import get_settings
from app.services import db, embeddings

log = logging.getLogger("app.tools")

MAX_TOP_K = 10


class ToolError(RuntimeError):
    """工具执行失败，错误信息会回传给模型，让它自行决定下一步。"""


def _search_corpus(query: str, top_k: int = 5) -> dict[str, Any]:
    """检索课程资料库，返回片段与出处。"""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query 不能为空")
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 5
    top_k = max(1, min(top_k, MAX_TOP_K))

    vec = embeddings.embed_one(query)
    terms = _extract_terms(query)
    hits = db.search_chunks_hybrid(embeddings.to_pgvector(vec), terms, top_k)

    results = [
        {
            "chunk_id": h["chunk_id"],
            "title": h["title"],
            "chunk_index": h["chunk_index"],
            "score": round(float(h.get("score") or 0.0), 4),
            "retrieved_by": h.get("retrieved_by", ""),
            "content": h["content"],
        }
        for h in hits
    ]
    log.info("tool search_corpus query_len=%d top_k=%d hits=%d", len(query), top_k, len(results))
    return {"query": query, "count": len(results), "results": results}


def _extract_terms(text: str) -> list[str]:
    from app.services.retrieval import extract_terms  # 避免循环导入

    return extract_terms(text)


def _corpus_stats() -> dict[str, Any]:
    """资料库规模：文档数、片段数、已向量化片段数。"""
    stats = db.counts()
    log.info("tool corpus_stats %s", stats)
    return stats


_TOOLS: dict[str, Callable[..., dict]] = {
    "search_corpus": _search_corpus,
    "corpus_stats": _corpus_stats,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_corpus",
            "description": (
                "在课程资料库中检索与查询相关的片段。返回片段正文、出处文档名与相似度。"
                "当你需要查找课程资料内容时调用它；可以换不同的关键词多次调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或问题，尽量具体"},
                    "top_k": {
                        "type": "integer",
                        "description": f"返回片段数量，1-{MAX_TOP_K}，默认 5",
                        "minimum": 1,
                        "maximum": MAX_TOP_K,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "corpus_stats",
            "description": "查询资料库规模（文档数、片段数、已向量化片段数）。用户问资料库有多少资料时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def dispatch(name: str, arguments: str) -> tuple[str, dict | None]:
    """执行一次工具调用。返回 (回传给模型的文本, 结构化的原始结果)。

    任何异常都收敛成文本回传，不让工具故障中断整轮对话。
    """
    fn = _TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False), None

    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ToolError("参数必须是 JSON 对象")
    except Exception as exc:
        return json.dumps({"error": f"参数解析失败：{exc}"}, ensure_ascii=False), None

    try:
        result = fn(**args)
    except ToolError as exc:
        log.warning("工具 %s 参数错误：%s", name, exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False), None
    except TypeError as exc:
        log.warning("工具 %s 参数不匹配：%s", name, exc)
        return json.dumps({"error": f"参数不匹配：{exc}"}, ensure_ascii=False), None
    except Exception as exc:
        log.exception("工具 %s 执行失败", name)
        return json.dumps({"error": f"工具执行失败：{type(exc).__name__}: {exc}"}, ensure_ascii=False), None

    return json.dumps(result, ensure_ascii=False), result
