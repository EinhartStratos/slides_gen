"""FTP mock 存储测试"""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.storage.ftp import FtpStorage
from app.core.config import Settings


def make_ftp(tmp_path) -> FtpStorage:
    """创建使用本地 mock_ftp 的 FtpStorage 实例"""
    settings = Settings(
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
        llm_base_url="",
        llm_model="",
        llm_timeout_seconds=10,
    )
    return FtpStorage(settings)


class TestFtpStorage:
    def test_ping_returns_true_in_mock_mode(self, tmp_path):
        ftp = make_ftp(tmp_path)
        assert ftp.ping() is True

    def test_remote_enabled_false(self, tmp_path):
        ftp = make_ftp(tmp_path)
        assert ftp.remote_enabled is False

    def test_join_paths(self, tmp_path):
        ftp = make_ftp(tmp_path)
        result = ftp.join("/base", "sub", "file.txt")
        assert result == "/base/sub/file.txt"

    def test_normalize(self, tmp_path):
        ftp = make_ftp(tmp_path)
        assert ftp.normalize("a/b/c") == "/a/b/c"
        assert ftp.normalize("\\a\\b") == "/a/b"

    def test_upload_and_read_bytes(self, tmp_path):
        ftp = make_ftp(tmp_path)
        remote = ftp.join(ftp.settings.ftp_root_dir, "test", "file.txt")
        ftp.upload_bytes(remote, b"hello world")
        assert ftp.read_bytes(remote) == b"hello world"

    def test_upload_file(self, tmp_path):
        ftp = make_ftp(tmp_path)
        local = tmp_path / "local.txt"
        local.write_text("test content", encoding="utf-8")
        remote = ftp.join(ftp.settings.ftp_root_dir, "uploaded", "local.txt")
        result = ftp.upload_file(local, remote)
        assert result == remote
        # 验证 mock 目录中存在文件
        mock_file = ftp.local_path(remote)
        assert mock_file.exists()
        assert mock_file.read_text(encoding="utf-8") == "test content"

    def test_download_file(self, tmp_path):
        ftp = make_ftp(tmp_path)
        # 先上传
        remote = ftp.join(ftp.settings.ftp_root_dir, "dl", "file.bin")
        ftp.upload_bytes(remote, b"download me")
        # 下载到本地路径
        local_target = tmp_path / "downloaded.bin"
        ftp.download_file(remote, local_target)
        assert local_target.exists()
        assert local_target.read_bytes() == b"download me"

    def test_download_nonexistent_raises(self, tmp_path):
        ftp = make_ftp(tmp_path)
        remote = ftp.join(ftp.settings.ftp_root_dir, "nonexistent", "file.bin")
        local_target = tmp_path / "should_fail.bin"
        try:
            ftp.download_file(remote, local_target)
            assert False, "应抛出 FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_ensure_dir(self, tmp_path):
        ftp = make_ftp(tmp_path)
        remote = ftp.join(ftp.settings.ftp_root_dir, "new_dir", "sub_dir")
        result = ftp.ensure_dir(remote)
        assert result == remote
        local = ftp.local_path(remote)
        assert local.exists()
        assert local.is_dir()

    def test_local_path(self, tmp_path):
        ftp = make_ftp(tmp_path)
        lp = ftp.local_path("/slides_gen_server/templates/tpl_001/source/template.pptx")
        assert lp == ftp.mock_root / "slides_gen_server" / "templates" / "tpl_001" / "source" / "template.pptx"
