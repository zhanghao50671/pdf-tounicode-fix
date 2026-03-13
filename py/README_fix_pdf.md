# PDF 中文复制乱码修复指南

## 问题诊断

**文件**: `clean-SHB_recovered_cleaned.pdf` (华为 ADS 4.0 智能驾驶系统功能安全技术说明书)

**症状**: WPS 打开能正确显示中文，但复制文本时得到乱码字符（如 `Ც㜭傮傦` 而非 `智能驾驶`）。

**根因**: PDF 中 6 个字体的关键编码信息被清除（置为 `null`）：

| xref | BaseFont | 被清除的信息 |
|------|----------|-------------|
| 80 | BCDEEE+SimSun (宋体) | ToUnicode, FontFile2, W |
| 83 | BCDGEE+MicrosoftYaHei-Bold | ToUnicode, FontFile2, W |
| 102 | BCDIEE+SimHei (黑体) | ToUnicode, FontFile2, W |
| 104 | ArialMT | ToUnicode, FontFile2, W |
| 105 | Arial-BoldMT | ToUnicode, FontFile2, W |
| 140 | TimesNewRomanPSMT | ToUnicode, FontFile2, W |

**为什么 WPS 能显示**: 内容流中的 GID（字形 ID）是正确的，WPS 用系统字体替代渲染。但复制时需要 `ToUnicode` CMap 将 GID 转回 Unicode 字符——这个映射表被清空了。

## 修复方案

通过 `fix_pdf_tounicode.py` 脚本从系统安装的同名字体中提取 `cmap` 表，反向构建 GID→Unicode 映射，生成 ToUnicode CMap 流并注入回 PDF。

### 环境要求

- **Python 3.10+**
- **依赖库**:
  ```bash
  pip install pymupdf fonttools
  ```
- **系统字体**（Windows 通常自带）:
  - `C:\Windows\Fonts\simsun.ttc` (宋体) ← **最关键**
  - `C:\Windows\Fonts\simhei.ttf` (黑体)
  - `C:\Windows\Fonts\msyhbd.ttc` (微软雅黑粗体)
  - `C:\Windows\Fonts\arial.ttf`
  - `C:\Windows\Fonts\arialbd.ttf`
  - `C:\Windows\Fonts\times.ttf`

### 使用方法

```bash
# 基本用法（自动生成 xxx_fixed.pdf）
python fix_pdf_tounicode.py clean-SHB_recovered_cleaned.pdf

# 指定输出文件名
python fix_pdf_tounicode.py clean-SHB_recovered_cleaned.pdf output_fixed.pdf
```

### 预期输出

```
[INFO] ============================================================
[INFO] PDF ToUnicode CMap 修复工具
[INFO] ============================================================
[INFO] 打开文件: clean-SHB_recovered_cleaned.pdf
[INFO] 分析 PDF 字体...
[INFO] 发现损坏字体: xref=80, BaseFont=/BCDEEE+SimSun
[INFO] 发现 6 个需要修复的字体

[INFO] 修复字体: /BCDEEE+SimSun (xref=80)
[INFO]   找到字体: SimSun → C:\Windows\Fonts\simsun.ttc
[INFO]   从字体构建了 XXXXX 个 GID→Unicode 映射
[INFO]   ✓ 成功修复
...
[INFO] ✓ 完成! 共修复 6/6 个字体
```

### 验证修复

修复后打开 PDF，尝试复制以下文字验证：

1. **封面标题**: 应能复制为 `智能驾驶系统功能安全技术说明书`
2. **页脚**: 应能复制为 `华为保密信息，未经授权禁止扩散`
3. **表格内容**: 如 `整车功能安全需求`、`驾驶功能安全需求` 等

## 技术原理

```
PDF 内容流:  <1CAA 372D 50AE 50A6>  (GID 序列)
                    ↓
ToUnicode CMap:  GID 0x1CAA → U+667A (智)
                 GID 0x372D → U+80FD (能)
                 GID 0x50AE → U+9A7E (驾)
                 GID 0x50A6 → U+9A76 (驶)
                    ↓
复制粘贴结果:  智能驾驶 ✓
```

修复过程：
1. 扫描 PDF 找到所有 `ToUnicode=null` 的 Type0 字体
2. 根据 `BaseFont` 名称在系统中查找对应字体文件
3. 从字体文件的 `cmap` 表提取 Unicode→GlyphName 映射
4. 结合 `GlyphOrder` 得到 GlyphName→GID 映射
5. 反向得到 GID→Unicode 映射
6. 生成标准 CMap 流并创建新 PDF 对象存储
7. 更新字体对象的 `/ToUnicode` 引用指向新 CMap

## 注意事项

- **必须在有对应系统字体的机器上运行**。不同字体的 GID 编号不同，用错误的字体生成的映射会导致复制出错误的汉字。
- 脚本不会修改原文件，总是生成新文件。
- 如果某个字体找不到精确匹配，会按后备链尝试 CJK 字体。但后备字体的 GID 映射可能不完全正确。
- `FontFile2`（嵌入字体数据）和 `W`（字符宽度）仍为 null，这不影响文本复制，但可能影响在没有对应字体的机器上的显示。

## 故障排除

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| `未找到系统字体 'SimSun'` | 系统未安装宋体 | 安装宋体或将 simsun.ttc 放到脚本目录 |
| 修复后复制仍为乱码 | 使用了错误的后备字体 | 确保系统安装了 SimSun 宋体 |
| 修复后出现不同的错误汉字 | GID 映射来自非匹配字体 | 使用与 PDF 原始字体相同的系统字体 |
| `pip install pymupdf` 失败 | Python 版本过低 | 使用 Python 3.10+ |

## 文件清单

- `fix_pdf_tounicode.py` - 修复脚本
- `README_fix_pdf.md` - 本说明文档（你正在看的）
