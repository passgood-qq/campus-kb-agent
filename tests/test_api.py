"""接口测试。不调真实 LLM —— 只测契约、校验和健康检查。"""
from fastapi.testclient import TestClient

from app.main import app


def test_healthz():
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ask_rejects_empty_question():
    with TestClient(app) as client:
        resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422


def test_ask_rejects_missing_field():
    with TestClient(app) as client:
        resp = client.post("/ask", json={})
    assert resp.status_code == 422
