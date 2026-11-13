"""抓取公开中文知识库作为规模测试语料。

来源：Snailclimb/JavaGuide（Apache-2.0），中文后端知识库，与项目语料主题相近。
只取 Markdown 正文，图片与二进制一律跳过。

用法：
    python scripts/fetch_corpus.py --limit 120 --out corpus_extra
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "Snailclimb/JavaGuide"
BRANCH = "main"
UA = {"User-Agent": "campus-kb-agent/1.0 (educational use)"}
MAX_BYTES = 3 * 1024 * 1024     # 总大小上限，避免灌太多
MIN_CHARS = 400                 # 太短的文件没有检索价值


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def safe_name(path: str) -> str:
    name = path.replace("/", "__")
    name = re.sub(r"[^\w\u4e00-\u9fff.\-]+", "_", name)
    return name[:120]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--out", default="corpus_extra")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1] 读取仓库文件树 {REPO}@{BRANCH} ...")
    tree = get_json(
        f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
    )
    if "tree" not in tree:
        print("获取文件树失败:", tree)
        return 1

    paths = [
        t["path"] for t in tree["tree"]
        if t.get("type") == "blob"
        and t["path"].endswith(".md")
        and t.get("size", 0) > MIN_CHARS * 2
    ]
    print(f"    共 {len(paths)} 个 Markdown 文件")

    # 均匀抽样，覆盖面更广
    step = max(1, len(paths) // args.limit) if len(paths) > args.limit else 1
    picked = paths[::step][: args.limit]

    total_bytes = 0
    saved = 0
    for i, p in enumerate(picked, 1):
        if total_bytes > MAX_BYTES:
            print(f"    已达大小上限 {MAX_BYTES // 1024} KB，停止")
            break
        url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{urllib.parse.quote(p)}"
        try:
            text = get_text(url)
        except Exception as exc:  # 单个失败不影响整体
            print(f"    [{i}] 跳过 {p}: {type(exc).__name__}")
            continue
        if len(text) < MIN_CHARS:
            continue
        target = out_dir / safe_name(p)
        target.write_text(text, encoding="utf-8")
        total_bytes += len(text.encode("utf-8"))
        saved += 1
        if i % 20 == 0:
            print(f"    [{i}/{len(picked)}] 已保存 {saved}，累计 {total_bytes // 1024} KB")
        time.sleep(0.05)

    print(f"[2] 完成：{saved} 个文件，{total_bytes / 1024:.0f} KB -> {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
