"""测试公共夹具：内存 Mock 数据库 + Mock 适配器 + httpx2 Client"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from dataclasses import dataclass

import httpx2
import pytest

# FastAPI TestClient 内部 import httpx，这里将 httpx2 别名为 httpx 使其兼容
sys.modules.setdefault("httpx", httpx2)
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────
# Mock 数据库：用内存 dict 模拟 MySQL
# ──────────────────────────────────────────────
class MockMySQLDatabase:
    """模拟 MySQLDatabase 接口，无需真实 MySQL 连接"""

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self._tables: dict[str, list[dict]] = {}

    def ping(self) -> bool:
        return True

    # ── 内部辅助 ──
    def _get_table(self, sql: str) -> str | None:
        for pattern in [
            r"INSERT\s+INTO\s+(\w+)",
            r"FROM\s+(\w+)",
            r"UPDATE\s+(\w+)",
        ]:
            m = re.search(pattern, sql, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _parse_insert_columns(self, sql: str) -> list[str]:
        m = re.search(r"INSERT\s+INTO\s+\w+\s*\(([^)]+)\)", sql, re.IGNORECASE)
        if m:
            return [c.strip() for c in m.group(1).split(",")]
        return []

    def _parse_where_conditions(self, sql: str) -> str:
        m = re.search(r"\bWHERE\b\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT\s+|\s+ON\s+DUPLICATE|$)", sql, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    def _parse_order_by(self, sql: str) -> str | None:
        m = re.search(r"ORDER\s+BY\s+(.+?)(?:\s+LIMIT\s+|$)", sql, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_limit(self, sql: str) -> int | None:
        m = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _parse_select_columns(self, sql: str) -> list[str] | None:
        m = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE)
        if m:
            cols = m.group(1).strip()
            if cols == "*":
                return None
            return [c.strip() for c in cols.split(",")]
        return None

    def _match_row(self, row: dict, conditions: str, params: tuple) -> bool:
        """简单 WHERE 条件匹配，支持 AND / OR / = / IS NULL"""
        if not conditions:
            return True
        param_idx = 0

        def eval_condition(cond: str) -> bool:
            nonlocal param_idx
            cond = cond.strip()
            if " OR " in cond or " AND " in cond:
                parts_or = re.split(r"\s+OR\s+", cond, flags=re.IGNORECASE)
                if len(parts_or) > 1:
                    return any(eval_condition(p) for p in parts_or)
                parts_and = re.split(r"\s+AND\s+", cond, flags=re.IGNORECASE)
                return all(eval_condition(p) for p in parts_and)
            m = re.match(r"(\w+)\s*=\s*%s", cond)
            if m:
                col = m.group(1)
                val = params[param_idx] if param_idx < len(params) else None
                param_idx += 1
                return row.get(col) == val
            m = re.match(r"(\w+)\s*=\s*(\d+)", cond)
            if m:
                col, literal = m.group(1), m.group(2)
                return str(row.get(col)) == literal
            m = re.match(r"(\w+)\s*=\s*'([^']*)'", cond)
            if m:
                col, literal = m.group(1), m.group(2)
                return str(row.get(col)) == literal
            return True

        return eval_condition(conditions)

    # ── 公开接口 ──
    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict | None:
        rows = self._do_query(sql, params or ())
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict]:
        return self._do_query(sql, params or ())

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> int:
        params = params or ()
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT"):
            return self._do_insert(sql, params)
        if sql_upper.startswith("UPDATE"):
            return self._do_update(sql, params)
        return 0

    def _do_insert(self, sql: str, params: tuple) -> int:
        table = self._get_table(sql)
        if not table:
            return 0
        columns = self._parse_insert_columns(sql)
        row = {}
        for i, col in enumerate(columns):
            val = params[i] if i < len(params) else None
            if col in ("is_builtin", "stop_requested") and val is not None:
                val = int(val)
            row[col] = val
        row.setdefault("created_at", datetime.now())
        self._tables.setdefault(table, []).append(row)
        return 1

    def _do_update(self, sql: str, params: tuple) -> int:
        table = self._get_table(sql)
        if not table:
            return 0
        set_match = re.search(r"SET\s+(.+?)\s+WHERE", sql, re.IGNORECASE | re.DOTALL)
        where_match = re.search(r"WHERE\s+(.+?)$", sql, re.IGNORECASE | re.DOTALL)
        set_clause = set_match.group(1).strip() if set_match else ""
        where_clause = where_match.group(1).strip() if where_match else ""
        assignments = [a.strip() for a in set_clause.split(",")]
        set_cols = []
        for a in assignments:
            m = re.match(r"(\w+)\s*=\s*%s", a)
            set_cols.append(m.group(1)) if m else None
        where_col = None
        where_val = None
        if where_clause:
            wm = re.match(r"(\w+)\s*=\s*%s", where_clause)
            if wm:
                where_col = wm.group(1)
                where_val = params[len(set_cols)]
        count = 0
        for row in self._tables.get(table, []):
            if where_col is None or row.get(where_col) == where_val:
                for i, col in enumerate(set_cols):
                    if col in ("is_builtin", "stop_requested"):
                        row[col] = int(params[i])
                    else:
                        row[col] = params[i]
                count += 1
        return count

    def _do_query(self, sql: str, params: tuple) -> list[dict]:
        table = self._get_table(sql)
        if not table:
            return []
        rows = list(self._tables.get(table, []))
        conditions = self._parse_where_conditions(sql)
        if conditions:
            rows = [r for r in rows if self._match_row(r, conditions, params)]
        order_by = self._parse_order_by(sql)
        if order_by:
            reverse = "DESC" in order_by.upper()
            sort_col = re.sub(r"\s+(DESC|ASC)", "", order_by, flags=re.IGNORECASE).strip().split(",")[0].strip()
            rows.sort(key=lambda r: (r.get(sort_col) is None, r.get(sort_col)), reverse=reverse)
        limit = self._parse_limit(sql)
        if limit is not None:
            rows = rows[:limit]
        select_cols = self._parse_select_columns(sql)
        if select_cols:
            rows = [{c: r.get(c) for c in select_cols} for r in rows]
        return rows


# ──────────────────────────────────────────────
# Mock PPTX→SVG 适配器
# ──────────────────────────────────────────────
@dataclass
class MockConvertResult:
    slides: list
    canvas_px: tuple


class MockPptxToSvgAdapter:
    """模拟 PptxToSvgAdapter，生成简单的 SVG 文件"""

    def __init__(self, settings=None) -> None:
        self.settings = settings

    def convert(self, pptx_path: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        svg_dir = output_dir / "svg"
        svg_flat_dir = output_dir / "svg-flat"
        svg_dir.mkdir(parents=True, exist_ok=True)
        svg_flat_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, 4):
            svg_content = f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><text>Slide {i}</text></svg>'
            (svg_dir / f"slide_{i}.svg").write_text(svg_content, encoding="utf-8")
            (svg_flat_dir / f"slide_{i}.svg").write_text(svg_content, encoding="utf-8")
        return MockConvertResult(slides=[{"page_no": i, "page_name": f"Slide {i}"} for i in range(1, 4)], canvas_px=(960, 540))


class MockSvgToPptxAdapter:
    """模拟 SvgToPptxAdapter，生成空 PPTX 文件"""

    def __init__(self, settings=None) -> None:
        self.settings = settings

    def export(self, svg_files: list[Path], output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
        return True


# ──────────────────────────────────────────────
# 测试用 Settings
# ──────────────────────────────────────────────
@pytest.fixture
def test_settings(tmp_path):
    from app.core.config import Settings

    mock_ftp = tmp_path / "mock_ftp"
    runtime = tmp_path / "runtime"
    mock_ftp.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_name="test_slides_gen",
        app_env="test",
        api_prefix="/api/v1",
        runtime_dir=runtime,
        mock_ftp_dir=mock_ftp,
        default_template_file=Path("c:/AMD/slides_gen_server/templete.pptx"),
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="",
        db_schema="test_db",
        ftp_host="",
        ftp_port=21,
        ftp_user="",
        ftp_password="",
        ftp_root_dir="/slides_gen_server",
        mock_ftp_enabled=True,
        default_template_id=None,
        ppt_master_scripts_dir=tmp_path / "scripts",
        llm_base_url="",
        llm_model="",
        llm_timeout_seconds=10,
    )


# ──────────────────────────────────────────────
# TestClient fixture
# ──────────────────────────────────────────────
@pytest.fixture
def client(test_settings, monkeypatch):
    # 清除 get_settings 缓存
    from app.core.config import get_settings
    get_settings.cache_clear()

    # 替换 MySQLDatabase、PptxToSvgAdapter、SvgToPptxAdapter
    monkeypatch.setattr("app.services.container.MySQLDatabase", MockMySQLDatabase)
    monkeypatch.setattr("app.services.container.PptxToSvgAdapter", MockPptxToSvgAdapter)
    monkeypatch.setattr("app.services.container.SvgToPptxAdapter", MockSvgToPptxAdapter)
    monkeypatch.setattr("app.core.config.get_settings", lambda: test_settings)

    # 导入 app（延迟导入，确保 monkeypatch 生效）
    from app.main import app

    with TestClient(app) as c:
        yield c

    get_settings.cache_clear()


# ──────────────────────────────────────────────
# 常用 fixture
# ──────────────────────────────────────────────
TEST_API_KEY = "sk-test-key-for-testing"


@pytest.fixture
def api_key():
    return TEST_API_KEY


@pytest.fixture
def auth_headers(api_key):
    return {"X-LLM-API-Key": api_key}


@pytest.fixture
def curl_data():
    """从 curl.txt 中提取请求体 JSON"""
    curl_path = Path("c:/AMD/slides_gen_server/curl.txt")
    raw = curl_path.read_text(encoding="utf-8")
    # 提取 --data '...' 中的 JSON
    match = re.search(r"--data\s+'(\{.*?\})'\s*$", raw, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # 兼容双引号
    match = re.search(r'--data\s+"(\{.*?\})"\s*$', raw, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    raise ValueError("无法从 curl.txt 中提取 JSON 数据")


@pytest.fixture
def curl_requirement_text(curl_data):
    return curl_data["requirement_text"]
