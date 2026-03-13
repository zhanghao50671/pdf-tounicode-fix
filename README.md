# pdf-tounicode-fix

Fix Chinese/CJK text copy garbled characters in PDF files by rebuilding ToUnicode CMap mappings from system fonts.

> **[中文说明](#中文说明)** 请往下翻阅

## Problem

Some PDF files display Chinese text correctly in viewers (WPS, Adobe Reader), but when you **copy-paste** the text, you get garbled characters like `Ც㜭傮傦` instead of `智能驾驶`.

**Root cause**: The font's `ToUnicode` CMap mapping was stripped (set to `null`). The PDF content stream stores GIDs (Glyph IDs) which renderers can display using system fonts, but copy operations need the `ToUnicode` table to convert GIDs back to Unicode characters.

## How It Works

```
PDF content stream:  <1CAA 372D 50AE 50A6>  (GID sequence)
                          ↓
ToUnicode CMap:     GID 0x1CAA → U+667A (智)
                    GID 0x372D → U+80FD (能)
                    GID 0x50AE → U+9A7E (驾)
                    GID 0x50A6 → U+9A76 (驶)
                          ↓
Copy-paste result:  智能驾驶 ✓
```

The tool:
1. Scans the PDF for Type0 fonts with `ToUnicode = null`
2. Matches each font to the corresponding system font file
3. Extracts `Unicode → GlyphName` from the font's `cmap` table
4. Combines with `GlyphOrder` to get `GlyphName → GID`
5. Reverses to build `GID → Unicode` mapping
6. Generates a standard CMap stream and injects it back into the PDF

## Installation

```bash
pip install pymupdf fonttools
```

### System Font Requirements

The matching system fonts must be installed. Windows typically includes:

| Font | File |
|------|------|
| SimSun (宋体) | `C:\Windows\Fonts\simsun.ttc` |
| SimHei (黑体) | `C:\Windows\Fonts\simhei.ttf` |
| Microsoft YaHei Bold | `C:\Windows\Fonts\msyhbd.ttc` |
| Arial | `C:\Windows\Fonts\arial.ttf` |
| Times New Roman | `C:\Windows\Fonts\times.ttf` |

## Usage

```bash
# Auto-generates output as xxx_fixed.pdf
python fix_pdf_tounicode.py input.pdf

# Specify output filename
python fix_pdf_tounicode.py input.pdf output.pdf
```

### Example Output

```
[INFO] ============================================================
[INFO] PDF ToUnicode CMap Fix Tool
[INFO] ============================================================
[INFO] Opening: input.pdf
[INFO] Analyzing PDF fonts...
[INFO] Found broken font: xref=80, BaseFont=/BCDEEE+SimSun
[INFO] Found 6 fonts to fix

[INFO] Fixing font: /BCDEEE+SimSun (xref=80)
[INFO]   Found font: SimSun → C:\Windows\Fonts\simsun.ttc
[INFO]   Built 28839 GID→Unicode mappings from font
[INFO]   ✓ Fixed successfully
...
[INFO] ✓ Done! Fixed 6/6 fonts
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `System font 'SimSun' not found` | Font not installed | Install SimSun or place `simsun.ttc` in script directory |
| Still garbled after fix | Wrong fallback font used | Ensure the exact matching system font is installed |
| Different wrong characters | GID mapping from non-matching font | Use the same font that was originally embedded in the PDF |

## License

MIT

---

## 中文说明

修复 PDF 文件中因字体 `ToUnicode` 映射表被清除导致的中文复制乱码问题。

### 症状

PDF 在 WPS/Adobe Reader 中**显示正常**，但**复制文字**时得到乱码（如 `Ც㜭傮傦`）。

### 原因

PDF 中字体的 `ToUnicode` CMap 被置为 `null`，导致 GID（字形ID）无法转回 Unicode 字符。

### 使用方法

```bash
# 安装依赖
pip install pymupdf fonttools

# 运行修复
python fix_pdf_tounicode.py 问题文件.pdf
```

需要系统安装对应字体（宋体、黑体等），Windows 通常自带。

### 技术细节

详见 [py/README_fix_pdf.md](py/README_fix_pdf.md)。
