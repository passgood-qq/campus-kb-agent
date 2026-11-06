-- 12周底座 D3 · 初始 schema
-- 三张表：documents / chunks / queries
-- 故意不建：query_sources、eval_cases、eval_runs（等第8周再建）

-- ① documents：文档元数据，一份 PDF 一行，不存正文
CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,   -- 文件内容哈希，重复上传自动去重
    source      TEXT,                     -- 来源（课件/教材/网页）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ② chunks：切分片段，检索的基本单位
-- embedding 列故意不建：等 D5 定好模型再加，避免维度不匹配重建表
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    UNIQUE (document_id, chunk_index)   -- 幂等：重新切分不产生重复
);

-- ③ queries：每次提问记录
-- 第8周所有数字（P95/错误率/成本/命中率）都从这张表算
-- status 给第9周用：ok / failed / degraded
CREATE TABLE IF NOT EXISTS queries (
    id               BIGSERIAL PRIMARY KEY,
    question         TEXT NOT NULL,
    answer           TEXT,
    model            TEXT,
    prompt_tokens     INT,
    completion_tokens INT,
    latency_ms       INT,
    cost             NUMERIC(10, 6),
    status           TEXT NOT NULL DEFAULT 'ok'
                     CHECK (status IN ('ok', 'failed', 'degraded')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_queries_created ON queries(created_at);
CREATE INDEX IF NOT EXISTS idx_queries_status ON queries(status);
