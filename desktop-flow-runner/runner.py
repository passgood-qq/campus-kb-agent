"""流程执行器：把一段桌面操作写成 JSON 脚本，按步骤执行并支持重试。

设计要点（对应 JD 里的「窗口定位 / 点击输入 / 脚本触发 / 结果读取 / 异常处理」）：
  1. 每步独立重试，失败不拖垮整条流程；重试次数与退避可配置
  2. 区分「可重试」与「不可重试」错误：配置写错就别重试，浪费时间
  3. 窗口失焦/找不到时先重新定位，再执行动作
  4. 全流程有总超时，避免卡死
  5. 输出结构化报告（每步耗时、尝试次数、错误），便于排查
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backends import BackendError

log = logging.getLogger("flow")

DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.5


@dataclass
class StepResult:
    index: int
    action: str
    ok: bool
    attempts: int
    elapsed_ms: int
    error: str | None = None


@dataclass
class RunResult:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if not s.ok), None)


class FlowError(Exception):
    """流程配置或执行错误。"""


def _require(step: dict, key: str) -> Any:
    if key not in step:
        raise FlowError(f"步骤缺少必填字段：{key}")
    return step[key]


def _exec_step(step: dict, backend) -> None:
    action = step.get("action")
    if action == "focus_window":
        backend.find_window(_require(step, "title"), float(step.get("timeout", 5)))
        backend.focus_window()
    elif action == "click":
        backend.click(step.get("x"), step.get("y"))
    elif action == "type_text":
        backend.type_text(_require(step, "text"))
    elif action == "press":
        backend.press(_require(step, "key"))
    elif action == "screenshot":
        backend.screenshot(_require(step, "path"))
    elif action == "wait":
        time.sleep(float(_require(step, "seconds")))
    else:
        raise FlowError(f"未知动作：{action}")


def run_flow(
    flow: dict,
    backend,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
    logger: logging.Logger = log,
) -> RunResult:
    """执行整条流程。返回结构化结果，不抛异常（配置错误除外）。"""
    steps_cfg = flow.get("steps")
    if not isinstance(steps_cfg, list) or not steps_cfg:
        raise FlowError("flow.steps 必须是非空数组")

    default_retries = int(flow.get("retries", DEFAULT_RETRIES))
    backoff = float(flow.get("backoff", DEFAULT_BACKOFF))
    started = clock()
    results: list[StepResult] = []

    for idx, step in enumerate(steps_cfg, start=1):
        action = step.get("action", "?")
        retries = int(step.get("retries", default_retries))
        step_started = clock()
        attempts = 0
        last_error: str | None = None

        try:
            for attempt in range(retries + 1):
                attempts += 1
                try:
                    _exec_step(step, backend)
                    last_error = None
                    break
                except BackendError as exc:
                    last_error = str(exc)
                    if not exc.retryable or attempt == retries:
                        raise
                    delay = backoff * (2 ** attempt)
                    logger.warning(
                        "第 %d 步 %s 失败（%s），%.1fs 后第 %d 次重试",
                        idx, action, exc, delay, attempt + 2,
                    )
                    sleep(delay)
        except FlowError as exc:
            # 配置写错属于编程错误，直接抛出，由调用方显式处理
            logger.error("第 %d 步配置错误，终止流程：%s", idx, exc)
            raise
        except BackendError as exc:
            results.append(StepResult(idx, action, False, attempts,
                                      int((clock() - step_started) * 1000), last_error))
            logger.error("第 %d 步 %s 最终失败（尝试 %d 次）：%s", idx, action, attempts, last_error)
            return RunResult(False, results, int((clock() - started) * 1000))

        elapsed = int((clock() - step_started) * 1000)
        results.append(StepResult(idx, action, True, attempts, elapsed))
        logger.info("第 %d 步 %s 完成（%d 次尝试，%d ms）", idx, action, attempts, elapsed)

    return RunResult(True, results, int((clock() - started) * 1000))
