"""SVG 校验服务测试"""
from __future__ import annotations

from pathlib import Path

from app.services.svg_validation_service import SvgValidationService


class TestSvgValidationService:
    def setup_method(self):
        self.service = SvgValidationService()

    def test_valid_svg(self, tmp_path):
        svg = tmp_path / "valid.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<rect width="50" height="50"/>'
            "</svg>",
            encoding="utf-8",
        )
        status, message = self.service.validate(svg)
        assert status == "passed"
        assert message == "ok"

    def test_empty_file(self, tmp_path):
        svg = tmp_path / "empty.svg"
        svg.write_text("", encoding="utf-8")
        status, message = self.service.validate(svg)
        assert status == "failed"

    def test_non_svg_root(self, tmp_path):
        svg = tmp_path / "not_svg.svg"
        svg.write_text(
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>test</body></html>',
            encoding="utf-8",
        )
        status, message = self.service.validate(svg)
        assert status == "failed"
        assert "根节点不是 svg" in message

    def test_malformed_xml(self, tmp_path):
        svg = tmp_path / "malformed.svg"
        svg.write_text("<svg><rect></svg>", encoding="utf-8")
        status, message = self.service.validate(svg)
        assert status == "failed"
        assert "SVG 解析失败" in message

    def test_nonexistent_file(self, tmp_path):
        svg = tmp_path / "nonexistent.svg"
        status, message = self.service.validate(svg)
        assert status == "failed"
