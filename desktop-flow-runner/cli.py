"""命令行入口：python -m cli run examples/notepad_flow.json

选项：
    --dry-run   只做静态校验，不真的操作桌面
    --report    把结构化报告写到指定 JSON 文件
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from backends import BackendError, MockBackend, PyAutoGUIBackend
from runner import FlowError, run_flow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cli")


def validate(flow: dict) -> list[str]:
    """静态校验：不碰桌面，先把配置问题挑出来。"""
    problems: list[str] = []
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["steps 必须是非空数组"]
    known = {"focus_window", "click", "type_text", "press", "screenshot", "wait"}
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            problems.append(f"第 {i} 步不是对象")
            continue
        action = s.get("action")
        if action not in known:
            problems.append(f"第 {i} 步动作未知：{action}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "check"])
    ap.add_argument("flow")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report")
    args = ap.parse_args()

    path = Path(args.flow)
    if not path.exists():
        print(f"流程文件不存在：{path}", file=sys.stderr)
        return 2
    flow = json.loads(path.read_text(encoding="utf-8"))

    problems = validate(flow)
    if problems:
        print("配置有误：")
        for p in problems:
            print("  -", p)
        return 2
    if args.command == "check" or args.dry_run:
        print(f"配置校验通过：{len(flow['steps'])} 个步骤")
        return 0

    try:
        backend = PyAutoGUIBackend()
    except BackendError as exc:
        print(f"无法初始化执行后端：{exc}", file=sys.stderr)
        return 3

    try:
        result = run_flow(flow, backend)
    except FlowError as exc:
        print(f"流程错误：{exc}", file=sys.stderr)
        return 2

    payload = {
        "ok": result.ok,
        "elapsed_ms": result.elapsed_ms,
        "steps": [s.__dict__ for s in result.steps],
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)  # 目录不存在时自动创建
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"报告已写入：{args.report}")

    if not result.ok:
        failed = result.failed_step
        print(f"流程失败于第 {failed.index} 步（{failed.action}）：{failed.error}", file=sys.stderr)
        return 1
    print(f"流程执行成功：{len(result.steps)} 步，耗时 {result.elapsed_ms} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
