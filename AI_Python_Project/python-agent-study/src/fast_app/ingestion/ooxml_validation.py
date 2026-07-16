from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


OOXML_CORE_FILES = {
    ".pptx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
    },
    ".xlsx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
    },
}


class OOXMLValidationError(ValueError):
    """携带稳定错误码的 OOXML 包校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        """保存面向 API/任务状态的稳定错误码和可读错误信息。"""

        super().__init__(message)
        self.code = code


def validate_ooxml_package(
    path: str | Path,
    *,
    max_uncompressed_bytes: int = 200 * 1024 * 1024,
    max_entries: int = 10_000,
    max_compression_ratio: float = 100.0,
) -> None:
    """校验 PPTX/XLSX ZIP 结构及解压资源上限，不解压文件到磁盘。"""

    file_path = Path(path)
    extension = file_path.suffix.lower()
    required_files = OOXML_CORE_FILES.get(extension)
    if required_files is None:
        raise OOXMLValidationError(
            "UNSUPPORTED_DOCUMENT_TYPE",
            "只允许上传 .pptx 或 .xlsx 文件",
        )

    try:
        with ZipFile(file_path) as archive:
            entries = archive.infolist()
            # 先限制条目数量，避免攻击者用大量小文件消耗遍历和元数据资源。
            if len(entries) > max_entries:
                raise OOXMLValidationError(
                    "OOXML_TOO_MANY_ENTRIES",
                    "OOXML 文件包含过多 ZIP 条目",
                )

            names: set[str] = set()
            total_uncompressed = 0
            total_compressed = 0
            for entry in entries:
                # 所有条目在读取内容前先做路径和加密标志校验。
                _validate_archive_name(entry.filename)
                if entry.flag_bits & 0x1:
                    raise OOXMLValidationError(
                        "OOXML_ENCRYPTED",
                        "不支持加密的 OOXML 文件",
                    )
                names.add(entry.filename)
                total_uncompressed += entry.file_size
                total_compressed += entry.compress_size
                # 单条目压缩比与累计解压大小同时受限，覆盖常见 ZIP Bomb 形式。
                if total_uncompressed > max_uncompressed_bytes:
                    raise OOXMLValidationError(
                        "OOXML_UNCOMPRESSED_TOO_LARGE",
                        "OOXML 文件解压后大小超过限制",
                    )
                if _compression_ratio(entry.file_size, entry.compress_size) > max_compression_ratio:
                    raise OOXMLValidationError(
                        "OOXML_COMPRESSION_RATIO_TOO_HIGH",
                        "OOXML ZIP 条目压缩比超过限制",
                    )

            # 单个条目正常也不代表整体安全，因此还要检查整个压缩包的总压缩比。
            if _compression_ratio(total_uncompressed, total_compressed) > max_compression_ratio:
                raise OOXMLValidationError(
                    "OOXML_COMPRESSION_RATIO_TOO_HIGH",
                    "OOXML ZIP 总体压缩比超过限制",
                )

            corrupt_entry = archive.testzip()
            if corrupt_entry is not None:
                raise OOXMLValidationError(
                    "OOXML_CORRUPT",
                    f"OOXML ZIP 条目损坏: {corrupt_entry}",
                )

            # 精确检查 OOXML 核心文件，不能只凭 ppt/ 或 xl/ 目录前缀判断格式。
            missing = sorted(required_files - names)
            if missing:
                raise OOXMLValidationError(
                    "OOXML_CORE_FILE_MISSING",
                    f"OOXML 文件缺少核心文件: {', '.join(missing)}",
                )
    except BadZipFile as exc:
        raise OOXMLValidationError(
            "INVALID_OOXML_PACKAGE",
            "文件不是有效的 OOXML ZIP 包",
        ) from exc


def _validate_archive_name(name: str) -> None:
    """拒绝绝对路径、目录穿越、Windows 路径和控制字符条目。"""

    if (
        not name
        or "\\" in name
        or "\x00" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise OOXMLValidationError("OOXML_UNSAFE_PATH", "OOXML ZIP 条目路径不安全")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise OOXMLValidationError("OOXML_UNSAFE_PATH", "OOXML ZIP 条目路径不安全")


def _compression_ratio(uncompressed: int, compressed: int) -> float:
    """计算压缩比；非空内容的零压缩大小按无限大风险处理。"""

    if uncompressed == 0:
        return 0.0
    if compressed == 0:
        return float("inf")
    return uncompressed / compressed


__all__ = ["OOXMLValidationError", "validate_ooxml_package"]
