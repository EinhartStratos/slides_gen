r"""独立测试大模型连通性。

直接调用项目中的模型配置（.env → Settings）和结果解析函数，
分别测试规划、整页 SVG、单图 SVG、结构化内容四个接口。

用法：
    .venv\Scripts\python.exe scripts\test_llm.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

# 让脚本可以从项目根目录运行
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 默认终端编码可能为 GBK，强制 stdout/stderr 使用 UTF-8
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)


class Tee:
    """同时输出到屏幕和文件"""

    def __init__(self, file_path: Path) -> None:
        self.file = file_path.open("w", encoding="utf-8", errors="replace")
        self.stdout = sys.stdout

    def write(self, data: str) -> None:
        self.stdout.write(data)
        self.file.write(data)
        self.file.flush()

    def flush(self) -> None:
        self.stdout.flush()
        self.file.flush()

    def close(self) -> None:
        sys.stdout = self.stdout
        self.file.close()


OUTPUT_FILE = ROOT / "scripts" / "test_llm_output.txt"

from dotenv import load_dotenv

from app.core.config import get_settings
from app.infrastructure.llm.concurrency import init_global_semaphore
from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


SAMPLE_REQUIREMENT = """
一、项目涉及的产品包括：
1、需要改造的产品：GLMS、FIMIS、GRMS、GTS-D、CCMS-G、T-DCMP、SSDRP、C-DRAP、C-RPM、C-CRM、AC-EUP、T-TCE
2、仅配合测试的产品：T-DIIP、UDP-APLT、C-EAM
3、渠道类产品：AC-EUP
4、业务类产品：GLMS、FIMIS、GRMS、GTS-D、CCMS-G
5、平台类产品：T-DCMP、T-DIIP
6、后线类产品：SSDRP、C-DRAP、C-RPM、C-CRM、T-TCE、C-EAM、UDP-APLT
二、各产品的关系如下：
1、AC-EUP联机请求GLMS、GRMS、GTS-D、CCMS-G、C-RPM、C-CRM，接口形式为http
2、GTS-D、FIMIS联机请求GLMS，接口形式包括 IPS-D、http两种，其中http为本次新增的关系
3、CCMS-G、GRMS联机请求GLMS，接口形式为http
4、CCMS-G联机请求GRMS，接口形式为http
5、GLMS、FIMIS、GRMS、GTS-D、CCMS-G、T-DCMP、AC-EUP、T-TCE、C-EAM、C-RPM、C-CRM、SSDRP、C-DRAP、UDP-APLT通过批量从T-DIIP获取数据，接口形式为FTP
6、C-DRAP、C-RPM、C-CRM通过批量从T-DCMP获取数据，接口形式为FTP
""".strip()


def get_api_key() -> str:
    # 优先从环境变量读取；.env 中 DOTENV 可能被系统空变量覆盖，直接解析文件兜底
    key = os.getenv("API_KEY", "") or ""
    if key:
        return key
    env_path = ROOT / ".env"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("API_KEY=") and not line.startswith("#"):
                return line[len("API_KEY="):].strip().strip('"\'')
    return ""


def mask_key(key: str) -> str:
    if not key:
        return "(空)"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def print_result(label: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}")
    if detail:
        for line in detail.splitlines():
            print(f"    {line}")


def main() -> int:
    tee = Tee(OUTPUT_FILE)
    sys.stdout = tee

    # 确保 .env 中配置被加载（覆盖已存在的环境变量）
    load_dotenv(ROOT / ".env", override=True)
    get_settings.cache_clear()

    settings = get_settings()
    # 测试脚本里减少重试，避免长时间退避；整页 SVG 较慢，保留 120s 超时
    settings.llm_rate_limit_max_retries = 1
    settings.llm_timeout_seconds = 120
    init_global_semaphore(settings.max_llm_concurrency)

    print_section("模型配置信息")
    print(f"LLM_BASE_URL: {settings.llm_base_url}")
    print(f"LLM_MODEL: {settings.llm_model}")
    _api_key = get_api_key()
    print(f"API_KEY_LEN: {len(_api_key)}")
    print(f"API_KEY: {mask_key(_api_key)}")
    print(f"TIMEOUT: {settings.llm_timeout_seconds}s")
    print(f"MAX_CONCURRENCY: {settings.max_llm_concurrency}")

    if not settings.llm_base_url or not settings.llm_model:
        print("\n[WARNING] .env 中 LLM_BASE_URL 或 LLM_MODEL 未配置，无法继续测试。")
        return 1

    builder = PageAnalysisPromptBuilder()
    client = OpenAILikePageGenerationClient(settings, builder)

    # 1. 测试页面规划
    print_section("1. 测试页面规划 (plan_single_page)")
    try:
        plan = client.plan_single_page(
            api_key=get_api_key(),
            requirement_text=SAMPLE_REQUIREMENT,
            page_no=1,
            page_name="封面",
            svg_content='<svg xmlns="http://www.w3.org/2000/svg"><text>封面</text></svg>',
            total_pages=10,
        )
        detail = (
            f"decision_source={plan.decision_source}\n"
            f"page_type={plan.page_type}\n"
            f"page_title={plan.page_title}\n"
            f"should_generate={plan.should_generate}"
        )
        print_result("plan_single_page", plan.decision_source != "failed", detail)
    except Exception as exc:
        print_result("plan_single_page", False, f"异常: {exc}")

    # 2. 测试整页 SVG 生成
    print_section("2. 测试整页 SVG 生成 (generate_page_svg)")
    try:
        result = client.generate_page_svg(
            api_key=get_api_key(),
            requirement_text=SAMPLE_REQUIREMENT,
            page_no=2,
            page_name="产品连接关系图",
            page_type="diagram",
            page_title="产品连接关系图",
            svg_content='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540"><rect x="0" y="0" width="960" height="540" fill="#f8f8f8"/><text x="80" y="120" font-size="36" fill="#333">标题</text><text x="80" y="180" font-size="20" fill="#666">正文占位</text></svg>',
        )
        detail = (
            f"decision_source={result.decision_source}\n"
            f"generated_svg_length={len(result.generated_svg or '')}\n"
            f"first_120_chars={(result.generated_svg or '')[:120]}"
        )
        print_result(
            "generate_page_svg",
            result.generated_svg is not None and "<svg" in (result.generated_svg or ""),
            detail,
        )
    except Exception as exc:
        print_result("generate_page_svg", False, f"异常: {exc}")

    # 3. 测试单图 SVG 生成
    print_section("3. 测试单图 SVG 生成 (generate_diagram_svg)")
    try:
        result = client.generate_diagram_svg(
            api_key=get_api_key(),
            requirement_text=SAMPLE_REQUIREMENT,
            page_no=2,
            page_name="产品连接关系图",
            page_title="产品连接关系图",
        )
        detail = (
            f"decision_source={result.decision_source}\n"
            f"generated_svg_length={len(result.generated_svg or '')}\n"
            f"first_120_chars={(result.generated_svg or '')[:120]}"
        )
        print_result(
            "generate_diagram_svg",
            result.generated_svg is not None and "<svg" in (result.generated_svg or ""),
            detail,
        )
    except Exception as exc:
        print_result("generate_diagram_svg", False, f"异常: {exc}")

    # 4. 测试结构化内容生成
    print_section("4. 测试结构化内容生成 (generate_page_content)")
    try:
        structured = client.generate_page_content(
            api_key=get_api_key(),
            requirement_text=SAMPLE_REQUIREMENT,
            page_no=3,
            page_name="项目背景",
            page_rule={
                "page_no": 3,
                "page_name": "项目背景",
                "elements": [
                    {"id": "title", "type": "title", "content_requirement": "标题"},
                    {"id": "body", "type": "text", "content_requirement": "正文"},
                ],
            },
        )
        elements = structured.elements or []
        detail = (
            f"decision_source={getattr(structured, 'decision_source', 'llm')}\n"
            f"should_generate={structured.should_generate}\n"
            f"elements_count={len(elements)}\n"
            f"elements={json.dumps([e.model_dump() if hasattr(e, 'model_dump') else dict(e) for e in elements], ensure_ascii=False, indent=2)[:300]}"
        )
        print_result("generate_page_content", structured.should_generate and len(elements) > 0, detail)
    except Exception as exc:
        print_result("generate_page_content", False, f"异常: {exc}")

    # 5. 裸调用 _call_llm，查看最原始返回
    print_section("5. 原始 LLM 调用 (_call_llm)")
    try:
        raw = client._call_llm(
            api_key=get_api_key(),
            system_prompt="你是一个 helpful 助手。请只返回 JSON。",
            user_prompt="请用 JSON 输出：{\"hello\": \"world\"}",
            use_json=False,
            stream=False,
        )
        print_result("_call_llm", bool(raw), f"原始返回长度={len(raw or '')}\n前 200 字符：{(raw or '')[:200]}")
    except Exception as exc:
        print_result("_call_llm", False, f"异常: {exc}")

    print_section("测试结束")
    print(f"详细输出已写入: {OUTPUT_FILE}")
    print("如果以上出现 401/403/Connection，请检查 .env 中的 API_KEY、LLM_BASE_URL、LLM_MODEL 是否有效。")
    tee.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(1)
