# campus-kb-agent

> 把散在群文件和网盘里的课程资料，变成一个能直接问的助手。

[![CI](https://github.com/passgood-qq/campus-kb-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/passgood-qq/campus-kb-agent/actions/workflows/ci.yml)

**状态**：开发中（WIP）· 2027 届春招项目

![首页截图](docs/screenshot.png)

---

## 这是什么

找一份课程资料，通常要翻三五个群文件、几十条网盘链接，还不一定找得到。

本项目把课程资料统一收进来，做成可以用自然语言提问的知识库：
问一句"第三章讲了什么"，直接给出答案，并记录每次调用的耗时与成本。

**目标用户**：同专业的在读学生（也包括我自己）。

---

## 快速开始

### 1. 准备数据库

需要 PostgreSQL 16+ **并安装 pgvector 扩展**。

```bash
createdb campus_kb
psql -d campus_kb -f db/schema.sql
psql -d campus_kb -f db/migrations/002_chunks_embedding.sql
```

### 2. 配置并安装依赖

```bash
cp .env.example .env          # 填 LLM / Embedding 的 API Key，并让 DATABASE_URL 指向你的库
pip install -r requirements.txt
```

### 3. 灌库（切分 + 向量化）

```bash
python scripts/ingest.py      # 读 data/docs 下的 txt/md → 切分 → embedding → 写进 chunks
```

### 4. 启动服务

```bash
python -m uvicorn app.main:app --port 8000
```

- 交互页面：<http://127.0.0.1:8000/>
- 接口文档：<http://127.0.0.1:8000/docs>

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 存活探针，返回服务与数据库状态 |
| `POST` | `/ask` | 传入问题，返回答案 + 耗时 + token + 记录 id |
| `GET` | `/docs` | Swagger 调试界面 |

`POST /ask` 响应示例：

```json
{
  "answer": "RAG（检索增强生成）是一种…… [1]",
  "sources": [
    {
      "index": 1,
      "title": "what_is_rag",
      "page_no": null,
      "chunk_index": 0,
      "score": 0.6455,
      "snippet": "什么是 RAG？RAG（检索增强生成）是一种……"
    }
  ],
  "latency_ms": 8381,
  "token_in": 358,
  "token_out": 509,
  "query_id": 8
}
```

> `query_id` 是故意返回的：接口成功不等于数据落库成功，能对账才算真的通了。

---

## 项目结构

```
├── app/
│   ├── main.py            # 入口、lifespan、首页、Swagger
│   ├── config.py          # pydantic-settings 读 .env
│   ├── schemas.py         # 请求/响应模型
│   ├── api/routes.py      # /ask、/healthz
│   └── services/
│       ├── llm.py         # LLM 调用封装，异常统一成 LLMError
│       └── db.py          # 连接池（懒加载）、queries 落库
├── scripts/
│   ├── test_llm.py        # 验证 LLM 通路
│   └── doc_pipeline.py    # 读文档 → 调模型 → 存库
├── tests/test_api.py      # 4 个接口测试
├── db/schema.sql          # documents / chunks / queries
├── docker-compose.yml     # 部署 / CI 用
└── .env.example
```

---

## 用户验证

手动访谈（样本很小，只作方向参考）：

| 对象 | 反馈 | 解读 |
|---|---|---|
| 同学 A | “不会用”，未说明原因 | 可能是非目标用户；访谈时也还没有可交互界面，只能凭描述想象 |
| 同学 B | “会用”，且在被问「要文件还是要解答」时明确选择**要解答** | 需求成立，且产品形态应是**带出处的回答**，而不是文件搜索器 |

**下一步**：让 1–2 个真实用户实际用一次，观察他们会问什么、是否追问、会不会第二次回来用。
口头上的“会用”不等于行为上的“会用”。

---

## 数据与隐私

- **语料**：公开教材与课程课件
- **评测集**：人工构造 50 条，含 20% 无答案负样本（第 8 周补齐）

> 本项目为个人学习项目，不含真实用户数据。`.env` 存有 API Key，已被 `.gitignore` 排除。

---

## 进度

- [x] D1 仓库、README、首次提交
- [x] D3 PostgreSQL + 初始 schema（3 张表）
- [x] D4 打通 LLM 调用（DeepSeek）
- [x] D5 端到端管线：读文档 → 调模型 → 存库
- [x] D6 日志与异常处理（退出码分级、超时重试）
- [x] 第 1 周 FastAPI 服务化：`/ask`、`/healthz`、首页、4 个测试
- [x] 第 2 周 文档切分 + 向量检索：pgvector 0.8.7 + HNSW，答案带出处
- [ ] 评测集 50 条 + 评测脚本
- [ ] 部署到公网

---

## 已知问题

- **整篇文档直接塞进 prompt，没有切分**：文档一长就超出上下文窗口，`chunks` 表目前是空的。
  下一步要做切分 + embedding 检索。
- **`chunks` 表暂未启用向量列**：向量维度要等 embedding 模型定下来才能建，见 `db/schema.sql` 注释。
- **还没有鉴权和限流**：当前只用于本地开发，未做公网防护。

---

## 做了什么取舍

- **本地开发用原生 PostgreSQL，不用 Docker**：启动快、少一层抽象，排查问题直接看日志。
  Docker 只用于部署和 CI。
- **先跑通端到端，再上向量检索**：先验证"读文档 → 调用 → 落库"这条链路，再替换成 RAG，避免一上来就堆组件。
- **只用 3 张表**：`query_sources` / `eval_cases` / `eval_runs` 等到第 8 周再建。
- **首页不使用任何外部 CDN**：国内网络下拉不到 Swagger 的静态资源会白屏，
  所以首页写成零依赖的纯 HTML，Swagger 的资源也换成了国内 CDN。
- **不用 `uvicorn[standard]`**：它的依赖 `pyyaml` 在 Python 3.15 下没有预编译 wheel，
  会退化成源码编译并要求 MSVC Build Tools。基础版 uvicorn 足够本地开发。

---

## License

MIT
