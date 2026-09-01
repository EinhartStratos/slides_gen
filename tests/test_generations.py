"""Generation（v4 分离生成模式）接口测试"""
from __future__ import annotations

import time


class TestGenerationEndpoints:
    """测试 /api/v1/generations 系列接口"""

    def _create_generation(self, client, auth_headers, payload):
        resp = client.post("/api/v1/generations", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        return resp.json()["data"]

    def test_create_generation_body_only(self, client_with_mock_llm, auth_headers):
        """仅创建正文任务应返回 body_task_id 和 pending 状态"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["body"],
            "auto_compose": False,
            "requirement_text": "\n需求文档\n----------------------------------------\n项目：测试\n",
            "custom_requirements": "生成测试",
        }
        data = self._create_generation(client_with_mock_llm, auth_headers, payload)
        assert data["generation_mode"] == "separated_body_diagram"
        assert data["body_task_id"].startswith("task_")
        assert data["diagram_task_id"] is None
        assert data["compose_task_id"] is None
        assert data["body_status"] == "pending"

    def test_create_generation_diagrams_only(self, client_with_mock_llm, auth_headers):
        """仅创建图形任务应返回 diagram_task_id"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["diagrams"],
            "auto_compose": False,
            "requirement_text": "\n需求文档\n系统包含 A、B、C 三个模块。\n",
            "custom_requirements": "画架构图",
        }
        data = self._create_generation(client_with_mock_llm, auth_headers, payload)
        assert data["diagram_task_id"].startswith("task_")
        assert data["body_task_id"] is None

    def test_create_generation_auto_compose(self, client_with_mock_llm, auth_headers):
        """auto_compose=true 时，body 与 diagrams 完成后应自动触发 compose"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["body", "diagrams"],
            "auto_compose": True,
            "requirement_text": "\n需求文档\n项目：测试项目，包含 A、B、C 三个系统模块。\n",
            "custom_requirements": "画产品连接关系图",
        }
        data = self._create_generation(client_with_mock_llm, auth_headers, payload)
        assert data["body_task_id"].startswith("task_")
        assert data["diagram_task_id"].startswith("task_")

        # 等待后台任务完成（mock LLM 较快，最多 30 秒）
        generation_id = data["generation_id"]
        for _ in range(30):
            resp = client_with_mock_llm.get(
                f"/api/v1/generations/{generation_id}",
                headers=auth_headers,
            )
            assert resp.status_code == 200
            summary = resp.json()["data"]
            if summary["status"] == "completed":
                break
            time.sleep(1)
        else:
            raise AssertionError("generation 未在 30 秒内完成")

        assert summary["body_status"] == "completed"
        assert summary["diagram_status"] == "completed"
        assert summary["compose_status"] == "completed"
        assert summary["has_body_download"] is True
        assert summary["has_diagram_downloads"] is True
        assert summary["has_composed_download"] is True
        assert summary["body_pptx_artifact_id"] is not None
        assert summary["composed_pptx_artifact_id"] is not None

    def test_list_generations(self, client_with_mock_llm, auth_headers):
        """创建后应能在列表中查询到"""
        self._create_generation(
            client_with_mock_llm,
            auth_headers,
            {
                "generation_mode": "separated_body_diagram",
                "targets": ["body"],
                "auto_compose": False,
                "requirement_text": "测试",
            },
        )
        resp = client_with_mock_llm.get("/api/v1/generations", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "generation_id" in data[0]
        assert "body_status" in data[0]

    def test_append_child_task(self, client_with_mock_llm, auth_headers):
        """后续补触发 body 或 diagrams 任务"""
        data = self._create_generation(
            client_with_mock_llm,
            auth_headers,
            {
                "generation_mode": "separated_body_diagram",
                "targets": ["body"],
                "auto_compose": False,
                "requirement_text": "测试",
            },
        )
        generation_id = data["generation_id"]
        resp = client_with_mock_llm.post(
            f"/api/v1/generations/{generation_id}/tasks",
            json={"task_type": "diagrams"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        result = resp.json()["data"]
        assert result["diagram_task_id"].startswith("task_")

    def test_diagram_list_and_preview(self, client_with_mock_llm, auth_headers):
        """图形任务完成后，应能列出图形并预览 SVG"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["diagrams"],
            "auto_compose": False,
            "requirement_text": "\n系统包含 A、B、C 三个模块，A 调用 B，B 调用 C。\n",
            "custom_requirements": "画架构图",
        }
        data = self._create_generation(client_with_mock_llm, auth_headers, payload)
        generation_id = data["generation_id"]

        for _ in range(30):
            resp = client_with_mock_llm.get(
                f"/api/v1/generations/{generation_id}",
                headers=auth_headers,
            )
            summary = resp.json()["data"]
            if summary["diagram_status"] == "completed":
                break
            time.sleep(1)
        else:
            raise AssertionError("diagrams 任务未在 30 秒内完成")

        # 列出图形
        resp = client_with_mock_llm.get(
            f"/api/v1/generations/{generation_id}/diagrams",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        diagrams = resp.json()["data"]["diagrams"]
        assert len(diagrams) >= 1

        diagram_id = diagrams[0]["diagram_id"]
        task_id = summary["diagram_task_id"]

        # 详情
        resp = client_with_mock_llm.get(
            f"/api/v1/tasks/{task_id}/diagrams/{diagram_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["diagram_id"] == diagram_id

        # 预览 SVG
        resp = client_with_mock_llm.get(
            f"/api/v1/tasks/{task_id}/diagrams/{diagram_id}/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "<svg" in resp.text
        assert resp.headers["content-type"].startswith("image/svg+xml")
