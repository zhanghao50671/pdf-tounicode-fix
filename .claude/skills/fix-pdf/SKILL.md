---
name: fix-pdf
description: Fix Chinese/CJK text copy garbled characters in PDF files by rebuilding ToUnicode CMap. Use when user has a PDF that displays correctly but copies as garbled text.
argument-hint: "[input.pdf] [output.pdf]"
allowed-tools: Bash(python *), Read, Glob
---

# PDF ToUnicode CMap Fix

Fix a PDF file where Chinese/CJK text displays correctly but copies as garbled characters.

## Task

Run the `fix_pdf_tounicode.py` script to repair the ToUnicode CMap mappings in the given PDF file.

### Steps

1. **Check dependencies**: Verify `pymupdf` and `fonttools` are installed. If not, install them with `pip install pymupdf fonttools`.

2. **Locate the script**: Find `fix_pdf_tounicode.py` in the project. It should be at `${CLAUDE_SKILL_DIR}/../../../fix_pdf_tounicode.py` or in the project root.

3. **Run the fix**: Execute the script on the target PDF file(s).

   If the user provides specific files:
   ```
   python fix_pdf_tounicode.py $ARGUMENTS
   ```

   If no arguments given, scan the current directory for PDF files and ask the user which one(s) to fix.

4. **Verify the result**: After fixing, extract a sample of text from the fixed PDF to confirm Chinese characters are correctly decoded. Show the user a before/after comparison if possible.

5. **Report results**: Summarize how many fonts were fixed and show sample text extraction to confirm the fix worked.

### Important Notes

- The script requires matching **system fonts** to be installed (SimSun, SimHei, etc.). If fonts are missing, inform the user which fonts need to be installed.
- The script never modifies the original file; it always creates a new `_fixed.pdf` file.
- Use `PYTHONIOENCODING=utf-8` when running on Windows to ensure correct console output.
