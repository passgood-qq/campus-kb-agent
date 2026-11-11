"""可靠性单元测试：熔断状态机、指数退避、降级兜底。

这些测试不需要数据库和模型 —— 全部依赖可注入的 clock / sleep / fake client。
"""
import pytest

from app.services import llm as llm_mod
from app.services.resilience import BreakerState, CircuitBreaker
from app.services.retrieval import _degraded_answer


# ---------------------------------------------------------------- 熔断器

def test_breaker_stays_closed_below_threshold():
    b = CircuitBreaker(failure_threshold=3, recovery_seconds=10, clock=lambda: 0.0)
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.CLOSED
    assert b.allow() is True


def test_breaker_opens_at_threshold():
    b = CircuitBreaker(failure_threshold=2, recovery_seconds=10, clock=lambda: 0.0)
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.OPEN
    assert b.allow() is False


def test_breaker_half_open_after_cooldown():
    now = {"t": 0.0}
    b = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: now["t"])
    b.record_failure()
    assert b.state is BreakerState.OPEN

    now["t"] = 6.0            # 冷却结束
    assert b.allow() is True  # 放一个请求试探
    assert b.state is BreakerState.HALF_OPEN


def test_half_open_failure_reopens():
    now = {"t": 0.0}
    b = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: now["t"])
    b.record_failure()
    now["t"] = 6.0
    b.allow()
    b.record_failure()        # 试探也失败 → 立刻重新打开
    assert b.state is BreakerState.OPEN


def test_success_closes_breaker():
    b = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: 0.0)
    b.record_failure()
    assert b.state is BreakerState.OPEN
    b.record_success()
    assert b.state is BreakerState.CLOSED
    assert b.failures == 0


def test_reset():
    b = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: 0.0)
    b.record_failure()
    b.reset()
    assert b.state is BreakerState.CLOSED
    assert b.allow() is True


# ---------------------------------------------------------------- 重试

class _Boom(Exception):
    pass


class _FailingClient:
    """模拟调用必然失败的 SDK 客户端。"""

    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise _Boom("upstream down")


def test_retry_uses_exponential_backoff():
    client = _FailingClient()
    delays: list[float] = []

    with pytest.raises(llm_mod.LLMError):
        llm_mod._call_with_retry(
            client, "m", "p", attempts=3, base_delay=0.5, sleep=delays.append
        )

    assert client.calls == 3
    assert delays == [0.5, 1.0]   # 最后一次不再等待


def test_retry_succeeds_on_second_attempt():
    class _FlakyClient:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise _Boom("first fails")
            return "ok"

    client = _FlakyClient()
    result = llm_mod._call_with_retry(
        client, "m", "p", attempts=3, base_delay=0.1, sleep=lambda _: None
    )
    assert result == "ok"
    assert client.calls == 2


# ---------------------------------------------------------------- 降级

def test_degraded_answer_returns_raw_snippets():
    hits = [
        {"title": "数据库原理与应用", "content": "第三范式要求非主属性不传递依赖于候选键。", "page_no": None},
        {"title": "Python 基础教程", "content": "列表作为默认参数只创建一次。", "page_no": None},
    ]
    text = _degraded_answer(hits)
    assert "暂时不可用" in text
    assert "数据库原理与应用" in text
    assert "第三范式" in text


def test_degraded_answer_without_hits():
    text = _degraded_answer([])
    assert "不可用" in text
