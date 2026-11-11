"""故障注入演示：让模型调用真的失败，验证「重试 → 熔断 → 降级」整条链路。

用法（项目根目录，需数据库在跑）：
    python scripts/demo_degrade.py

注入点是 llm._call_once —— 这样真实的 ask() 逻辑（重试、熔断打点）都会执行。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm


def show(tag: str, r) -> None:
    body = r.json()
    print(f"\n--- {tag} ---")
    print("HTTP", r.status_code)
    if r.status_code == 200:
        print("status :", body.get("status"))
        print("answer :", (body.get("answer") or "")[:70].replace("\n", " "))
        print("query  : #%s" % body.get("query_id"))
    else:
        print("detail :", body.get("detail"))
    print("熔断器 :", llm.get_breaker().state.value,
          "| 连续失败:", llm.get_breaker().failures)


def main() -> int:
    q = {"question": "什么是 RAG？"}

    with TestClient(app) as client:
        show("1 正常请求", client.post("/ask", json=q))
        print("healthz:", client.get("/healthz").json())

        # 注入故障：真正让 SDK 调用抛错，ask() 内的重试与熔断逻辑照常执行
        def _boom(*args, **kwargs):
            raise RuntimeError("模拟上游 503")

        original = llm._call_once
        llm._call_once = _boom
        try:
            for i in range(1, 5):
                t0 = time.perf_counter()
                r = client.post("/ask", json=q)
                cost = (time.perf_counter() - t0) * 1000
                show(f"2.{i} 故障请求（耗时 {cost:.0f} ms）", r)
        finally:
            llm._call_once = original

        print("\n恢复上游后 healthz:", client.get("/healthz").json())

    return 0


if __name__ == "__main__":
    sys.exit(main())
