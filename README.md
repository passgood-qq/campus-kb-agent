# campus-kb-agent

> 把散在群文件和网盘里的课程资料，变成一个能直接问的助手。

**状态**：开发中（WIP）· 2027 届春招项目 · 预计 2027-02 完成

---

## 这是什么

找一份课程资料，通常要翻三五个群文件、几十条网盘链接，还不一定找得到。

本项目把课程资料（PDF / PPT / Markdown）统一收进来，做成可以自然语言提问的知识库：
问一句"第三章讲了什么"，直接给出答案，并标注出自哪份文档。

**目标用户**：同专业的在读学生（也包括我自己）。

---

## 快速开始

### 方式 A：本地开发（原生 PostgreSQL）

需要 PostgreSQL 16+。

```bash
# 1. 建库（或在已有库里直接建表）
createdb campus_kb

# 2. 建表
psql -d campus_kb -f db/schema.sql

# 3. 配置环境变量
cp .env.example .env      # 填入 LLM_API_KEY，并把 DATABASE_URL 指向你的库

# 4. 装依赖
pip install -r requirements.txt

# 5. 跑一次端到端管线：读文档 → 调模型 → 存库
python scripts/doc_pipeline.py
```

### 方式 B：Docker（部署 / CI 用）

本地开发用方式 A 就够了；这个方式主要是给部署和以后接 CI 准备的。

```bash
cp .env.example .env
docker compose up -d
```

> Docker 模式下数据库名是 `campus_kb`，记得把 `.env` 里的 `DATABASE_URL`
> 改成 `postgresql://postgres:postgres@localhost:5432/campus_kb`。

---

## 项目结构

```
├── db/
│   └── schema.sql          # 表结构：documents / chunks / queries
├── scripts/
│   ├── test_llm.py         # D4：验证 LLM 通路
│   └── doc_pipeline.py     # D5：读文档 → 调模型 → 存库
├── docker-compose.yml      # 部署用（本地开发可不启）
├── .env.example
└── README.md
```

---

## 数据与隐私

- **语料**：公开教材与课程课件
- **评测集**：人工构造 50 条，含 20% 无答案负样本（第 8 周补齐）

> 本项目为个人学习项目，不含真实用户数据。`.env` 存有 API Key，已被 `.gitignore` 排除。

---

## 进度

- [x] D1 仓库、README、首次提交
- [x] D3 PostgreSQL 环境 + 初始 schema（3 张表）
- [x] D4 打通 LLM 调用（DeepSeek）
- [x] D5 端到端管线：读文档 → 调模型 → 存库（documents / queries 已落数据）
- [ ] 文档切分 + 向量检索（`chunks` 表目前建了但还没用上）
- [ ] FastAPI 服务化，暴露 `/ask` 接口
- [ ] 评测集 50 条 + 评测脚本
- [ ] 部署到公网

---

## 已知问题

- **整篇文档直接塞进 prompt，没有切分**：文档一长就会超出上下文窗口，`chunks` 表目前是空的。
  下一步（D6 之后）要做的是切分 + embedding 检索。
- **没有日志和异常处理**：目前全靠 `print`，外部调用失败会直接把脚本打断。
- **`chunks` 表暂未启用向量列**：向量维度要等 embedding 模型定下来才能建，见 `db/schema.sql` 注释。

---

## 做了什么取舍

- **本地开发用原生 PostgreSQL，不用 Docker**：启动快、少一层抽象，排查问题直接看日志。
  Docker 只用于部署和 CI，两者并存不冲突。
- **先跑通端到端，再上向量检索**：D5 刻意把整篇文档塞进 prompt，
  为的是先验证"读文档 → 调用 → 落库"这条链路，再替换成 RAG。避免一上来就堆组件。
- **只用 3 张表**：`query_sources` / `eval_cases` / `eval_runs` 等到第 8 周再建，
  早期多建的表大概率要改。

---

## License

MIT
