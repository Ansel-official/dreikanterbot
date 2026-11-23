"""把常见文件转换为可送入模型的纯文本。

设计取舍：
- 文件不落盘、不长期保存，只在本次请求内解析；
- 文本类文件支持 UTF-8 / GB18030；
- PDF / DOCX / PPTX / XLSX / ZIP 尽力提取；
- 图片等无法本地 OCR 的类型返回说明，前端仍会保留文件名供模型引用。
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".less",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".py",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".sql",
    ".log",
    ".ini",
    ".toml",
    ".conf",
    ".properties",
    ".tex",
    ".rtf",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".svg"}
ARCHIVE_EXTENSIONS = {".zip"}
MAX_TRUNCATE = 200_000


class FileExtractionError(ValueError):
    pass


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # 最后用替换字符兜底，避免直接失败
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    text = _clean(text)
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖总是随镜像安装
        raise FileExtractionError("服务端未安装 PDF 解析依赖 pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise FileExtractionError("PDF 已加密，无法读取") from exc
        pages = []
        for index, page in enumerate(reader.pages):
            if index >= 300:
                break
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    except FileExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FileExtractionError("PDF 解析失败，请确认文件未损坏") from exc


def _docx_text(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:
        raise FileExtractionError("服务端未安装 DOCX 解析依赖 python-docx") from exc
    try:
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        raise FileExtractionError("DOCX 解析失败") from exc


def _pptx_text(data: bytes) -> str:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise FileExtractionError("服务端未安装 PPTX 解析依赖 python-pptx") from exc
    try:
        presentation = Presentation(io.BytesIO(data))
        slides = []
        for index, slide in enumerate(presentation.slides):
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
            if texts:
                slides.append(f"[第 {index + 1} 页]\n" + "\n".join(texts))
        return "\n\n".join(slides)
    except Exception as exc:  # noqa: BLE001
        raise FileExtractionError("PPTX 解析失败") from exc


def _xlsx_text(data: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise FileExtractionError("服务端未安装 XLSX 解析依赖 openpyxl") from exc
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for sheet in workbook.worksheets:
            parts.append(f"[工作表：{sheet.title}]")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= 5000:
                    parts.append("…（工作表过长，已截断）")
                    break
                cells = ["" if value is None else str(value) for value in row]
                if any(cells):
                    parts.append(" | ".join(cells))
        workbook.close()
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        raise FileExtractionError("XLSX 解析失败") from exc


def _zip_text(data: bytes, limit: int) -> tuple[str, str | None]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileExtractionError("ZIP 文件损坏") from exc
    parts: list[str] = []
    used_chars = 0
    extracted_files = 0
    skipped = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if extracted_files >= 30 or used_chars >= limit:
            skipped += 1
            continue
        suffix = Path(info.filename).suffix.lower()
        if suffix not in TEXT_EXTENSIONS:
            skipped += 1
            continue
        if info.file_size > 5 * 1024 * 1024:
            skipped += 1
            continue
        try:
            raw = archive.read(info)
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        text = _clean(_decode_text(raw))
        if not text:
            skipped += 1
            continue
        header = f"[压缩包内文件：{info.filename}]"
        remaining = limit - used_chars
        chunk = f"{header}\n{text[:remaining]}"
        parts.append(chunk)
        used_chars += len(chunk)
        extracted_files += 1
    note = f"ZIP 内提取 {extracted_files} 个文本文件"
    if skipped:
        note += f"，跳过 {skipped} 个（二进制/超限/非文本）"
    return "\n\n".join(parts), note


def extract_file(filename: str, data: bytes, mime: str | None, limit: int) -> dict[str, Any]:
    safe_name = Path(filename or "附件").name[:200] or "附件"
    suffix = Path(safe_name).suffix.lower()
    note: str | None = None
    truncated = False

    if suffix in TEXT_EXTENSIONS:
        text = _decode_text(data)
    elif suffix == ".pdf" or (mime or "").lower() == "application/pdf":
        text = _pdf_text(data)
    elif suffix == ".docx":
        text = _docx_text(data)
    elif suffix in {".pptx", ".ppt"}:
        text = _pptx_text(data)
    elif suffix in {".xlsx", ".xlsm"}:
        text = _xlsx_text(data)
    elif suffix in ARCHIVE_EXTENSIONS:
        text, note = _zip_text(data, limit)
    elif suffix in IMAGE_EXTENSIONS or (mime or "").lower().startswith("image/"):
        text = ""
        note = "图片文件已记录，但当前 DeepSeek 文本模型无法直接识别图片内容"
    else:
        decoded = _decode_text(data)
        printable = sum(1 for char in decoded[:4000] if char.isprintable() or char in "\n\t")
        if decoded and printable / max(1, len(decoded[:4000])) > 0.85:
            text = decoded
            note = "按纯文本读取"
        else:
            text = ""
            note = "二进制文件未提取到可读文本，仅保留文件信息"

    text, truncated = _truncate(text, limit)
    if truncated:
        note = (note + "；" if note else "") + f"文本超过 {limit} 字符，已截断"
    return {
        "name": safe_name,
        "size": len(data),
        "mime": mime,
        "text": text,
        "text_chars": len(text),
        "truncated": truncated,
        "note": note,
    }
