"""D5：读文档 → 调模型 → 存库
端到端最小闭环：
  1. 读本地文档
  2. 存到 documents 表
  3. 调 LLM 对文档提问
  4. 存到 queries 表
"""
import os
import hashlib
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2

load_dotenv()

# 初始化
llm = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=os.getenv("LLM_BASE_URL"))
db = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = db.cursor()

# 1. 读文档
doc_path = "data/docs/what_is_rag.txt"
with open(doc_path, "r", encoding="utf-8") as f:
    content = f.read()

content_hash = hashlib.md5(content.encode()).hexdigest()
print(f"📄 文档长度：{len(content)} 字，哈希：{content_hash[:8]}...")

# 2. 存到 documents 表
cur.execute(
    """INSERT INTO documents (title, source_path, file_type, content_hash, status)
       VALUES (%s, %s, %s, %s, 'indexed')
       ON CONFLICT (content_hash) DO UPDATE SET status = 'indexed'
       RETURNING id""",
    ("什么是RAG", doc_path, "txt", content_hash)
)
doc_id = cur.fetchone()[0]
print(f"📚 文档已存入 documents 表，id={doc_id}")

# 3. 调 LLM 对文档提问
question = "用三句话总结这篇文档的核心观点"
prompt = f"请根据以下文档内容回答问题：\n\n文档：\n{content}\n\n问题：{question}"

resp = llm.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3
)
answer = resp.choices[0].message.content
latency = 0  # D5 先不计时，D8 再补
token_in = resp.usage.prompt_tokens
token_out = resp.usage.completion_tokens

print(f"🤖 AI 回答：{answer}")

# 4. 存到 queries 表
cur.execute(
    """INSERT INTO queries (question, answer, token_in, token_out, status)
       VALUES (%s, %s, %s, %s, 'ok')""",
    (question, answer, token_in, token_out)
)
db.commit()
print(f"💾 已存入 queries 表，token_in={token_in}, token_out={token_out}")

# 清理
cur.close()
db.close()
print("\n✅ D5 跑通：读文档 → 调模型 → 存库，全链路完成")
