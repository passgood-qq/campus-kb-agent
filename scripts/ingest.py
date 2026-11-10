"""灌库脚本：读 data/docs 下的 txt/md → 切分 → 向量化 → 写进 chunks。

用法（项目根目录）：
    python scripts/ingest.py
    python scripts/ingest.py --dir data/docs --reset

设计取舍：
  - 只支持 txt/md。PDF 要引入 pypdf 并处理页码，留到有真实材料时再做。
  - 按空行分段再累积，长段落硬切；不做语义切分（当前语料量不值得）。
  - 按 content_hash 去重，重复跑不会产生重复文档。
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path

# 直接运行脚本时（python scripts/ingest.py），把项目根目录加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from app.config import get_settings
from app.services import db, embeddings

load_dotenv()

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("ingest")

SUPPORTED = {".txt", ".md"}


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """按空行分段累积成块；单段超过 size 则硬切，块间保留 overlap 字符的重叠。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(p) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            step = max(size - overlap, 1)
            for start in range(0, len(p), step):
                piece = p[start : start + size]
                if piece:
                    chunks.append(piece)
            continue

        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= size:
            buf = f"{buf}\n{p}"
        else:
            chunks.append(buf)
            buf = p

    if buf:
        chunks.append(buf)

    # 相邻块加一点重叠，避免答案正好被切断
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev[-overlap:]
            merged.append(f"{tail}\n{cur}" if tail else cur)
        chunks = merged

    return chunks


def ingest_dir(doc_dir: Path) -> tuple[int, int]:
    s = get_settings()
    files = sorted(p for p in doc_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not files:
        log.warning("目录里没有可处理的文件：%s", doc_dir)
        return 0, 0

    total_docs = total_chunks = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            log.warning("跳过空文件：%s", f.name)
            continue

        content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        doc_id = db.upsert_document(
            title=f.stem,
            source_path=str(f),
            file_type=f.suffix.lstrip(".").lower(),
            content_hash=content_hash,
        )

        pieces = split_text(text, s.chunk_size, s.chunk_overlap)
        vectors = embeddings.embed_batch(pieces)
        rows = [
            {
                "chunk_index": i,
                "content": piece,
                "page_no": None,
                "token_count": None,
                "embedding": embeddings.to_pgvector(vec),
            }
            for i, (piece, vec) in enumerate(zip(pieces, vectors))
        ]
        n = db.replace_chunks(doc_id, rows)
        log.info("已处理 %s -> doc_id=%s, %d 个片段", f.name, doc_id, n)
        total_docs += 1
        total_chunks += n

    return total_docs, total_chunks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/docs", help="语料目录")
    args = parser.parse_args()

    doc_dir = Path(args.dir)
    if not doc_dir.exists():
        log.error("目录不存在：%s", doc_dir.resolve())
        return 2

    try:
        docs, chunks = ingest_dir(doc_dir)
    except embeddings.EmbeddingError as exc:
        log.error("向量化失败：%s", exc)
        return 4
    except RuntimeError as exc:
        log.error("数据库不可用：%s", exc)
        return 3

    stats = db.counts()
    log.info("完成：本次处理 %d 份文档 / %d 个片段", docs, chunks)
    log.info("库内合计：documents=%d chunks=%d 已向量化=%d",
             stats["documents"], stats["chunks"], stats["embedded"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
