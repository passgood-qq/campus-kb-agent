# desktop-flow-runner

> 把一段桌面操作写成 JSON，按步骤执行、失败重试、留下可追溯的执行报告。

## 为什么做这个

桌面操作（打开某个程序、点几个按钮、把结果截图留证）重复且容易漏步骤。
这个小工具把流程**脚本化**：配置怎么写就怎么跑，每步都有重试与日志，
失败时能直接看出卡在第几步、什么原因。

## 快速开始

```bash
pip install -r requirements.txt

# 1. 静态校验（不碰桌面）
python cli.py check examples/notepad_flow.json

# 2. 真机执行（会操作鼠标键盘，建议先只开记事本）
python cli.py run examples/notepad_flow.json --report output/report.json
```

> 执行期间把鼠标甩到**屏幕左上角**可以紧急中断（pyautogui FAILSAFE）。

## 流程配置

```json
{
  "retries": 2,
  "backoff": 0.5,
  "steps": [
    { "action": "focus_window", "title": "记事本", "timeout": 8, "retries": 3 },
    { "action": "type_text", "text": "hello" },
    { "action": "screenshot", "path": "output/step1.png" }
  ]
}
```

支持的步骤：

| action | 说明 | 必填字段 |
|---|---|---|
| `focus_window` | 按标题定位窗口并激活（超时轮询） | `title` |
| `type_text` | 键入一段文本 | `text` |
| `press` | 按下单个按键（如 enter、tab） | `key` |
| `click` | 点击指定坐标或当前位置 | — |
| `screenshot` | 截图落盘，作为执行证据 | `path` |
| `wait` | 等待固定秒数 | `seconds` |

## 设计取舍

- **后端可替换**：`PyAutoGUIBackend` 真机执行，`MockBackend` 用于测试。
  核心流程逻辑不依赖 GUI，所以 8 个单测在无桌面环境（含 CI）也能跑。
- **区分「可重试」与「不可重试」错误**：窗口没找到、点击失败值得重试；
  配置写错了（未知动作、缺字段）立刻失败，不做无意义的等待。
- **每步独立重试 + 指数退避**：一步失败不会直接中断整条流程，
  重试次数可全局配置也可单步覆盖。
- **结构化报告**：每步输出尝试次数、耗时、错误信息，写入 JSON。
- **FAILSAFE**：pyautogui 的紧急中断机制保留，避免脚本失控。

## 测试

```bash
python -m pytest tests -q
```

覆盖：正常执行、重试后成功、重试耗尽、窗口找不到、未知动作、
空步骤、不可重试错误立即停止。

## 已知限制

- 只支持 Windows（依赖 pygetwindow）
- 中文输入依赖输入法状态，示例流程用英文文本规避
- 未做图像识别定位（后续可接模板匹配或 OCR）
