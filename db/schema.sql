-- ============================================================
-- campus-kb-agent 数据库 schema（D3）
-- 只建 3 张表：documents / chunks / queries
-- 原则：早期少建。schema 会变，12 周里多建的表有 80% 会被改掉。
-- ============================================================

-- 等 D5 需要向量检索时再装 pgvector，然后取消下面这行注释
-- CREATE EXTENSION IF NOT EXISTS vector;

-- --------------------------------------------------------------
-- 1. documents：文档元数据
--    一份 PDF / PPT / MD 一行。不存正文，正文在 chunks。
-- ------------------------------------------------------------
CREATE TABLE documents (
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT        NOT NULL,
    source_path  TEXT        NOT NULL,                  -- 原始文件路径或 URL
    file_type    TEXT        NOT NULL,                  -- pdf / pptx / md
    page_count   INTEGER,
    content_hash TEXT        NOT NULL UNIQUE,           -- 文件内容哈希：同一份文件重复上传只留一份
    status       TEXT        NOT NULL DEFAULT 'pending', -- pending / parsed / indexed / failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_status ON documents (status);

-- --------------------------------------------------------------
-- 2. chunks：切分后的片段（检索的基本单位）
--    注意：embedding 列先不建。
--    向量维度必须和 embedding 模型一致，而模型还没定（D4 才定）。
--    定好模型后在 D5 执行：
--      ALTER TABLE chunks ADD COLUMN embedding vector(1024);
--    维度填错了要重建整张表，所以别提前猜。
-- ------------------------------------------------------------
CREATE TABLE chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,                       -- 该文档内的第几段，从 0 开始
    content     TEXT    NOT NULL,                       -- 片段正文
    page_no     INTEGER,                                -- 来源页码，用于回答时标注出处
    token_count INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)                   -- 防止重复切分产生重复片段
);

CREATE INDEX idx_chunks_document ON chunks (document_id);

-- --------------------------------------------------------------
-- 3. queries：每次提问的记录（可观测性的地基）
--    第 8 周的 P95 / 错误率 / 单次成本全部从这张表算出来。
--    现在就开始记，比事后补埋点省事一百倍。
-- ------------------------------------------------------------
CREATE TABLE queries (
    id         BIGSERIAL PRIMARY KEY,
    question   TEXT        NOT NULL,
    answer     TEXT,
    latency_ms INTEGER,
    token_in   INTEGER,
    token_out  INTEGER,
    cost_cents NUMERIC(10, 4),                          -- 单次成本，单位：分
    status     TEXT        NOT NULL DEFAULT 'ok',       -- ok / failed / degraded
    trace_id   TEXT,                                    -- 串起一次请求的所有日志
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_queries_created ON queries (created_at DESC);

-- ============================================================
-- 后续再建（别现在建）：
--   query_sources  → 第 8 周：答案引用了哪些 chunk（引用溯源）
--   eval_cases     → 第 8 周：评测题 + 标准答案 + 分类
--   eval_runs      → 第 8 周：每次评测的结果，用于回归对比
-- ============================================================
