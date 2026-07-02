"""任务相关接口测试，使用 curl.txt 中的真实请求数据"""
from __future__ import annotations

import time


class TestCreateTask:
    """POST /api/v1/tasks"""

    def test_create_task_with_curl_data(self, client, auth_headers, curl_data):
        """使用 curl.txt 中的完整需求文本创建任务"""
        resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "task_id" in data
        assert data["status"] in ("pending", "running")
        assert data["current_stage"] in ("queued", "preparing")
        assert data["progress"] == 0
        assert data["template_id"] is not None

    def test_create_task_without_api_key_returns_401(self, client, curl_data):
        """不带 API Key 创建任务应返回 401"""
        resp = client.post("/api/v1/tasks", json=curl_data)
        assert resp.status_code == 401

    def test_create_task_with_minimal_requirement(self, client, auth_headers):
        """最简需求文本应能创建任务"""
        payload = {
            "requirement_text": "请生成一份介绍智能制造平台方案的 PPT",
            "template_id": None,
        }
        resp = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["task_id"].startswith("task_")

    def test_create_task_with_custom_filename(self, client, auth_headers):
        """指定 output_filename 应反映在 ftp_result_pptx_path 中"""
        payload = {
            "requirement_text": "测试自定义文件名",
            "options": {"output_filename": "my_demo.pptx"},
        }
        resp = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "my_demo.pptx" in (data.get("ftp_result_pptx_path") or "")

    def test_create_task_without_requirement_returns_422(self, client, auth_headers):
        """缺少 requirement_text 应返回 422 校验错误"""
        resp = client.post("/api/v1/tasks", json={"template_id": None}, headers=auth_headers)
        assert resp.status_code == 422

    def test_create_task_with_empty_requirement(self, client, auth_headers):
        """空需求文本应能创建任务（服务端不做非空校验）"""
        resp = client.post(
            "/api/v1/tasks",
            json={"requirement_text": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 200


class TestListTasks:
    """GET /api/v1/tasks"""

    def test_list_tasks_empty(self, client, auth_headers):
        """无任务时应返回空列表"""
        resp = client.get("/api/v1/tasks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_tasks_after_create(self, client, auth_headers, curl_data):
        """创建任务后应能在列表中看到"""
        client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        resp = client.get("/api/v1/tasks", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert "task_id" in data[0]
        assert "status" in data[0]

    def test_list_tasks_ids_only(self, client, auth_headers, curl_data):
        """ids_only=true 应只返回 task_id 列表"""
        client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        resp = client.get("/api/v1/tasks?ids_only=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert all(isinstance(item, str) for item in data)

    def test_list_tasks_filter_by_status(self, client, auth_headers, curl_data):
        """按 status 过滤任务列表"""
        client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        resp = client.get("/api/v1/tasks?status=pending", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert all(item["status"] in ("pending", "running") for item in data)

    def test_list_tasks_without_api_key_returns_401(self, client):
        """不带 API Key 查询任务应返回 401"""
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 401


class TestGetTask:
    """GET /api/v1/tasks/{task_id}"""

    def test_get_existing_task(self, client, auth_headers, curl_data):
        """查询已存在的任务"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["task_id"] == task_id
        assert data["status"] in ("pending", "running")

    def test_get_nonexistent_task_returns_404(self, client, auth_headers):
        """查询不存在的任务应返回 404"""
        resp = client.get("/api/v1/tasks/task_nonexistent_000", headers=auth_headers)
        assert resp.status_code == 404


class TestTaskPages:
    """GET /api/v1/tasks/{task_id}/pages"""

    def test_get_pages_for_existing_task(self, client, auth_headers, curl_data):
        """查询已存在任务的分页列表（初始为空）"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}/pages", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)


class TestTaskEvents:
    """GET /api/v1/tasks/{task_id}/events"""

    def test_get_events_after_create(self, client, auth_headers, curl_data):
        """创建任务后应至少有 1 条 created 事件"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}/events", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert data[0]["event_type"] == "created"


class TestTaskArtifacts:
    """GET /api/v1/tasks/{task_id}/artifacts"""

    def test_get_artifacts_for_new_task(self, client, auth_headers, curl_data):
        """新任务的产物列表应为空或包含初始产物"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}/artifacts", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)


class TestDownloadTask:
    """GET /api/v1/tasks/{task_id}/download"""

    def test_download_pending_task_returns_409(self, client, auth_headers, curl_data):
        """pending 状态的任务不可下载，应返回 409"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}/download", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 409


class TestStopTask:
    """POST /api/v1/tasks/{task_id}/stop"""

    def test_stop_pending_task(self, client, auth_headers, curl_data):
        """停止 pending 任务应成功"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.post(f"/api/v1/tasks/{task_id}/stop", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["stop_requested"] is True

    def test_stop_nonexistent_task_returns_404(self, client, auth_headers):
        """停止不存在的任务应返回 404"""
        resp = client.post("/api/v1/tasks/task_nonexistent_000/stop", headers=auth_headers)
        assert resp.status_code == 404


class TestResumeTask:
    """POST /api/v1/tasks/{task_id}/resume"""

    def test_resume_pending_task_returns_409(self, client, auth_headers, curl_data):
        """pending 状态不允许恢复，应返回 409"""
        create_resp = client.post("/api/v1/tasks", json=curl_data, headers=auth_headers)
        task_id = create_resp.json()["data"]["task_id"]
        resp = client.post(f"/api/v1/tasks/{task_id}/resume", headers=auth_headers)
        assert resp.status_code == 409
