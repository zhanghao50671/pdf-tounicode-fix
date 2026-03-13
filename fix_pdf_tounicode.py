#!/usr/bin/env python3
"""
PDF ToUnicode CMap 修复工具
============================
修复因字体信息被清除（ToUnicode=null, FontFile2=null）导致的中文复制乱码问题。

原理：
  PDF 内容流中保存的 GID（字形ID）是正确的，WPS 能用系统字体正确渲染。
  但复制文字需要 ToUnicode 映射表将 GID 转回 Unicode，该表被清空了。
  本工具利用系统安装的同名字体，从其 cmap 表反向构建 GID→Unicode 映射，
  然后注入回 PDF 中。

使用方法：
  python fix_pdf_tounicode.py input.pdf [output.pdf]

依赖：
  pip install pymupdf fonttools

系统字体要求（Windows 通常自带）：
  - SimSun (宋体): C:/Windows/Fonts/simsun.ttc
  - SimHei (黑体): C:/Windows/Fonts/simhei.ttf
  - Microsoft YaHei (微软雅黑): C:/Windows/Fonts/msyh.ttc
"""

from __future__ import annotations

import sys
import os
import re
import struct
import logging
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("错误: 缺少 PyMuPDF 库，请运行: pip install pymupdf")
    sys.exit(1)

try:
    from fontTools.ttLib import TTFont
except ImportError:
    print("错误: 缺少 fonttools 库，请运行: pip install fonttools")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# 系统字体搜索路径（按优先级排列）
# Windows / macOS / Linux 常见路径
FONT_SEARCH_PATHS = [
    # Windows
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    # macOS
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
    Path("/System/Library/Fonts"),
    # Linux
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
]

# PDF 字体 BaseFont 名称 → 系统字体文件名映射
# 键: BaseFont 中去掉子集前缀后的名称
# 值: 可能的系统文件名列表（按优先级）
FONT_FILE_MAP = {
    "SimSun":               ["simsun.ttc", "simsun.ttf", "SimSun.ttc", "SimSun.ttf"],
    "SimHei":               ["simhei.ttf", "SimHei.ttf", "simhei.ttc"],
    "MicrosoftYaHei":       ["msyh.ttc", "msyh.ttf", "MicrosoftYaHei.ttc"],
    "MicrosoftYaHei-Bold":  ["msyhbd.ttc", "msyhbd.ttf", "MicrosoftYaHeiBold.ttc"],
    "MicrosoftYaHeiUI":     ["msyh.ttc", "msyh.ttf"],
    "ArialMT":              ["arial.ttf", "Arial.ttf", "arial.ttc"],
    "Arial-BoldMT":         ["arialbd.ttf", "Arial Bold.ttf", "Arial-BoldMT.ttf"],
    "TimesNewRomanPSMT":    ["times.ttf", "Times New Roman.ttf", "TimesNewRoman.ttf"],
    "TimesNewRomanPS-BoldMT": ["timesbd.ttf", "Times New Roman Bold.ttf"],
    # Noto CJK 作为后备
    "NotoSansCJKsc":        ["NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf"],
    "NotoSerifCJKsc":       ["NotoSerifCJK-Regular.ttc", "NotoSerifSC-Regular.otf"],
    # WenQuanYi (Linux)
    "WenQuanYiZenHei":      ["wqy-zenhei.ttc", "wqy-zenhei.ttf"],
}

# CJK 字体的后备链（当找不到精确匹配时按此顺序尝试）
CJK_FALLBACK_CHAIN = [
    "SimSun", "SimHei", "MicrosoftYaHei",
    "NotoSansCJKsc", "NotoSerifCJKsc", "WenQuanYiZenHei",
]


# ============================================================
# 字体查找
# ============================================================

def find_system_font(base_font_name: str) -> str | None:
    """
    根据 PDF BaseFont 名称查找系统字体文件路径。
    返回找到的字体文件完整路径，找不到则返回 None。
    """
    # 去掉子集前缀 (如 "BCDEEE+SimSun" → "SimSun")
    clean_name = base_font_name
    if "+" in clean_name:
        clean_name = clean_name.split("+", 1)[1]

    # 去掉常见的变体后缀进行模糊匹配
    search_names = [clean_name]
    # 也尝试去掉连字符后的部分
    if "-" in clean_name:
        search_names.append(clean_name.replace("-", ""))

    for name in search_names:
        candidates = FONT_FILE_MAP.get(name, [])
        for candidate in candidates:
            for search_dir in FONT_SEARCH_PATHS:
                if not search_dir.exists():
                    continue
                # 递归搜索
                for font_path in search_dir.rglob(candidate):
                    if font_path.is_file():
                        log.info(f"  找到字体: {name} → {font_path}")
                        return str(font_path)

    return None


def find_cjk_fallback_font() -> str | None:
    """查找任意可用的 CJK 后备字体"""
    for name in CJK_FALLBACK_CHAIN:
        candidates = FONT_FILE_MAP.get(name, [])
        for candidate in candidates:
            for search_dir in FONT_SEARCH_PATHS:
                if not search_dir.exists():
                    continue
                for font_path in search_dir.rglob(candidate):
                    if font_path.is_file():
                        log.info(f"  使用 CJK 后备字体: {font_path}")
                        return str(font_path)
    return None


# ============================================================
# 从字体构建 GID → Unicode 映射
# ============================================================

def build_gid_to_unicode_map(font_path: str, font_index: int = 0) -> dict[int, int]:
    """
    从 TrueType/OpenType 字体文件构建 GID → Unicode 映射。

    参数:
        font_path: 字体文件路径
        font_index: TTC 集合中的字体索引

    返回:
        dict: {gid: unicode_codepoint}
    """
    try:
        tt = TTFont(font_path, fontNumber=font_index)
    except Exception:
        tt = TTFont(font_path)

    gid_to_unicode = {}

    # 遍历 cmap 表，优先使用 (3,1) Windows Unicode BMP 或 (3,10) Windows Unicode Full
    best_cmap = None
    for table in tt["cmap"].tables:
        if table.platformID == 3 and table.platEncID == 10:
            best_cmap = table.cmap
            break
        if table.platformID == 3 and table.platEncID == 1:
            if best_cmap is None:
                best_cmap = table.cmap
        if table.platformID == 0:
            if best_cmap is None:
                best_cmap = table.cmap

    if best_cmap is None:
        log.warning(f"  字体 {font_path} 中未找到可用的 cmap 表")
        return gid_to_unicode

    # cmap: unicode_codepoint → glyph_name
    # 我们需要: gid → unicode_codepoint
    # 先获取 glyph_name → gid 的映射
    glyph_order = tt.getGlyphOrder()
    name_to_gid = {name: gid for gid, name in enumerate(glyph_order)}

    for unicode_val, glyph_name in best_cmap.items():
        gid = name_to_gid.get(glyph_name)
        if gid is not None and gid > 0:
            # 如果同一个 GID 映射到多个 Unicode，保留第一个（通常是最常用的）
            if gid not in gid_to_unicode:
                gid_to_unicode[gid] = unicode_val

    log.info(f"  从字体构建了 {len(gid_to_unicode)} 个 GID→Unicode 映射")
    tt.close()
    return gid_to_unicode


# ============================================================
# 生成 ToUnicode CMap
# ============================================================

def generate_tounicode_cmap(gid_to_unicode: dict[int, int]) -> bytes:
    """
    根据 GID→Unicode 映射生成标准的 ToUnicode CMap 流。

    CMap 格式要求每个 beginbfchar/endbfchar 块最多 100 条。
    """
    if not gid_to_unicode:
        return b""

    # 排序
    pairs = sorted(gid_to_unicode.items())

    # 分块（每块最多 100 条）
    chunks = []
    for i in range(0, len(pairs), 100):
        chunks.append(pairs[i:i + 100])

    lines = []
    lines.append("/CIDInit /ProcSet findresource begin")
    lines.append("12 dict begin")
    lines.append("begincmap")
    lines.append("/CIDSystemInfo")
    lines.append("<< /Registry (Adobe)")
    lines.append("/Ordering (UCS)")
    lines.append("/Supplement 0")
    lines.append(">> def")
    lines.append("/CMapName /Adobe-Identity-UCS def")
    lines.append("/CMapType 2 def")
    lines.append("1 begincodespacerange")
    lines.append("<0000><FFFF>")
    lines.append("endcodespacerange")

    for chunk in chunks:
        # 尝试将连续映射合并为 bfrange
        # 简单起见，对于大量数据全用 bfchar
        lines.append(f"{len(chunk)} beginbfchar")
        for gid, uni in chunk:
            if uni <= 0xFFFF:
                lines.append(f"<{gid:04X}><{uni:04X}>")
            else:
                # 对于 BMP 之外的字符，使用 UTF-16 代理对
                hi = 0xD800 + ((uni - 0x10000) >> 10)
                lo = 0xDC00 + ((uni - 0x10000) & 0x3FF)
                lines.append(f"<{gid:04X}><{hi:04X}{lo:04X}>")
        lines.append("endbfchar")

    lines.append("endcmap")
    lines.append("CMapName currentdict /CMap defineresource pop")
    lines.append("end")
    lines.append("end")

    return "\n".join(lines).encode("latin-1")


# ============================================================
# 扫描 PDF 内容流，提取使用的 GID
# ============================================================

def extract_used_gids_from_pdf(doc: fitz.Document, font_xrefs: list[int]) -> dict[int, set[int]]:
    """
    扫描所有页面的内容流，提取每个字体使用的 GID 集合。
    这一步是可选的优化——如果有完整的系统字体，可以直接用全量映射。

    返回: {font_xref: set(gid1, gid2, ...)}
    """
    # 简化实现：直接返回空集，表示使用全量映射
    # 全量映射虽然大一些但确保覆盖所有字符
    return {xref: set() for xref in font_xrefs}


# ============================================================
# 核心修复逻辑
# ============================================================

def analyze_pdf_fonts(doc: fitz.Document) -> list[dict]:
    """
    分析 PDF 中所有字体，找出需要修复的字体。

    返回: [{"xref": int, "base_font": str, "has_tounicode": bool, "has_fontfile": bool}, ...]
    """
    broken_fonts = []
    seen_xrefs = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        fonts = page.get_fonts(full=True)
        for font_info in fonts:
            xref = font_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                obj_str = doc.xref_object(xref)
            except Exception:
                continue

            # 只关注 Type0 字体（CID 字体，通常用于 CJK）
            if "/Type0" not in obj_str and "/Subtype /Type0" not in obj_str:
                continue

            base_font = ""
            for line in obj_str.split("\n"):
                if "/BaseFont" in line:
                    parts = line.strip().split("/")
                    if len(parts) >= 2:
                        base_font = parts[-1].strip()
                    break

            has_tounicode = "ToUnicode null" not in obj_str and "/ToUnicode" in obj_str
            has_null_tounicode = "ToUnicode null" in obj_str

            if has_null_tounicode:
                broken_fonts.append({
                    "xref": xref,
                    "base_font": base_font,
                    "obj_str": obj_str,
                })
                log.info(f"发现损坏字体: xref={xref}, BaseFont=/{base_font}")

    return broken_fonts


def fix_pdf(input_path: str, output_path: str) -> bool:
    """
    修复 PDF 文件中损坏的 ToUnicode 映射。

    参数:
        input_path: 输入 PDF 路径
        output_path: 输出 PDF 路径

    返回:
        bool: 是否成功修复了至少一个字体
    """
    log.info(f"打开文件: {input_path}")
    doc = fitz.open(input_path)

    # 1. 分析字体
    log.info("分析 PDF 字体...")
    broken_fonts = analyze_pdf_fonts(doc)

    if not broken_fonts:
        log.info("未发现需要修复的字体，文件正常。")
        doc.close()
        return False

    log.info(f"发现 {len(broken_fonts)} 个需要修复的字体\n")

    # 2. 查找系统字体并构建映射
    fixed_count = 0
    cjk_fallback = None  # 延迟加载

    for font_info in broken_fonts:
        xref = font_info["xref"]
        base_font = font_info["base_font"]
        clean_name = base_font.split("+", 1)[-1] if "+" in base_font else base_font

        log.info(f"修复字体: /{base_font} (xref={xref})")

        # 查找对应的系统字体
        system_font_path = find_system_font(base_font)

        if system_font_path is None:
            log.warning(f"  未找到系统字体 '{clean_name}'，尝试 CJK 后备字体...")
            if cjk_fallback is None:
                cjk_fallback = find_cjk_fallback_font()
            system_font_path = cjk_fallback

        if system_font_path is None:
            log.error(f"  ✗ 无法找到任何可用字体来修复 '{clean_name}'，跳过")
            continue

        # 对于 TTC 文件，尝试找到正确的字体索引
        font_index = 0
        if system_font_path.lower().endswith(".ttc"):
            font_index = _find_font_index_in_ttc(system_font_path, clean_name)

        # 构建 GID → Unicode 映射
        gid_to_unicode = build_gid_to_unicode_map(system_font_path, font_index)

        if not gid_to_unicode:
            log.error(f"  ✗ 无法从字体构建映射，跳过")
            continue

        # 生成 ToUnicode CMap
        cmap_data = generate_tounicode_cmap(gid_to_unicode)
        log.info(f"  生成 CMap: {len(cmap_data)} 字节, {len(gid_to_unicode)} 个映射")

        # 3. 注入 CMap 到 PDF
        success = inject_tounicode_cmap(doc, xref, cmap_data)
        if success:
            fixed_count += 1
            log.info(f"  ✓ 成功修复")
        else:
            log.error(f"  ✗ 注入 CMap 失败")

    # 4. 保存
    if fixed_count > 0:
        log.info(f"\n保存修复后的文件: {output_path}")
        doc.save(output_path, garbage=0, deflate=True)
        log.info(f"✓ 完成! 共修复 {fixed_count}/{len(broken_fonts)} 个字体")
    else:
        log.warning("没有成功修复任何字体")

    doc.close()
    return fixed_count > 0


def _find_font_index_in_ttc(ttc_path: str, target_name: str) -> int:
    """在 TTC 字体集合中查找匹配的字体索引"""
    try:
        # 读取 TTC 头部获取字体数量
        with open(ttc_path, "rb") as f:
            tag = f.read(4)
            if tag != b"ttcf":
                return 0
            f.read(4)  # version
            num_fonts = struct.unpack(">I", f.read(4))[0]

        # 尝试每个索引
        target_lower = target_name.lower().replace("-", "").replace(" ", "")
        for i in range(num_fonts):
            try:
                tt = TTFont(ttc_path, fontNumber=i)
                name_table = tt["name"]
                for record in name_table.names:
                    try:
                        name_str = record.toUnicode().lower().replace("-", "").replace(" ", "")
                        if target_lower in name_str or name_str in target_lower:
                            tt.close()
                            return i
                    except Exception:
                        continue
                tt.close()
            except Exception:
                continue
    except Exception:
        pass
    return 0


def inject_tounicode_cmap(doc: fitz.Document, font_xref: int, cmap_data: bytes) -> bool:
    """
    将 ToUnicode CMap 流注入到 PDF 字体对象中。

    策略：
    1. 创建一个新的 xref，先初始化为空字典对象
    2. 将 CMap 数据写入为该对象的 stream
    3. 修改字体对象的 /ToUnicode 引用指向新对象
    """
    try:
        # 创建新的 xref
        new_xref = doc.get_new_xref()
        # 必须先初始化为空字典，否则 update_stream 会报错
        doc.update_object(new_xref, "<<>>")
        # 写入 CMap stream
        doc.update_stream(new_xref, cmap_data)
        # 更新字体对象的 /ToUnicode 引用
        doc.xref_set_key(font_xref, "ToUnicode", f"{new_xref} 0 R")

        return True
    except Exception as e:
        log.error(f"  注入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# 验证修复结果
# ============================================================

def verify_fix(output_path: str):
    """验证修复后的 PDF 文本是否正确"""
    log.info(f"\n验证修复结果: {output_path}")
    doc = fitz.open(output_path)

    # 检查几个关键页面
    test_pages = [0, 3, 7]  # 封面、目录、第一个表格页
    for page_num in test_pages:
        if page_num >= len(doc):
            continue
        page = doc[page_num]
        text = page.get_text()

        # 检查是否包含预期的中文字符
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        garbled_chars = sum(1 for c in text if '\u1000' <= c <= '\u1fff' or '\u0800' <= c <= '\u08ff')

        status = "✓" if chinese_chars > garbled_chars else "✗"
        log.info(f"  Page {page_num + 1}: 中文字符={chinese_chars}, 疑似乱码={garbled_chars} {status}")

        # 显示文本样本
        sample = text[:100].replace("\n", " ").strip()
        log.info(f"    样本: {sample}")

    doc.close()


# ============================================================
# 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法: python fix_pdf_tounicode.py <输入PDF> [输出PDF]")
        print()
        print("示例:")
        print("  python fix_pdf_tounicode.py broken.pdf")
        print("  python fix_pdf_tounicode.py broken.pdf fixed.pdf")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        log.error(f"文件不存在: {input_path}")
        sys.exit(1)

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        stem = Path(input_path).stem
        suffix = Path(input_path).suffix
        output_path = str(Path(input_path).parent / f"{stem}_fixed{suffix}")

    log.info("=" * 60)
    log.info("PDF ToUnicode CMap 修复工具")
    log.info("=" * 60)

    success = fix_pdf(input_path, output_path)

    if success:
        verify_fix(output_path)
        print(f"\n修复完成: {output_path}")
    else:
        print("\n修复失败，请检查日志输出。")
        sys.exit(1)


if __name__ == "__main__":
    main()
