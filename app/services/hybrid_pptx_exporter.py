"""混合导出器。

将 SVG 页面（通过 convert_svg_to_slide_shapes 转为 DrawingML 可编辑形状）
和结构化页面（通过 PPTBuilder 回填到模板原生元素）整合到同一个 PPTX 中。

整合流程：
1. 用 python-pptx 打开模板 PPTX 副本
2. 结构化页面 → PPTBuilder.fill_single_slide() 回填对应 slide
3. SVG 页面 → convert_svg_to_slide_shapes() 生成 DrawingML XML → 注入到对应 slide
4. 删除跳过的页面
5. 重排 slide 顺序
6. 保存最终 PPTX
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from lxml import etree
from pptx import Presentation

from app.core.config import Settings
from app.core.constants import TEMPLATE_COPY_PAGE_TYPES
from app.infrastructure.ppt_master.pptx_builder import PPTBuilder
from app.schemas.structured_generation import StructuredPageResult


logger = logging.getLogger(__name__)

# 1 SVG px = 9525 EMU（96 DPI），与 vendor svg_to_pptx 的换算一致
_EMU_PER_PX = 9525

# DrawingML relationship 属性（r:embed / r:link / r:id 等）
_R_ATTR_RE = re.compile(r"^\{http://schemas\.openxmlformats\.org/officeDocument/2006/relationships\}")

# DrawingML 命名空间
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _qn(tag: str) -> str:
    """构建带命名空间的标签。"""
    prefix, local = tag.split(":")
    ns_map = {"p": NS_P, "a": NS_A, "r": NS_R}
    return f"{{{ns_map[prefix]}}}{local}"


class HybridPptxExporter:
    """混合导出器：整合 SVG slide + 结构化 slide 到一个 PPTX。"""

    def __init__(
        self,
        settings: Settings,
        pptx_builder: PPTBuilder | None = None,
    ) -> None:
        self.settings = settings
        self._svg_convert_func = None

    def _get_svg_convert_func(self):
        """延迟加载 convert_svg_to_slide_shapes 函数。"""
        if self._svg_convert_func is not None:
            return self._svg_convert_func
        scripts_dir = self.settings.ppt_master_scripts_dir
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from svg_to_pptx.drawingml_converter import convert_svg_to_slide_shapes
        self._svg_convert_func = convert_svg_to_slide_shapes
        return self._svg_convert_func

    def export(
        self,
        template_pptx_path: Path,
        template_rules: dict,
        svg_pages: dict[int, Path],
        structured_pages: dict[int, StructuredPageResult],
        skipped_pages: set[int],
        output_path: Path,
        insert_svg_pages: set[int] | None = None,
    ) -> Path:
        """整合两种来源的页面，导出最终 PPTX。

        Args:
            template_pptx_path: 模板 PPTX 路径
            template_rules: 模板规则 JSON dict
            svg_pages: 页码 → SVG 文件路径
            structured_pages: 页码 → StructuredPageResult
            skipped_pages: 跳过的页码集合
            output_path: 输出 PPTX 路径
        """
        presentation = Presentation(template_pptx_path)
        original_slide_count = len(presentation.slides)
        page_rule_map = {int(page["page_no"]): page for page in template_rules.get("pages", [])}
        slide_size = (template_rules.get("template") or {}).get("slide_size") or {}

        insert_svg_pages = insert_svg_pages or set()

        # 页码 → 实际占用的 slide 索引列表（结构化页面可能拆页产生多个 slide）
        page_to_slide_indices: dict[int, list[int]] = {}
        # 需要删除的 slide 索引
        delete_indices: set[int] = set()

        for slide_index in range(original_slide_count):
            page_no = slide_index + 1
            result = structured_pages.get(page_no)
            page_rule = page_rule_map.get(page_no, {})

            # 目录页/尾页为固定页：无论任何情况都原样保留，绝不删除或改写
            if self._is_pinned_page(page_rule, result):
                page_to_slide_indices[page_no] = [slide_index]
                continue

            if page_no in skipped_pages:
                delete_indices.add(slide_index)
                page_to_slide_indices[page_no] = []
                continue

            has_svg = page_no in svg_pages
            insert_svg = page_no in insert_svg_pages

            if result is not None:
                if not result.should_generate:
                    delete_indices.add(slide_index)
                    page_to_slide_indices[page_no] = []
                    continue
                builder = PPTBuilder(template_pptx_path)
                occupied = builder.fill_single_slide(
                    presentation, slide_index, page_rule, result, slide_size=slide_size,
                )
                page_to_slide_indices[page_no] = occupied

                # v4 组装：在已回填的结构化页面上再插入图形
                if has_svg and insert_svg:
                    self._safe_inject_svg(
                        presentation, slide_index, svg_pages[page_no],
                        page_no=page_no, replace_existing=False,
                    )

            elif has_svg:
                self._safe_inject_svg(
                    presentation, slide_index, svg_pages[page_no],
                    page_no=page_no, replace_existing=not insert_svg,
                )
                page_to_slide_indices[page_no] = [slide_index]

            else:
                delete_indices.add(slide_index)
                page_to_slide_indices[page_no] = []

        # 删除跳过的 slide
        for slide_index in sorted(delete_indices, reverse=True):
            self._delete_slide(presentation, slide_index)
            # 调整后续页码的 slide 索引映射
            for page_no, indices in page_to_slide_indices.items():
                page_to_slide_indices[page_no] = [
                    idx - 1 if idx > slide_index else idx for idx in indices
                ]

        # 重排 slide 顺序：按页码顺序排列
        self._reorder_slides(presentation, page_to_slide_indices)

        # 保存
        output_path.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(output_path)
        return output_path

    @staticmethod
    def _is_pinned_page(page_rule: dict, result: StructuredPageResult | None) -> bool:
        """固定页（目录/尾页）判定：命中即原样保留，任何情况不删除。"""
        purpose = (page_rule or {}).get("page_purpose", "")
        page_type = getattr(result, "page_type", None)
        if purpose in TEMPLATE_COPY_PAGE_TYPES or page_type in TEMPLATE_COPY_PAGE_TYPES:
            return True
        name = (page_rule or {}).get("page_name") or ""
        title = ((page_rule or {}).get("title") or {}).get("text") or ""
        combined = f"{name} {title}"
        return any(kw in combined for kw in ("目录", "CONTENTS", "感谢", "致谢", "敬请指正"))

    def _safe_inject_svg(
        self,
        presentation: Presentation,
        slide_index: int,
        svg_file: Path,
        page_no: int,
        replace_existing: bool,
    ) -> None:
        """注入失败时仅告警跳过，避免单张图形拖垮整个导出。"""
        try:
            self._inject_svg_slide(
                presentation, slide_index, svg_file,
                replace_existing=replace_existing,
            )
        except Exception as exc:
            logger.warning("第 %s 页图形 SVG 注入失败，保留原有内容: %s", page_no, exc)

    def _inject_svg_slide(
        self,
        presentation: Presentation,
        slide_index: int,
        svg_file: Path,
        replace_existing: bool = True,
    ) -> None:
        """将 SVG 转换的 DrawingML 注入到模板 PPTX 的指定 slide。

        保持可编辑形状，不渲染为图片。插入模式（replace_existing=False）时，
        先把图形缩放平移到页面中下部区域，避免覆盖标题与正文。
        """
        convert_func = self._get_svg_convert_func()
        source_svg = svg_file
        if not replace_existing:
            source_svg = self._position_svg_lower_middle(presentation, svg_file)
        slide_xml, media_files, rel_entries, _ = convert_func(
            source_svg, slide_num=slide_index + 1, verbose=False,
        )

        # 解析转换后的 XML
        new_slide_root = etree.fromstring(slide_xml.encode("utf-8"))
        new_cSld = new_slide_root.find(_qn("p:cSld"))
        if new_cSld is None:
            logger.warning("SVG 转换结果中未找到 cSld (slide=%s)", slide_index)
            return
        new_sp_tree = new_cSld.find(_qn("p:spTree"))
        if new_sp_tree is None:
            logger.warning("SVG 转换结果中未找到 spTree (slide=%s)", slide_index)
            return

        # 获取目标 slide 的 spTree
        target_slide = presentation.slides[slide_index]
        target_element = target_slide._element
        target_cSld = target_element.find(_qn("p:cSld"))
        if target_cSld is None:
            logger.warning("目标 slide 中未找到 cSld (slide=%s)", slide_index)
            return
        target_sp_tree = target_cSld.find(_qn("p:spTree"))
        if target_sp_tree is None:
            logger.warning("目标 slide 中未找到 spTree (slide=%s)", slide_index)
            return

        # 仅在替换模式下删除目标 slide 中所有现有 shape（保留 nvGrpSpPr 和 grpSpPr）
        if replace_existing:
            for child in list(target_sp_tree):
                tag = etree.QName(child).localname
                if tag not in ("nvGrpSpPr", "grpSpPr"):
                    target_sp_tree.remove(child)

        # 先把转换产生的图片资源挂到目标 slide，建立 旧 rId → 新 rId 映射
        rid_map = self._attach_media(target_slide, media_files, rel_entries)

        # 计算 shape ID 偏移量，避免与已有 slide 的 shape ID 冲突
        max_existing_id = self._find_max_shape_id(presentation)
        id_offset = max_existing_id

        # 将新 shape 插入目标 slide（跳过新 spTree 的 nvGrpSpPr 和 grpSpPr）
        for child in new_sp_tree:
            tag = etree.QName(child).localname
            if tag in ("nvGrpSpPr", "grpSpPr"):
                continue
            cloned = deepcopy(child)
            # 偏移所有 shape ID
            self._offset_shape_ids(cloned, id_offset)
            # 改写 r:embed 等关系引用到目标 slide 的 rId；引用缺失则丢弃该元素
            if not self._remap_relationship_ids(cloned, rid_map):
                logger.warning("跳过引用缺失资源的图形元素 (slide=%s)", slide_index)
                continue
            target_sp_tree.append(cloned)

        logger.info("SVG slide 注入完成 (slide=%s, svg=%s)", slide_index, svg_file.name)

    def _attach_media(
        self,
        slide,
        media_files: dict,
        rel_entries: list,
    ) -> dict:
        """把转换产生的图片挂到目标 slide，返回 旧 rId → 新 rId 映射。"""
        rid_map: dict[str, str] = {}
        if not rel_entries:
            return rid_map
        slide_part = slide.part
        for rel in rel_entries:
            target = rel.get("target", "")
            if not target.startswith("../media/"):
                continue
            media_name = target.split("../media/", 1)[1]
            data = media_files.get(media_name)
            if data is None:
                continue
            try:
                _image_part, new_rid = slide_part.get_or_add_image_part(BytesIO(data))
                rid_map[rel.get("id")] = new_rid
            except Exception as exc:
                logger.warning("图片资源挂载失败 (file=%s): %s", media_name, exc)
        return rid_map

    def _remap_relationship_ids(self, element, rid_map: dict) -> bool:
        """把克隆元素中的 r:* 关系引用改写到目标 slide 的实际 rId。

        返回 False 表示存在无法解析的引用（例如图片挂载失败），调用方应丢弃该元素。
        """
        ok = True
        for attr_name, attr_val in list(element.attrib.items()):
            if not _R_ATTR_RE.match(attr_name):
                continue
            new_rid = rid_map.get(attr_val)
            if new_rid:
                element.attrib[attr_name] = new_rid
            else:
                ok = False
        for child in element:
            if not self._remap_relationship_ids(child, rid_map):
                ok = False
        return ok

    def _position_svg_lower_middle(self, presentation: Presentation, svg_file: Path) -> Path:
        """把单图 SVG 包一层 translate+scale，使图形落在页面中下部区域。"""
        try:
            tree = etree.parse(str(svg_file))
            root = tree.getroot()
            vb_x, vb_y, vb_w, vb_h = self._svg_view_box(root)
            if vb_w <= 0 or vb_h <= 0:
                return svg_file

            slide_w_px = (presentation.slide_width or 0) / _EMU_PER_PX
            slide_h_px = (presentation.slide_height or 0) / _EMU_PER_PX
            if slide_w_px <= 0 or slide_h_px <= 0:
                return svg_file

            # 目标区域：水平居中、宽度约 86% 页宽，占据页面下方约 45% 高度
            target_w = slide_w_px * 0.86
            target_h = slide_h_px * 0.45
            scale = min(target_w / vb_w, target_h / vb_h)
            draw_w = vb_w * scale
            draw_h = vb_h * scale
            tx = (slide_w_px - draw_w) / 2 - vb_x * scale
            ty = slide_h_px * 0.96 - (vb_y + vb_h) * scale

            svg_ns = "http://www.w3.org/2000/svg"
            group = etree.SubElement(root, f"{{{svg_ns}}}g")
            group.set("transform", f"translate({tx:.2f} {ty:.2f}) scale({scale:.4f})")
            for child in list(root):
                if child is group:
                    continue
                if etree.QName(child).localname == "defs":
                    continue
                root.remove(child)
                group.append(child)

            fd, positioned_name = tempfile.mkstemp(prefix="diagram_pos_", suffix=".svg")
            os.close(fd)
            positioned_path = Path(positioned_name)
            tree.write(str(positioned_path), encoding="utf-8", xml_declaration=True)
            return positioned_path
        except Exception as exc:
            logger.warning("图形 SVG 定位预处理失败，按原坐标插入 %s: %s", svg_file.name, exc)
            return svg_file

    @staticmethod
    def _svg_view_box(root) -> tuple[float, float, float, float]:
        """解析 SVG 的 viewBox；缺失时回退 width/height。"""
        view_box = (root.get("viewBox") or "").replace(",", " ").split()
        if len(view_box) == 4:
            try:
                return tuple(float(v) for v in view_box)
            except ValueError:
                pass

        def _num(value: str | None) -> float:
            if not value:
                return 0.0
            match = re.match(r"[-\d.]+", str(value).strip())
            return float(match.group(0)) if match else 0.0

        width = _num(root.get("width"))
        height = _num(root.get("height"))
        if width > 0 and height > 0:
            return (0.0, 0.0, width, height)
        return (0.0, 0.0, 0.0, 0.0)

    def _find_max_shape_id(self, presentation: Presentation) -> int:
        """找到所有 slide 中最大的 shape ID。"""
        max_id = 100
        for slide in presentation.slides:
            for shape in slide.shapes:
                try:
                    shape_id = shape.shape_id
                    if shape_id > max_id:
                        max_id = shape_id
                except Exception:
                    pass
        return max_id + 1

    def _offset_shape_ids(self, element, offset: int) -> None:
        """递归偏移 XML 元素中的所有 shape ID。"""
        tag = etree.QName(element).localname
        if tag == "cNvPr" and "id" in element.attrib:
            try:
                old_id = int(element.attrib["id"])
                element.attrib["id"] = str(old_id + offset)
            except (ValueError, TypeError):
                pass
        for child in element:
            self._offset_shape_ids(child, offset)

    def _delete_slide(self, presentation: Presentation, slide_index: int) -> None:
        """删除指定索引的 slide。"""
        slide_id_list = presentation.slides._sldIdLst
        slide_id = slide_id_list[slide_index]
        relationship_id = slide_id.rId
        presentation.part.drop_rel(relationship_id)
        del slide_id_list[slide_index]

    def _reorder_slides(
        self,
        presentation: Presentation,
        page_to_slide_indices: dict[int, list[int]],
    ) -> None:
        """按页码顺序重排 slide。"""
        sorted_pages = sorted(page_to_slide_indices.keys())
        new_order: list[int] = []
        for page_no in sorted_pages:
            new_order.extend(page_to_slide_indices[page_no])

        if not new_order:
            return

        slide_id_list = presentation.slides._sldIdLst
        # 收集所有 sldId 元素
        sld_ids = [slide_id_list[i] for i in range(len(slide_id_list))]

        # 按新顺序重新排列
        for i, target_index in enumerate(new_order):
            if target_index < len(sld_ids):
                sld_id = sld_ids[target_index]
                # 先移除再插入到正确位置
                slide_id_list.remove(sld_id)
                slide_id_list.insert(i, sld_id)
