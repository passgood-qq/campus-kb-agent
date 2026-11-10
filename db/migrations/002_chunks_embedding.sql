-- ============================================================
-- 第 2 周迁移：给 chunks 加向量列 + 建索引
-- 执行：psql -d <你的库> -f db/migrations/002_chunks_embedding.sql
-- ============================================================

-- pgvector 扩展（schema.sql 里是注释状态，这里正式启用）
CREATE EXTENSION IF NOT EXISTS vector;

-- 维度必须和 embedding 模型一致：bge-m3 是 1024 维
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- HNSW 索引：按余弦距离近邻检索
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- 便于按文档查片段
CREATE INDEX IF NOT EXISTS idx_chunks_doc_idx ON chunks (document_id, chunk_index);
