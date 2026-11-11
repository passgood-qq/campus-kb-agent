# 部署到阿里云函数计算 FC（Web 函数）

> 用途：国内可访问的常驻服务。免费额度：新用户每月 15 万 CU，连续 3 个月。
> 前置：阿里云账号 + **实名认证**。

---

## 0. 为什么是 FC

- 国内可直连，面试官打开快
- 免费额度明确，不需要绑卡
- 支持 FastAPI 这类 Web 框架

> 注意：本项目部署包里的依赖是 **cp310（Python 3.10）** 的 wheel，
> **运行环境必须选 Python 3.10**，选 3.12 会 ABI 不兼容。

---

## 1. 领免费额度

打开 <https://free.aliyun.com> → 搜索「函数计算 FC」→ 领取（每月 15 万 CU，3 个月）。

## 2. 开通函数计算

<https://fc.console.aliyun.com> → 首次进入按向导开通（选择地域，建议**华东1-杭州**）。

## 3. 创建函数

函数计算 → 函数 → **创建函数** → 选择 **Web 函数**

| 配置项 | 填什么 |
|---|---|
| 函数名称 | `campus-kb-agent` |
| 运行环境 | **Python 3.10**（必须 3.10） |
| 代码上传方式 | **ZIP 包上传** → 选 `F:\dev\fc-campus-kb.zip` |
| 启动命令 | `python -m uvicorn app.main:app --host 0.0.0.0 --port 9000` |
| 监听端口 | `9000` |
| 规格 | 内存 512 MB 起，够用 |
| 超时时间 | **120 秒**（默认 60 可能不够：冷启动 + 模型调用） |
| 环境变量 | 见下 |

**环境变量**（在配置页逐个添加）：

| Key | 值 |
|---|---|
| `DATABASE_URL` | Neon 连接串（`F:\dev\neon-db-url.txt`） |
| `LLM_API_KEY` | DeepSeek key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 你的模型名 |
| `EMBEDDING_API_KEY` | 硅基流动 key |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `LOG_LEVEL` | `INFO` |

## 4. 配置 HTTP 触发器

创建函数后在「触发器管理」里添加 **HTTP 触发器**：

| 配置项 | 填什么 |
|---|---|
| 请求方法 | `GET, POST`（要支持 OPTIONS 的话全选） |
| 认证方式 | **无需认证**（匿名调用） |

保存后 FC 会给你一个默认域名，形如：

```
https://campus-kb-agent-xxxx.cn-hangzhou.fcapp.run
```

## 5. 验证

浏览器打开：

```
https://<你的域名>/healthz
```

期望：

```json
{"status":"ok","db":"up","llm":"closed","documents":6,"chunks":32}
```

然后打开 `/` 问一个课程问题，看能否返回答案 + 出处。

---

## 常见问题

**Q：`/healthz` 返回 `db: "down"`**
检查 `DATABASE_URL` 是否包含 `?sslmode=require`。Neon 必须带 SSL。

**Q：函数报 `ModuleNotFoundError`**
部署包里的依赖是平铺在根目录的，检查是否上传了完整的 zip（18.6 MB），
且没有多套一层文件夹。

**Q：请求超时**
把函数超时时间调到 120 秒；首次冷启动会慢。

**Q：3 个月后怎么办**
换「先不部署」或买轻量应用服务器。免费额度到期前控制台会有提醒。

---

## 打部署包（本地重建）

```powershell
python -m pip install --quiet --target F:\dev\fc-pkg `
    --platform manylinux2014_x86_64 --python-version 3.10 --only-binary=:all: `
    -r F:\dev\12week-base\requirements.txt

# 删除运行时不需要的：pygments / _pytest / pytest / bin
# 依赖平铺到根目录后再把 app/ 拷进去，然后压缩
```
