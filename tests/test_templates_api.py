"""模板相关接口测试"""
from __future__ import annotations

import io


class TestListTemplates:
    """GET /api/v1/templates"""

    def test_list_without_api_key_returns_builtin(self, client):
        """不带 API Key 应只返回公共模板"""
        resp = client.get("/api/v1/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert isinstance(body["data"], list)
        # lifespan 中已导入默认模板，至少有 1 个
        assert len(body["data"]) >= 1
        for item in body["data"]:
            assert item["is_builtin"] is True

    def test_list_with_api_key_returns_builtin_and_private(self, client, auth_headers):
        """带 API Key 应返回公共模板 + 私有模板"""
        resp = client.get("/api/v1/templates", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 1


class TestGetTemplate:
    """GET /api/v1/templates/{template_id}"""

    def test_get_existing_template(self, client):
        """查询存在的模板应返回详情"""
        listing = client.get("/api/v1/templates").json()["data"]
        template_id = listing[0]["template_id"]
        resp = client.get(f"/api/v1/templates/{template_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["template_id"] == template_id
        assert "source_ftp_path" in data

    def test_get_nonexistent_template_returns_404(self, client):
        """查询不存在的模板应返回 404"""
        resp = client.get("/api/v1/templates/tpl_nonexistent_000")
        assert resp.status_code == 404


class TestImportBuiltinTemplate:
    """POST /api/v1/templates/import-builtin"""

    def test_import_builtin_without_file(self, client):
        """不传文件时应复用默认模板"""
        resp = client.post("/api/v1/templates/import-builtin")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "template_id" in data
        assert "template_name" in data
        assert data["slide_count"] >= 0

    def test_import_builtin_with_file(self, client):
        """上传文件应导入为公共模板"""
        pptx_bytes = b"PK\x03\x04" + b"\x00" * 128
        resp = client.post(
            "/api/v1/templates/import-builtin",
            files={"template_file": ("test.pptx", io.BytesIO(pptx_bytes), "application/octet-stream")},
            data={"template_name": "测试公共模板"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["template_name"] == "测试公共模板"

    def test_import_builtin_no_api_key_required(self, client):
        """导入公共模板不需要 API Key"""
        resp = client.post("/api/v1/templates/import-builtin")
        assert resp.status_code != 401


class TestImportPrivateTemplate:
    """POST /api/v1/templates/import"""

    def test_import_without_api_key_returns_401(self, client):
        """不带 API Key 导入私有模板应返回 401"""
        pptx_bytes = b"PK\x03\x04" + b"\x00" * 128
        resp = client.post(
            "/api/v1/templates/import",
            files={"template_file": ("test.pptx", io.BytesIO(pptx_bytes), "application/octet-stream")},
            data={"template_name": "私有模板"},
        )
        assert resp.status_code == 401

    def test_import_with_api_key(self, client, auth_headers):
        """带 API Key 导入私有模板应成功"""
        pptx_bytes = b"PK\x03\x04" + b"\x00" * 128
        resp = client.post(
            "/api/v1/templates/import",
            files={"template_file": ("my_template.pptx", io.BytesIO(pptx_bytes), "application/octet-stream")},
            data={"template_name": "我的私有模板"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["template_name"] == "我的私有模板"
        assert "template_id" in data
