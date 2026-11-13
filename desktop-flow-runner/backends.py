"""执行后端：把具体 GUI 库隔离开，核心逻辑因此可以脱离桌面做单元测试。

- PyAutoGUIBackend : 真机执行，用 pyautogui + pygetwindow
- MockBackend      : 测试用，记录调用、按预设失败，不碰屏幕
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger("backend")


class BackendError(Exception):
    """底层 GUI 操作失败。retryable 表示是否值得重试。"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class PyAutoGUIBackend:
    """真机后端。依赖：pyautogui、pygetwindow（Windows）。"""

    def __init__(self) -> None:
        try:
            import pyautogui  # noqa: F401
            import pygetwindow  # noqa: F401
        except ImportError as exc:  # 只在真机执行时才需要
            raise BackendError(
                "缺少依赖：pip install pyautogui pygetwindow", retryable=False
            ) from exc
        import pyautogui

        pyautogui.FAILSAFE = True   # 鼠标甩到左上角可紧急中断
        pyautogui.PAUSE = 0.2       # 每个动作后暂停，避免操作过快
        self._gui = pyautogui
        self._log = []

    # ------------------------------------------------------------------
    def find_window(self, titles, timeout: float) -> bool:
        """按标题候选列表匹配窗口。

        标题在不同语言/不同文件下会变（'记事本' vs 'Notepad'），
        所以支持传多个候选，任一命中即可。
        """
        import pygetwindow

        if isinstance(titles, str):
            titles = [titles]
        candidates = [t.lower() for t in titles if t]

        deadline = time.time() + timeout
        while time.time() < deadline:
            for w in pygetwindow.getAllWindows():
                title = (w.title or "").lower()
                if title and any(c in title for c in candidates):
                    self._active = w
                    return True
            time.sleep(0.3)

        # 找不到时把当前可见窗口打出来，便于排查（RPA 最常见的故障）
        visible = [t for t in pygetwindow.getAllTitles() if t.strip()][:15]
        log.warning("未找到窗口 %s，当前可见窗口：%s", titles, visible)
        raise BackendError(
            f"未找到窗口：{titles}（超时 {timeout}s）；可见窗口：{visible}", retryable=True
        )

    def focus_window(self) -> None:
        try:
            if getattr(self, "_active", None) is None:
                raise BackendError("尚未定位窗口", retryable=False)
            if self._active.isMinimized:
                self._active.restore()
            self._active.activate()
            time.sleep(0.3)
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"窗口激活失败：{exc}", retryable=True) from exc

    def click(self, x: int | None = None, y: int | None = None) -> None:
        self._gui.click(x, y)

    def type_text(self, text: str) -> None:
        self._gui.typewrite(text, interval=0.02)

    def press(self, key: str) -> None:
        self._gui.press(key)

    def screenshot(self, path: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._gui.screenshot(str(target))
        return str(target)


class MockBackend:
    """测试后端：按预设序列触发失败，并记录全部调用。"""

    def __init__(self, windows: list[str] | None = None,
                 fail_plan: dict[str, list[bool]] | None = None) -> None:
        self.windows = windows if windows is not None else ["记事本"]
        self.fail_plan = fail_plan or {}
        self.calls: list[tuple[str, tuple, dict]] = []
        self._active = None

    def _maybe_fail(self, name: str) -> None:
        plan = self.fail_plan.get(name)
        if plan:
            should_fail = plan.pop(0)
            if should_fail:
                raise BackendError(f"mock 失败：{name}", retryable=True)

    def find_window(self, titles, timeout: float) -> bool:
        self.calls.append(("find_window", (titles, timeout), {}))
        self._maybe_fail("find_window")
        if isinstance(titles, str):
            titles = [titles]
        if not any(any(t.lower() in w.lower() for t in titles) for w in self.windows):
            raise BackendError(f"未找到窗口：{titles}", retryable=True)
        self._active = titles
        return True

    def focus_window(self) -> None:
        self.calls.append(("focus_window", (), {}))
        self._maybe_fail("focus_window")

    def click(self, x: int | None = None, y: int | None = None) -> None:
        self.calls.append(("click", (x, y), {}))
        self._maybe_fail("click")

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", (text,), {}))
        self._maybe_fail("type_text")

    def press(self, key: str) -> None:
        self.calls.append(("press", (key,), {}))
        self._maybe_fail("press")

    def screenshot(self, path: str) -> str:
        self.calls.append(("screenshot", (path,), {}))
        self._maybe_fail("screenshot")
        return path
