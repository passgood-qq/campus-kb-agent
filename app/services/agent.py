"""Agent 循环：模型自己决定调用哪些工具、看结果、再决定是否继续。

终止条件（三者取先到）：
  1. 模型不再发起工具调用（给出最终答案）
  2. 达到 max_steps
  3. 工具连续失败

超步数时强制收口：去掉 tools 再调一次，逼模型基于已有结果作答。
"""
from __future__ import annotations

import json
import logging
import time
from collections import namedtuple

from app.config import get_settings
from app.services import llm, tools

log = logging.getLogger("app.agent")

AgentResult = namedtuple(
    "AgentResult", "answer sources tool_calls token_in token_out latency_ms steps"
)

SYSTEM_PROMPT = """你是一个课程资料助手，可以调用工具来查找资料。

规则：
1. 需要查资料时调用 search_corpus；关键词不理想时可以换个说法再查一次。
2. 只能依据工具返回的资料作答。资料里没有的内容，直接说「资料里没有找到相关内容」，不要编造。
3. 引用资料时在句末标注编号，例如 [1]、[2]，编号对应检索结果顺序。
4. 最多进行 {max_steps} 轮工具调用，之后必须直接给出最终答案。
5. 回答用中文，简洁准确。"""


def _collect_sources(results: list[dict], index: dict[int, int]) -> list[dict]:
    """把各轮检索到的片段去重、编号，用于回填出处。"""
    out = []
    for item in results:
        cid = item.get("chunk_id")
        if cid is None:
            continue
        if cid not in index:
            index[cid] = len(index) + 1
        out.append(
            {
                "index": index[cid],
                "title": item.get("title", ""),
                "page_no": None,
                "chunk_index": item.get("chunk_index", 0),
                "score": item.get("score", 0.0),
                "retrieved_by": item.get("retrieved_by", ""),
                "snippet": (item.get("content") or "")[:120],
            }
        )
    return out


def run(question: str, max_steps: int = 3) -> AgentResult:
    s = get_settings()
    started = time.perf_counter()

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(max_steps=max_steps)},
        {"role": "user", "content": question},
    ]

    token_in = token_out = 0
    steps = 0
    calls: list[dict] = []
    source_index: dict[int, int] = {}
    sources: dict[int, dict] = {}
    consecutive_failures = 0

    while steps < max_steps:
        steps += 1
        try:
            msg, tin, tout, _ = llm.chat_messages(messages, tool_schemas=tools.TOOL_SCHEMAS)
        except llm.LLMUnavailable:
            raise
        except llm.LLMError:
            raise
        token_in += tin
        token_out += tout

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            answer = (msg.content or "").strip()
            latency = int((time.perf_counter() - started) * 1000)
            log.info("agent 完成 steps=%d tools=%d token=%d/%d", steps, len(calls), token_in, token_out)
            return AgentResult(
                answer,
                [sources[k] for k in sorted(sources)],
                calls, token_in, token_out, latency, steps,
            )

        # 把 assistant 的工具调用意图写回对话，再逐个执行
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc.function.name
            text, raw = tools.dispatch(name, tc.function.arguments)
            if raw is None:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
                for src in _collect_sources(raw.get("results", []), source_index):
                    sources[src["index"]] = src
            calls.append({"name": name, "arguments": json.loads(tc.function.arguments or "{}")})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            log.info("agent 调用工具 %s -> %d 字", name, len(text))

        if consecutive_failures >= 2:
            log.error("工具连续失败 %d 次，提前收口", consecutive_failures)
            break

    # 步数用尽或工具连续失败：去掉工具强制收口
    messages.append({"role": "user", "content": "请基于以上信息直接给出最终答案，不要再调用工具。"})
    msg, tin, tout, _ = llm.chat_messages(messages, tool_schemas=None)
    token_in += tin
    token_out += tout
    latency = int((time.perf_counter() - started) * 1000)
    answer = (msg.content or "").strip()
    log.info("agent 强制收口 steps=%d token=%d/%d", steps, token_in, token_out)
    return AgentResult(
        answer, [sources[k] for k in sorted(sources)], calls, token_in, token_out, latency, steps
    )
