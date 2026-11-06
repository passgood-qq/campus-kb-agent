# 12 周底座

2027 届春招底座项目：FastAPI + PostgreSQL + LLM RAG 问答系统。

## 快速启动

```bash
# 1. 启动 PostgreSQL（本地免安装版）
F:\dev\pg17\pgsql\bin\pg_ctl -D F:\dev\12week-base\data -l F:\dev\12week-base\pg.log start

# 2. 建表（首次）
F:\dev\pg17\pgsql\bin\psql -U postgres -f F:\dev\12week-base\db\schema.sql

# 3. 连接
F:\dev\pg17\pgsql\bin\psql -U postgres
```

## 项目结构

```
├── db/
│   └── schema.sql      # 初始表结构（documents / chunks / queries）
├── data/               # PostgreSQL 数据目录（不提交）
└── README.md
```

## 当前进度

- [x] D3：PostgreSQL 环境 + 初始 schema
