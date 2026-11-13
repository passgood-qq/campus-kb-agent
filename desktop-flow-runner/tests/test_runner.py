"""执行器单元测试：全部用 MockBackend，不需要真实桌面。"""
import logging

import pytest

from backends import BackendError, MockBackend
from runner import FlowError, run_flow

FAKE_CLOCK = lambda: 0.0  # noqa: E731
NO_SLEEP = lambda _s: None  # noqa: E731


def flow(*steps, retries=2, backoff=0.5):
    return {"retries": retries, "backoff": backoff, "steps": list(steps)}


def test_run_success_records_each_step():
    backend = MockBackend()
    result = run_flow(
        flow(
            {"action": "focus_window", "title": "记事本", "timeout": 3},
            {"action": "type_text", "text": "hello"},
            {"action": "screenshot", "path": "out/a.png"},
        ),
        backend,
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is True
    assert [s.action for s in result.steps] == ["focus_window", "type_text", "screenshot"]
    assert all(s.attempts == 1 for s in result.steps)
    assert ("type_text", ("hello",), {}) in backend.calls


def test_retry_then_success():
    backend = MockBackend(fail_plan={"type_text": [True, True, False]})
    result = run_flow(
        flow({"action": "type_text", "text": "hi", "retries": 3}),
        backend,
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is True
    assert result.steps[0].attempts == 3


def test_retry_exhausted_returns_failure():
    backend = MockBackend(fail_plan={"type_text": [True, True, True, True]})
    result = run_flow(
        flow({"action": "type_text", "text": "hi", "retries": 2}),
        backend,
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is False
    assert result.steps[0].attempts == 3          # 首次 + 2 次重试
    assert "mock 失败" in (result.failed_step.error or "")


def test_window_not_found_is_retried_then_reported():
    backend = MockBackend(windows=["别的窗口"])
    result = run_flow(
        flow({"action": "focus_window", "title": "记事本", "timeout": 1, "retries": 1}),
        backend,
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is False
    assert result.steps[0].attempts == 2
    assert "未找到窗口" in (result.failed_step.error or "")


def test_unknown_action_aborts_without_retry():
    backend = MockBackend()
    with pytest.raises(FlowError):
        run_flow(flow({"action": "no_such_action"}), backend, sleep=NO_SLEEP,
                 clock=FAKE_CLOCK, logger=logging.getLogger("test"))


def test_empty_steps_rejected():
    with pytest.raises(FlowError):
        run_flow({"steps": []}, MockBackend())


def test_focus_window_accepts_multiple_title_candidates():
    """窗口标题随语言变化（'记事本' vs 'Notepad'），任一候选命中即可。"""
    backend = MockBackend(windows=["neon-db-url.txt - Notepad"])
    result = run_flow(
        flow({"action": "focus_window", "titles": ["记事本", "Notepad"], "timeout": 2}),
        backend,
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is True
    assert result.steps[0].attempts == 1


def test_non_retryable_error_stops_immediately():
    class Fatal(MockBackend):
        def type_text(self, text):
            raise BackendError("配置错误", retryable=False)

    result = run_flow(
        flow({"action": "type_text", "text": "x", "retries": 5}),
        Fatal(),
        sleep=NO_SLEEP,
        clock=FAKE_CLOCK,
        logger=logging.getLogger("test"),
    )
    assert result.ok is False
    assert result.steps[0].attempts == 1          # 不可重试 → 只尝试一次
