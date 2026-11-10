"""评测脚本：跑 50 条用例，算出回答准确率与检索命中率。

用法（项目根目录）：
    python scripts/eval.py
    python scripts/eval.py --limit 10          # 先跑几条看看

判分方式：关键词匹配（确定性、可复现、不额外花钱）。
  - 正样本：must_contain 里的关键词必须全部出现在答案中
  - 负样本：答案必须明确表示"资料里没有"

之所以同时统计检索命中率：回答错可能是模型编的，也可能是压根没检索到正确资料。
不分层就看不出该修哪一层。
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from datetime import datetime
from pathlib import Path

# 直接运行脚本时，把项目根目录加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import retrieval

logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")
log = logging.getLogger("eval")

NEG_MARKERS = ["没有找到", "没有相关", "资料里没有", "未找到", "没有提及",
               "无法回答", "没有提供", "未涉及", "没有包含", "资料中未"]


def norm(text: str) -> str:
    return "".join((text or "").lower().split())


def judge_answer(case: dict, answer: str) -> bool:
    a = norm(answer)
    if case["answerable"]:
        return all(norm(kw) in a for kw in case["must_contain"])
    return any(norm(m) in a for m in NEG_MARKERS)


def judge_retrieval(case: dict, sources: list[dict]) -> bool | None:
    """期望文档是否出现在引用的出处里。多跳/负样本不判。"""
    if not case.get("doc"):
        return None
    titles = norm(" ".join(s["title"] for s in sources))
    return norm(case["doc"]) in titles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="eval/cases.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="eval/results")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"用例文件不存在：{cases_path.resolve()}", file=sys.stderr)
        return 2

    data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    if args.limit:
        cases = cases[: args.limit]

    rows = []
    for i, case in enumerate(cases, start=1):
        try:
            answer, sources, tin, tout, latency = retrieval.answer(case["question"])
            ok = judge_answer(case, answer)
            r_ok = judge_retrieval(case, sources)
            rows.append({
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "answer": answer,
                "sources": [s["title"] for s in sources],
                "answer_ok": ok,
                "retrieval_ok": r_ok,
                "latency_ms": latency,
                "token_in": tin,
                "token_out": tout,
            })
            flag = "✓" if ok else "✗"
            print(f"[{i:>2}/{len(cases)}] {flag} #{case['id']:<2} {case['category']:<8} {case['question'][:32]}")
        except Exception as exc:
            rows.append({
                "id": case["id"], "category": case["category"], "question": case["question"],
                "answer": "", "sources": [], "answer_ok": False, "retrieval_ok": None,
                "latency_ms": 0, "token_in": 0, "token_out": 0,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"[{i:>2}/{len(cases)}] ! #{case['id']:<2} 失败: {type(exc).__name__}: {exc}")

    total = len(rows)
    answer_ok = sum(1 for r in rows if r["answer_ok"])
    retr_rows = [r for r in rows if r["retrieval_ok"] is not None]
    retr_ok = sum(1 for r in retr_rows if r["retrieval_ok"])
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]

    def pct(a: int, b: int) -> str:
        return f"{a}/{b} ({a / b * 100:.1f}%)" if b else "-"

    print("\n" + "=" * 62)
    print("总体")
    print("=" * 62)
    print(f"  回答准确率 : {pct(answer_ok, total)}")
    if retr_rows:
        print(f"  检索命中率 : {pct(retr_ok, len(retr_rows))}   （仅对指定了期望文档的用例）")
    if latencies:
        lat = sorted(latencies)
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        print(f"  延迟       : 平均 {statistics.mean(lat):.0f} ms / P95 {p95} ms")

    print("\n按类别")
    for cat in ["single", "multi", "negative"]:
        sub = [r for r in rows if r["category"] == cat]
        if sub:
            ok = sum(1 for r in sub if r["answer_ok"])
            print(f"  {cat:<9}: {pct(ok, len(sub))}")

    print("\n失败用例")
    failed = [r for r in rows if not r["answer_ok"]]
    if not failed:
        print("  无")
    for r in failed:
        print(f"  #{r['id']} [{r['category']}] {r['question']}")
        print(f"      答案: {(r['answer'] or '(空)')[:90]}")
        print(f"      出处: {', '.join(r['sources']) or '(无)'}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"{stamp}.json"
    out_file.write_text(json.dumps({
        "meta": {
            "total": total,
            "answer_accuracy": round(answer_ok / total, 4) if total else 0,
            "retrieval_hit_rate": round(retr_ok / len(retr_rows), 4) if retr_rows else None,
            "avg_latency_ms": round(statistics.mean(latencies)) if latencies else None,
            "run_at": stamp,
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
