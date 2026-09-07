"""用 real_case 真实案例调起 /generations 生成任务并轮询状态。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BASE = "http://127.0.0.1:8000/api/v1"
API_KEY = os.getenv("API_KEY", "")
HEADERS = {"X-LLM-API-Key": API_KEY, "Content-Type": "application/json"}


def extract_result_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("result") or ""


def main() -> None:
    req_file = ROOT / "real_case" / "系统需求-消金圈存产品放开我行对公转账及预警监测模型同步优化需求书.docx.txt"
    draw_file = ROOT / "real_case" / "画图要求.txt"

    requirement_text = extract_result_text(req_file)
    custom_requirements = draw_file.read_text(encoding="utf-8").strip()

    payload = {
        "generation_mode": "separated_body_diagram",
        "targets": ["body", "diagrams"],
        "auto_compose": True,
        "requirement_text": requirement_text,
        "custom_requirements": custom_requirements,
    }

    resp = httpx2.post(f"{BASE}/generations", json=payload, headers=HEADERS, timeout=60)
    print("POST /generations ->", resp.status_code)
    body = resp.json()
    print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
    data = body.get("data") or {}
    generation_id = data.get("generation_id")
    if not generation_id:
        return

    # 轮询直到终态
    for i in range(600):
        time.sleep(5)
        r = httpx2.get(f"{BASE}/generations/{generation_id}", headers=HEADERS, timeout=30)
        summary = r.json().get("data") or {}
        print(
            f"[{i:3d}] status={summary.get('status')} "
            f"body={summary.get('body_status')} "
            f"diagram={summary.get('diagram_status')} "
            f"compose={summary.get('compose_status')} "
            f"kept={summary.get('kept_page_count')} skipped={summary.get('skipped_page_count')} "
            f"diagrams={summary.get('diagram_count')} "
            f"body_dl={summary.get('has_body_download')} "
            f"composed_dl={summary.get('has_composed_download')}"
        )
        if summary.get("status") in ("completed", "completed_with_warnings", "failed"):
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            break

    # 列任务看 task_type
    r = httpx2.get(f"{BASE}/tasks?generation_id={generation_id}", headers=HEADERS, timeout=30)
    print("\ntasks:", json.dumps(r.json().get("data"), ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    main()
