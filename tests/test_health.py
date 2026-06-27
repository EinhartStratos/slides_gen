"""健康检查接口测试"""
from __future__ import annotations


class TestHealthEndpoint:
    """GET /api/v1/health"""

    def test_health_returns_ok(self, client):
        """健康检查应返回 200 且 status=ok"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["status"] == "ok"
        assert data["database"] is True
        assert data["ftp"] is True
        assert data["ftp_mode"] == "mock_only"
        assert "mock_ftp_dir" in data

    def test_health_no_auth_required(self, client):
        """健康检查不需要 API Key"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
