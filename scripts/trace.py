"""单条问题的全链路追踪：向量 → 检索 → prompt → 模型输出。

用法（项目根目录）：
    python scripts/trace.py "你的问题"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services import db, embeddings, llm, retrieval


def trace(question: str) -> None:
    s = get_settings()
    print("=" * 74)
    print("问题：", question)
    print("=" * 74)

    vec = embeddings.embed_one(question)
    print(f"[1] 向量化    dim={len(vec)}  前3维={[round(x, 4) for x in vec[:3]]}")

    hits = db.search_chunks_hybrid(
        embeddings.to_pgvector(vec),
        retrieval.extract_terms(question),
        s.retrieval_top_k,
    )
    print(f"[2] 混合检索  terms={retrieval.extract_terms(question)}  top-{s.retrieval_top_k}  命中 {len(hits)} 条")
    for i, h in enumerate(hits, start=1):
        print(f"    [{i}] 《{h['title']}》 chunk#{h['chunk_index']}  "
              f"score={float(h.get('score') or 0):.4f}  来源={h.get('retrieved_by')}")
        preview = h["content"][:90].replace("\n", " ")
        print(f"        {preview}…")

    context = retrieval._format_context(hits)
    prompt = retrieval.PROMPT_TMPL.format(context=context, question=question)
    print(f"\n[3] 拼出的 prompt  {len(prompt)} 字")
    print("-" * 74)
    print(prompt[:1800])
    if len(prompt) > 1800:
        print(f"…（后面还有 {len(prompt) - 1800} 字）")
    print("-" * 74)

    print("[4] 调用模型 …")
    answer, tin, tout, latency = llm.ask(prompt)
    print(f"    返回 tokens={tin}/{tout}  latency={latency}ms")

    print("\n[5] 模型输出")
    print("-" * 74)
    print(answer)
    print("-" * 74)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "候选键的定义是什么？"
    trace(q)
