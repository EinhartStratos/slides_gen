"""并发控制测试：全局信号量、429 退避、网络错误退避"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from app.core.config import Settings
from app.infrastructure.llm.concurrency import (
    get_global_semaphore,
    init_global_semaphore,
    reset_global_semaphore,
)
from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


def make_concurrency_settings(tmp_path) -> Settings:
    return Settings(
        app_name="test",
        app_env="test",
        api_prefix="/api/v1",
        runtime_dir=tmp_path / "runtime",
        mock_ftp_dir=tmp_path / "mock_ftp",
        default_template_file=tmp_path / "templete.pptx",
        db_host="",
        db_port=3306,
        db_user="",
        db_password="",
        db_schema="",
        ftp_host="",
        ftp_port=21,
        ftp_user="",
        ftp_password="",
        ftp_root_dir="/slides_gen_server",
        mock_ftp_enabled=True,
        default_template_id=None,
        ppt_master_scripts_dir=tmp_path / "scripts",
        llm_base_url="https://test.api.host",
        llm_model="test-model",
        llm_timeout_seconds=10,
        max_llm_concurrency=2,
        llm_rate_limit_max_retries=3,
        llm_rate_limit_base_delay=0.1,
        llm_rate_limit_max_delay=1.0,
    )


@pytest.fixture(autouse=True)
def reset_semaphore():
    """每个测试前后重置信号量"""
    reset_global_semaphore()
    yield
    reset_global_semaphore()


class TestGlobalSemaphore:
    def test_init_creates_semaphore(self):
        init_global_semaphore(4)
        sem = get_global_semaphore()
        assert sem is not None

    def test_get_without_init_raises(self):
        with pytest.raises(RuntimeError, match="未初始化"):
            get_global_semaphore()

    def test_init_is_idempotent(self):
        init_global_semaphore(4)
        sem1 = get_global_semaphore()
        init_global_semaphore(8)
        sem2 = get_global_semaphore()
        assert sem1 is sem2


class TestSemaphoreInCallLlm:
    def test_semaphore_acquired_and_released(self, tmp_path):
        """_call_llm 执行期间信号量被持有，执行后释放"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        semaphore = get_global_semaphore()
        assert semaphore._value == 2

        with patch.object(client, "_call_stream", return_value="response"):
            client._call_llm("key", "sys", "user", stream=True)

        assert semaphore._value == 2

    def test_semaphore_released_on_exception(self, tmp_path):
        """_call_llm 抛异常时信号量仍被释放"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        semaphore = get_global_semaphore()
        with patch.object(client, "_call_stream", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                client._call_llm("key", "sys", "user", stream=True)

        assert semaphore._value == 2

    def test_concurrency_limited_by_semaphore(self, tmp_path):
        """并发请求数不超过信号量上限"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(2)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        concurrent_count = 0
        max_concurrent = 0
        lock = threading.Lock()

        def slow_stream(payload, headers, timeout):
            nonlocal concurrent_count, max_concurrent
            with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            time.sleep(0.1)
            with lock:
                concurrent_count -= 1
            return "ok"

        with patch.object(client, "_call_stream", side_effect=slow_stream):
            threads = []
            results = []

            def call():
                results.append(client._call_llm("key", "sys", "user", stream=True))

            for _ in range(6):
                t = threading.Thread(target=call)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()

        assert max_concurrent <= 2
        assert len(results) == 6


class TestRateLimitBackoff:
    def test_429_with_retry_after_header(self, tmp_path):
        """429 响应带 Retry-After 头时按该值退避"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        response_429 = httpx2.Response(
            status_code=429,
            headers={"Retry-After": "0.1"},
            request=httpx2.Request("POST", "https://test.api.host/v1/chat/completions"),
        )
        response_ok = "ok response"

        sleep_calls: list[float] = []

        with patch.object(client, "_call_stream", side_effect=[
            httpx2.HTTPStatusError("429", request=response_429.request, response=response_429),
            response_ok,
        ]):
            with patch("app.infrastructure.llm.openai_like_client.time_module.sleep", side_effect=lambda d: sleep_calls.append(d)):
                result = client._call_llm("key", "sys", "user", stream=True)

        assert result == "ok response"
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 0.1

    def test_429_without_retry_after_uses_exponential_backoff(self, tmp_path):
        """429 无 Retry-After 时使用指数退避"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        response_429 = httpx2.Response(
            status_code=429,
            request=httpx2.Request("POST", "https://test.api.host/v1/chat/completions"),
        )

        sleep_calls: list[float] = []

        with patch.object(client, "_call_stream", side_effect=[
            httpx2.HTTPStatusError("429", request=response_429.request, response=response_429),
            "ok",
        ]):
            with patch("app.infrastructure.llm.openai_like_client.time_module.sleep", side_effect=lambda d: sleep_calls.append(d)):
                with patch("app.infrastructure.llm.openai_like_client.random.uniform", return_value=0.0):
                    result = client._call_llm("key", "sys", "user", stream=True)

        assert result == "ok"
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 0.1  # base_delay * 2^0 = 0.1

    def test_429_exhausted_retries_raises(self, tmp_path):
        """429 重试耗尽后抛出 RuntimeError"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        response_429 = httpx2.Response(
            status_code=429,
            headers={"Retry-After": "0.01"},
            request=httpx2.Request("POST", "https://test.api.host/v1/chat/completions"),
        )

        with patch.object(client, "_call_stream", side_effect=httpx2.HTTPStatusError(
            "429", request=response_429.request, response=response_429,
        )):
            with pytest.raises(RuntimeError, match="仍被限流"):
                client._call_llm("key", "sys", "user", stream=True)

    def test_non_429_http_error_not_retried(self, tmp_path):
        """非 429 的 HTTP 错误不退避，直接抛出"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        response_500 = httpx2.Response(
            status_code=500,
            request=httpx2.Request("POST", "https://test.api.host/v1/chat/completions"),
        )

        call_count = 0
        def always_500(payload, headers, timeout):
            nonlocal call_count
            call_count += 1
            raise httpx2.HTTPStatusError("500", request=response_500.request, response=response_500)

        with patch.object(client, "_call_stream", side_effect=always_500):
            with pytest.raises(httpx2.HTTPStatusError):
                client._call_llm("key", "sys", "user", stream=True)

        assert call_count == 1


class TestNetworkErrorBackoff:
    def test_connect_error_retried_then_succeeds(self, tmp_path):
        """连接错误退避后重试成功"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        sleep_calls: list[float] = []

        with patch.object(client, "_call_stream", side_effect=[
            httpx2.ConnectError("connection refused"),
            "ok",
        ]):
            with patch("app.infrastructure.llm.openai_like_client.time_module.sleep", side_effect=lambda d: sleep_calls.append(d)):
                with patch("app.infrastructure.llm.openai_like_client.random.uniform", return_value=0.0):
                    result = client._call_llm("key", "sys", "user", stream=True)

        assert result == "ok"
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 0.1  # base_delay * 2^0 = 0.1

    def test_read_timeout_exhausted_retries_raises(self, tmp_path):
        """读超时重试耗尽后抛出"""
        settings = make_concurrency_settings(tmp_path)
        init_global_semaphore(settings.max_llm_concurrency)
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())

        with patch.object(client, "_call_stream", side_effect=httpx2.ReadTimeout("timeout")):
            with patch("app.infrastructure.llm.openai_like_client.time_module.sleep"):
                with pytest.raises(httpx2.ReadTimeout):
                    client._call_llm("key", "sys", "user", stream=True)


class TestCalculateBackoff:
    def test_retry_after_present(self):
        response = httpx2.Response(
            status_code=429,
            headers={"Retry-After": "5"},
            request=httpx2.Request("POST", "https://example.com"),
        )
        delay = OpenAILikePageGenerationClient._calculate_backoff(response, 1, 1.0, 60.0)
        assert delay == 5.0

    def test_retry_after_invalid_falls_back_to_exponential(self):
        response = httpx2.Response(
            status_code=429,
            headers={"Retry-After": "invalid"},
            request=httpx2.Request("POST", "https://example.com"),
        )
        with patch("app.infrastructure.llm.openai_like_client.random.uniform", return_value=0.0):
            delay = OpenAILikePageGenerationClient._calculate_backoff(response, 2, 1.0, 60.0)
        assert delay == 2.0  # 1.0 * 2^1 = 2.0

    def test_no_retry_after_uses_exponential_with_jitter(self):
        response = httpx2.Response(
            status_code=429,
            request=httpx2.Request("POST", "https://example.com"),
        )
        with patch("app.infrastructure.llm.openai_like_client.random.uniform", return_value=0.5):
            delay = OpenAILikePageGenerationClient._calculate_backoff(response, 3, 1.0, 60.0)
        assert delay == 4.5  # 1.0 * 2^2 + 0.5 = 4.5

    def test_delay_capped_at_max(self):
        response = httpx2.Response(
            status_code=429,
            headers={"Retry-After": "120"},
            request=httpx2.Request("POST", "https://example.com"),
        )
        delay = OpenAILikePageGenerationClient._calculate_backoff(response, 1, 1.0, 60.0)
        assert delay == 60.0
