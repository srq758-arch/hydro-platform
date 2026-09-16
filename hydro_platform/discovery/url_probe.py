"""轻量 URL 可访问性探测。

来源发现不是正式下载：这里只做有上限的访问预检，用来排除 404 等失效链接。
对于可访问的 HTML 页面，最多读取 96 KB 文本预览以核对搜索摘要漏掉的电站、
年份和指标；不保存原文、不创建归档，也不触发解析或入库。
403/429 不直接判死，因为采集路由可以改用浏览器回退处理它们。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Iterable
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class UrlProbe:
    """对来源候选进行有界、无内容下载的访问预检。"""

    def __init__(self, *, timeout: float = 10.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    @staticmethod
    def _html_preview(response: requests.Response, *, limit: int = 96 * 1024) -> str:
        """从可访问 HTML 响应提取受限预览，供相关性验证而非数据采集使用。"""
        return UrlProbe._inspect_html(response, limit=limit)[0]

    @staticmethod
    def _inspect_html(response: requests.Response, *, limit: int = 96 * 1024) -> tuple[str, list[dict[str, str]]]:
        """一次读取受限 HTML，返回文字预览和最多 50 条公开链接。"""
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=16 * 1024):
                if not chunk:
                    continue
                remaining = limit - size
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
                if size >= limit:
                    break
        except (AttributeError, requests.RequestException):
            return "", []
        if not chunks:
            return "", []
        raw = b"".join(chunks)
        declared = str(getattr(response, "encoding", "") or "")
        encoding = declared if declared and not re.match(r"^(?:iso-8859-1|latin-1)$", declared, re.I) else None
        soup = BeautifulSoup(raw, "html.parser", from_encoding=encoding)
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        base_url = str(getattr(response, "url", "") or "")
        for anchor in soup.find_all("a", href=True):
            url = urljoin(base_url, str(anchor.get("href") or "").strip())
            if not url.startswith(("https://", "http://")) or url in seen:
                continue
            seen.add(url)
            links.append({"url": url, "text": anchor.get_text(" ", strip=True)[:500]})
            if len(links) >= 50:
                break
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:12000], links

    @staticmethod
    def _official_pdf_preview(response: requests.Response, *, limit: int = 2 * 1024 * 1024) -> str:
        """从小型官方公告 PDF 读取受限文本证据，不保存文件也不触发正式采集。"""
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ImportError:
            return ""
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                remaining = limit - size
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
                if size >= limit:
                    break
            reader = PdfReader(BytesIO(b"".join(chunks)))
            text = " ".join((page.extract_text() or "") for page in reader.pages[:12])
            return re.sub(r"\s+", " ", text).strip()[:16000]
        except (AttributeError, OSError, ValueError, PyPdfError, requests.RequestException):
            return ""

    def probe(self, candidate: dict) -> dict:
        url = candidate["url"]
        response = None
        try:
            response = self.session.get(
                url,
                stream=True,
                allow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": "HydroPlatform/1.0 (+source-discovery-probe)"},
            )
            http_status = int(response.status_code)
            final_url = response.url or url
            metadata = dict(candidate.get("metadata") or {})
            content_type = str((getattr(response, "headers", {}) or {}).get("Content-Type") or "").lower()
            is_pdf = (
                "pdf" in content_type
                or str(candidate.get("document_type") or "").lower() == "pdf"
                or final_url.lower().split("?", 1)[0].endswith(".pdf")
            )
            declared_pdf = (
                str(candidate.get("document_type") or "").lower() == "pdf"
                or final_url.lower().split("?", 1)[0].endswith(".pdf")
            )
            pdf_html_challenge = bool(
                200 <= http_status < 400 and declared_pdf and "html" in content_type
            )
            if 200 <= http_status < 400 and "html" in content_type and not declared_pdf:
                preview, links = self._inspect_html(response)
                if links:
                    metadata["discovered_links"] = links
            elif pdf_html_challenge:
                # 部分官方公告 CDN（例如交易所）对脚本/非浏览器请求返回
                # HTTP 200 的挑战页，而不是 PDF。保留候选并交给浏览器回退，
                # 不能把挑战页当作“可读取的 PDF”或静默判成内容不相关。
                preview, links = self._inspect_html(response)
                metadata["document_mismatch"] = "expected_pdf_received_html"
                if links:
                    metadata["discovered_links"] = links
            elif (
                200 <= http_status < 400
                and is_pdf
            ):
                # 来源发现只读取最多 2 MB/前 12 页的正文预览，用于补足搜索
                # 摘要没有电站名/年份的情况；正式采集仍由 Pipeline 单独下载。
                preview = self._official_pdf_preview(response)
            else:
                preview = ""
            if preview:
                metadata["content_preview"] = preview
            if pdf_html_challenge:
                access_status, status = "requires_browser", "discovered"
                error = "HTTP 200：PDF 链接返回 HTML，需要浏览器验证"
            elif 200 <= http_status < 400:
                access_status, status, error = "reachable", "discovered", None
            elif http_status in (401, 403, 429):
                # 这类链接不能被 HTTP 直接读取，但值得交给已接入的浏览器回退。
                access_status, status, error = "requires_browser", "discovered", f"HTTP {http_status}：需要浏览器回退验证"
            else:
                access_status, status, error = "unavailable", "unavailable", f"HTTP {http_status}"
            return {
                **candidate,
                "access_status": access_status,
                "status": status,
                "http_status": http_status,
                "final_url": final_url,
                "error": error,
                "metadata": metadata,
            }
        except requests.RequestException as exc:
            return {
                **candidate,
                "access_status": "unknown",
                "status": "unavailable",
                "http_status": None,
                "final_url": url,
                "error": f"访问探测失败：{exc.__class__.__name__}",
            }
        finally:
            if response is not None:
                response.close()

    def probe_many(self, candidates: Iterable[dict], *, max_workers: int = 4) -> list[dict]:
        """并行探测，保持输入顺序，限制并发避免对站点造成压力。"""
        items = list(candidates)
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
            return list(executor.map(self.probe, items))
