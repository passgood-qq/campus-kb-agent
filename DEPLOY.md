# 部署指南

两种方式，按用途选：

| 用途 | 方案 | 链接稳定性 | 成本 |
|---|---|---|---|
| 写进简历、给面试官点 | **Render + Neon** | 固定，但闲置会休眠 | 免费 |
| 录屏、发给同学试用 | **Cloudflare Quick Tunnel** | 电脑关机即断，每次重启变 | 免费 |

---

## 一、Render + Neon（写进简历用）

### 前提：语料要进仓库

语料放在 `corpus/`，随仓库一起部署。`data/` 是本地 PostgreSQL 数据目录，不进仓库。

### 步骤

**1. 建 Neon 数据库**

1. 注册 <https://neon.tech>（免费）
2. 新建 project，记下连接串，形如：
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. 在 Neon 的 SQL Editor 里依次执行：
   ```
   db/schema.sql
   db/migrations/002_chunks_embedding.sql
   ```

**2. 在 Render 建 Web Service**

1. 注册 <https://render.com>，New → Web Service
2. 连接 GitHub 仓库 `campus-kb-agent`
3. Runtime 选 **Docker**（仓库根目录已有 `Dockerfile`）
4. Plan 选 **Free**
5. Health Check Path 填 `/healthz`
6. 在 Environment 里填以下变量（**不要写进仓库**）：

   | Key | 值 |
   |---|---|
   | `DATABASE_URL` | Neon 的连接串 |
   | `LLM_API_KEY` | DeepSeek 的 key |
   | `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
   | `LLM_MODEL` | 你的模型名 |
   | `EMBEDDING_API_KEY` | 硅基流动的 key |
   | `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` |
   | `EMBEDDING_MODEL` | `BAAI/bge-m3` |
   | `LOG_LEVEL` | `INFO` |

7. Deploy，等构建完成

**3. 灌库（只做一次）**

Render 免费实例没有持久 Shell，最简单的方式是在**本地**指向 Neon 灌库：

```powershell
cd F:\dev\12week-base
$env:DATABASE_URL="<Neon 连接串>"
python scripts\ingest.py --dir corpus
```

灌完打开 `https://<你的服务>.onrender.com/healthz`，应该看到
`{"status":"ok","db":"up","documents":6,"chunks":32}`。

### 关于冷启动

免费实例 **15 分钟无访问会休眠，再次访问需等约 1 分钟**。

这不是缺陷，是成本权衡。建议在 README 顶部写一句：

> 免费实例，首次访问需等待约 1 分钟冷启动。

面试官看到这句会理解，而且会觉得你清楚自己在花什么钱。

---

## 二、Cloudflare Quick Tunnel（演示用）

**无需账号。** 双击 `tunnel.cmd`，首次会自动下载 cloudflared（约 40MB）。

等它打印出类似下面的地址：

```
https://random-words-here.trycloudflare.com
```

这个地址就是公网可访问的。

注意：

- 电脑关机 / 关掉这个窗口 → 链接失效
- 每次重新运行，链接都会变
- **不要把这个链接写进简历**

---

## 三、检查清单（上线后逐条过）

- [ ] `/healthz` 返回 `db: "up"` 且 `documents` 不为 0
- [ ] `/` 打开能看到问答页
- [ ] 问一个课程问题，能返回答案 + 出处
- [ ] `/docs` 能打开（若白屏，是 CDN 问题，不影响使用）
- [ ] 仓库里搜不到任何 `sk-` 开头的字符串
- [ ] README 里补上线上链接和冷启动说明
