from __future__ import annotations

from contextlib import contextmanager
from ftplib import FTP
from io import BytesIO
from pathlib import Path
import posixpath
import logging
import shutil

from app.core.config import Settings


logger = logging.getLogger(__name__)


class FtpStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mock_root = settings.mock_ftp_dir
        if settings.mock_ftp_enabled:
            self.mock_root.mkdir(parents=True, exist_ok=True)

    @property
    def remote_enabled(self) -> bool:
        return bool(self.settings.ftp_host.strip())

    @contextmanager
    def client(self):
        if not self.remote_enabled:
            raise RuntimeError("当前未启用远程 FTP，仅使用本地 mock_ftp 存储")
        ftp = FTP()
        ftp.connect(self.settings.ftp_host, self.settings.ftp_port, timeout=20)
        ftp.login(self.settings.ftp_user, self.settings.ftp_password)
        ftp.encoding = "utf-8"
        try:
            yield ftp
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def ping(self) -> bool:
        self.mock_root.mkdir(parents=True, exist_ok=True)
        if not self.remote_enabled:
            return True
        try:
            with self.client() as ftp:
                return bool(ftp.pwd())
        except Exception as exc:
            logger.warning("FTP 健康检查失败: %s", exc)
            return False

    def normalize(self, remote_path: str) -> str:
        path = remote_path.replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        return posixpath.normpath(path)

    def join(self, *parts: str) -> str:
        clean = [part.strip("/") for part in parts if part and part.strip("/")]
        return self.normalize("/" + "/".join(clean))

    def local_path(self, remote_path: str) -> Path:
        normalized = self.normalize(remote_path)
        relative = normalized.lstrip("/")
        return self.mock_root / Path(relative)

    def ensure_dir(self, remote_dir: str) -> str:
        normalized = self.normalize(remote_dir)
        if self.settings.mock_ftp_enabled:
            self.local_path(normalized).mkdir(parents=True, exist_ok=True)
        if self.remote_enabled:
            with self.client() as ftp:
                self._ensure_dir(ftp, normalized)
        return normalized

    def upload_bytes(self, remote_path: str, payload: bytes) -> str:
        normalized = self.normalize(remote_path)
        if self.settings.mock_ftp_enabled:
            local_target = self.local_path(normalized)
            local_target.parent.mkdir(parents=True, exist_ok=True)
            local_target.write_bytes(payload)
        if self.remote_enabled:
            with self.client() as ftp:
                self._ensure_dir(ftp, posixpath.dirname(normalized))
                ftp.storbinary(f"STOR {normalized}", BytesIO(payload))
        return normalized

    def upload_file(self, local_path: Path, remote_path: str) -> str:
        normalized = self.normalize(remote_path)
        if self.settings.mock_ftp_enabled:
            local_target = self.local_path(normalized)
            local_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, local_target)
        if self.remote_enabled:
            with self.client() as ftp:
                self._ensure_dir(ftp, posixpath.dirname(normalized))
                with local_path.open("rb") as handle:
                    ftp.storbinary(f"STOR {normalized}", handle)
        return normalized

    def download_file(self, remote_path: str, local_path: Path) -> Path:
        normalized = self.normalize(remote_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        mock_path = self.local_path(normalized)
        if self.remote_enabled:
            try:
                with self.client() as ftp:
                    with local_path.open("wb") as handle:
                        ftp.retrbinary(f"RETR {normalized}", handle.write)
                mock_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, mock_path)
                return local_path
            except Exception as exc:
                if not mock_path.exists():
                    raise exc
                logger.warning("远程 FTP 下载失败，回退本地 mock_ftp: %s", exc)
        if not mock_path.exists():
            raise FileNotFoundError(f"mock_ftp 中不存在文件: {normalized}")
        shutil.copy2(mock_path, local_path)
        return local_path

    def read_bytes(self, remote_path: str) -> bytes:
        normalized = self.normalize(remote_path)
        mock_path = self.local_path(normalized)
        if self.remote_enabled:
            try:
                buffer = BytesIO()
                with self.client() as ftp:
                    ftp.retrbinary(f"RETR {normalized}", buffer.write)
                payload = buffer.getvalue()
                mock_path.parent.mkdir(parents=True, exist_ok=True)
                mock_path.write_bytes(payload)
                return payload
            except Exception as exc:
                if not mock_path.exists():
                    raise exc
                logger.warning("远程 FTP 读取失败，回退本地 mock_ftp: %s", exc)
        return mock_path.read_bytes()

    def _ensure_dir(self, ftp: FTP, remote_dir: str) -> None:
        parts = [part for part in remote_dir.split("/") if part]
        current = ""
        for part in parts:
            current += "/" + part
            try:
                ftp.mkd(current)
            except Exception:
                pass
