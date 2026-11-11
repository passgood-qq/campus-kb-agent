FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 依赖单独一层，改代码不会触发重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY corpus ./corpus
COPY eval ./eval

EXPOSE 8000

# Render 会注入 $PORT，本地没这个变量时回退到 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
