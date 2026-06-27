"""工具函数测试"""
from __future__ import annotations

from datetime import datetime

from app.core.utils import generate_id, ensure_parent, ensure_clean_dir, json_dumps, to_iso


class TestGenerateId:
    def test_format(self):
        tid = generate_id("task")
        assert tid.startswith("task_")
        parts = tid.split("_")
        assert len(parts) == 3

    def test_uniqueness(self):
        ids = {generate_id("tpl") for _ in range(100)}
        assert len(ids) == 100

    def test_prefix(self):
        assert generate_id("evt").startswith("evt_")
        assert generate_id("art").startswith("art_")


class TestEnsureParent:
    def test_creates_parent(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        ensure_parent(target)
        assert target.parent.exists()

    def test_existing_parent_no_error(self, tmp_path):
        target = tmp_path / "file.txt"
        ensure_parent(target)
        assert target.parent.exists()


class TestEnsureCleanDir:
    def test_creates_new_dir(self, tmp_path):
        target = tmp_path / "new_dir"
        ensure_clean_dir(target)
        assert target.exists()
        assert target.is_dir()

    def test_cleans_existing_dir(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()
        (target / "file.txt").write_text("data", encoding="utf-8")
        ensure_clean_dir(target)
        assert target.exists()
        assert not (target / "file.txt").exists()


class TestJsonDumps:
    def test_basic(self):
        result = json_dumps({"key": "值"})
        assert '"key"' in result
        assert "值" in result

    def test_ensure_ascii_false(self):
        result = json_dumps({"name": "中文"})
        assert "中文" in result
        assert "\\u" not in result

    def test_with_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, 0)
        result = json_dumps({"time": dt})
        assert "2025-01-01" in result


class TestToIso:
    def test_none(self):
        assert to_iso(None) is None

    def test_datetime(self):
        dt = datetime(2025, 6, 27, 10, 30, 0)
        assert to_iso(dt) == "2025-06-27T10:30:00"

    def test_string_passthrough(self):
        assert to_iso("2025-01-01") == "2025-01-01"
