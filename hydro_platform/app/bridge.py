"""桥接层：hydro_platform 核心与 GUI 的适配器。

将核心模块的结果类型和异常转换为 GUI 友好的格式。
"""

from typing import Optional
from hydro_platform.common.enums import AcquisitionErrorCode, FailureStage
from hydro_platform.acquisition.result import FetchResult
from hydro_platform.archive.archiver import ArchiveError
from hydro_platform.parsing.content import ParsedContent


class BridgeError(Exception):
    """桥接层统一异常，携带结构化错误信息。"""

    def __init__(self, stage: str, code: str, message: str, details: dict = None):
        self.stage = stage
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{stage}:{code}] {message}")


def wrap_acquisition_error(result: FetchResult, url: str) -> BridgeError:
    """将 FetchResult 失败转换为 BridgeError。"""
    code = result.error_code.value if result.error_code else "FETCH_FAILED"
    message = result.error or "下载失败"
    return BridgeError(
        stage="ACQUISITION",
        code=code,
        message=message,
        details={"url": url}
    )


def wrap_archive_error(error: ArchiveError, context: dict) -> BridgeError:
    """将 ArchiveError 转换为 BridgeError。"""
    return BridgeError(
        stage="ARCHIVE",
        code="ARCHIVE_FAILED",
        message=str(error),
        details=context
    )


def wrap_parse_error(parsed: ParsedContent, file_path: str) -> BridgeError:
    """将 ParsedContent 失败转换为 BridgeError。"""
    return BridgeError(
        stage="PARSE",
        code="PARSE_FAILED",
        message=parsed.error or "解析失败",
        details={"file_path": file_path}
    )


def wrap_extraction_error(reason: str, context: dict) -> BridgeError:
    """将抽取失败转换为 BridgeError。"""
    return BridgeError(
        stage="EXTRACTION",
        code="NO_CANDIDATES",
        message=reason,
        details=context
    )


def format_error_for_ui(e: BridgeError) -> str:
    """将 BridgeError 格式化为用户友好的大白话提示。"""
    # 映射到完整的大白话描述（直接说问题和原因）
    error_messages = {
        # 下载相关
        ("ACQUISITION", "NETWORK_ERROR"): "网络连接失败，请检查网络后重试",
        ("ACQUISITION", "CONNECT_TIMEOUT"): "连接超时，可能是网络不稳定或网站响应慢",
        ("ACQUISITION", "READ_TIMEOUT"): "下载超时，文件可能太大或网速太慢",
        ("ACQUISITION", "HTTP_403"): "网站拒绝访问，可能需要登录或权限",
        ("ACQUISITION", "HTTP_404"): "文件不存在，链接可能已失效",
        ("ACQUISITION", "HTTP_429"): "访问太频繁被限速，请稍后再试",
        ("ACQUISITION", "HTTP_500"): "网站服务器出错了，请稍后再试",
        ("ACQUISITION", "HTTP_502"): "网站网关错误，请稍后再试",
        ("ACQUISITION", "HTTP_503"): "网站暂时无法访问，请稍后再试",
        ("ACQUISITION", "HTTP_ERROR"): "下载失败，服务器返回错误",
        ("ACQUISITION", "NOT_PDF"): "这不是 PDF 文件，请检查链接",
        ("ACQUISITION", "NOT_EXPECTED_TYPE"): "文件类型不对，可能不是我们需要的格式",
        ("ACQUISITION", "HTML_BLOCK_PAGE"): "遇到防火墙拦截页面，可能需要手动下载",
        ("ACQUISITION", "EMPTY_BODY"): "下载的文件是空的，链接可能有问题",
        ("ACQUISITION", "TOO_LARGE"): "文件太大了，超过了处理限制",

        # 解析相关
        ("PARSE", "PARSE_FAILED"): "文件解析失败，可能是文件损坏或格式不支持",
        ("PARSE", "CORRUPT_FILE"): "文件损坏了，无法打开",
        ("PARSE", "UNSUPPORTED_FORMAT"): "不支持这种文件格式",
        ("PARSE", "PARSE_TIMEOUT"): "文件太复杂，解析超时了",

        # 抽取相关
        ("EXTRACTION", "NO_CANDIDATES"): "文件里没找到发电量数据，可能不是我们需要的报告",
        ("EXTRACTION", "EXTRACTION_TIMEOUT"): "数据抽取超时，文件可能太大或内容太复杂",

        # 归档相关
        ("ARCHIVE", "ARCHIVE_FAILED"): "文件保存失败，可能是磁盘空间不足",
        ("ARCHIVE", "SOURCE_NOT_FOUND"): "数据源不存在，请先在「来源管理」中添加该数据源",
        ("ARCHIVE", "INTEGRITY_ERROR"): "数据库完整性错误，数据可能有冲突",
    }

    # 尝试匹配精确的 (stage, code) 组合
    key = (e.stage, e.code)
    if key in error_messages:
        return error_messages[key]

    # 兜底：通用提示
    stage_map = {
        "ACQUISITION": "下载",
        "PARSE": "解析",
        "EXTRACTION": "数据抽取",
        "ARCHIVE": "保存",
        "UNKNOWN": "处理",
    }
    stage_zh = stage_map.get(e.stage, "处理")

    # 如果有具体的 message，直接用
    if e.message and len(e.message) > 0 and e.message != e.code:
        return f"{stage_zh}失败：{e.message}"

    # 否则给个通用提示
    return f"{stage_zh}时出错了，请检查文件或链接后重试"


__all__ = [
    "BridgeError",
    "wrap_acquisition_error",
    "wrap_archive_error",
    "wrap_parse_error",
    "wrap_extraction_error",
    "format_error_for_ui",
]
