"""中标公告目录抓取器。

流程：
  输入目录 URL -> 同站 BFS 抓取目录页 -> 沿分页链接翻页 -> 进入公告详情页，
  抽取现名、曾用名、统一社会信用代码。

约束：
- 只跟随同站（scheme + host[:port] 相同）的 http/https 链接；
- 静态资源链接不抓取；
- 任何页面抓取失败都登记到 failures，由页面提示“名录可能不完整”；
- 跨站重定向按失败处理；
- 设置页数/详情数上限，超限置 truncated=True。
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .htmltools import parse_html, extract_links, extract_fields, _clean
from .normalize import Record, normalize_code, split_former_names

NAME_LABELS = [
    "中标（成交）供应商名称", "中标供应商名称", "成交供应商名称",
    "中标人名称", "成交人名称", "供应商名称", "供应商",
]
FORMER_LABELS = ["曾用名", "原名", "历史名称", "变更前名称"]
CODE_LABELS = [
    "统一社会信用代码（组织机构代码）", "统一社会信用代码",
    "社会信用代码", "信用代码",
]

_STATIC_EXT = re.compile(
    r"\.(?:css|js|mjs|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|eot|"
    r"pdf|docx?|xlsx?|zip|rar|7z|mp4|mp3|txt|xml|json)(?:$|[?#])",
    re.IGNORECASE,
)
_DETAIL_HINT = re.compile(r"(detail|announce|announcement|notice|bid|gonggao|"
                          r"news|info|view|item|/a/|/n/|/\d+)", re.IGNORECASE)


@dataclass
class FetchFailure:
    url: str
    kind: str          # detail | listing
    error: str

    def to_dict(self) -> dict:
        return {"url": self.url, "kind": self.kind, "error": self.error}


@dataclass
class CrawlReport:
    start_url: str
    records: list[Record] = field(default_factory=list)
    failures: list[FetchFailure] = field(default_factory=list)
    visited_pages: list[str] = field(default_factory=list)
    truncated: bool = False
    limit_pages: int = 0
    limit_details: int = 0

    @property
    def incomplete(self) -> bool:
        return bool(self.failures) or self.truncated

    def to_dict(self) -> dict:
        return {
            "start_url": self.start_url,
            "records": [r.to_dict() for r in self.records],
            "failures": [f.to_dict() for f in self.failures],
            "visited_pages": self.visited_pages,
            "truncated": self.truncated,
            "incomplete": self.incomplete,
            "limits": {
                "pages": self.limit_pages,
                "details": self.limit_details,
                "visited": len(self.visited_pages),
            },
        }


def _same_site(url_a: str, url_b: str) -> bool:
    a, b = urllib.parse.urlsplit(url_a), urllib.parse.urlsplit(url_b)
    return (a.scheme.lower() == b.scheme.lower()
            and a.netloc.lower() == b.netloc.lower())


def _candidate_url(base: str, href: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    url = urllib.parse.urljoin(base, href)
    url = urllib.parse.urldefrag(url)[0]
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if _STATIC_EXT.search(parts.path):
        return None
    return url


def _fetch(url: str, timeout: float) -> tuple[str, str]:
    """返回 (最终URL, 解码后的HTML文本)。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "supplier-normalizer/1.0 (offline audit tool)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type)
    if match:
        charset = match.group(1)
    try:
        return final_url, raw.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return final_url, raw.decode("utf-8", errors="replace")


def _page_title(root) -> str:
    for node in root.iter():
        if node.tag in ("title", "h1"):
            text = _clean(node.text_content())
            if text:
                return text
    return ""


def _parse_detail(url: str, html: str) -> Record:
    all_labels = NAME_LABELS + FORMER_LABELS + CODE_LABELS
    fields = extract_fields(html, all_labels)

    name = next((fields[lbl] for lbl in NAME_LABELS if lbl in fields), "")
    former_raw = next((fields[lbl] for lbl in FORMER_LABELS if lbl in fields), "")
    code_raw = next((fields[lbl] for lbl in CODE_LABELS if lbl in fields), "")

    root = parse_html(html)
    title = _page_title(root)
    return Record(
        page_url=url,
        title=title,
        current_name=name,
        former_names=split_former_names(former_raw),
        code=normalize_code(code_raw),
        source_announcement=title or url,
    )


def crawl(start_url: str, *, timeout: float = 10.0,
          max_pages: int = 100, max_details: int = 200) -> CrawlReport:
    report = CrawlReport(start_url=start_url,
                         limit_pages=max_pages, limit_details=max_details)
    start_parts = urllib.parse.urlsplit(start_url)
    if start_parts.scheme not in ("http", "https") or not start_parts.netloc:
        raise ValueError("URL 必须是 http/https 且包含主机名")

    from collections import deque
    queue: deque[str] = deque([start_url])
    seen: set[str] = set()
    detail_urls: set[str] = set()     # 按链接特征判定为详情页的 URL
    detail_seen: set[str] = set()

    while queue:
        if len(report.visited_pages) >= max_pages or len(detail_seen) >= max_details:
            report.truncated = True
            break

        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        try:
            final_url, html = _fetch(url, timeout)
            if not _same_site(start_url, final_url):
                raise ValueError(f"重定向到跨站地址: {final_url}")
        except (urllib.error.URLError, urllib.error.HTTPError,
                ValueError, TimeoutError, OSError) as exc:
            kind = "detail" if url in detail_urls else "listing"
            report.failures.append(FetchFailure(url=url, kind=kind,
                                                error=str(exc)))
            continue

        report.visited_pages.append(url)
        root = parse_html(html)
        fields = extract_fields(html, NAME_LABELS)

        if fields:  # 详情页：抽取记录，叶子页不再向外扩展
            if url not in detail_seen:
                detail_seen.add(url)
                rec = _parse_detail(url, html)
                if not rec.title:
                    rec.title = _page_title(root)
                    rec.source_announcement = rec.title or url
                report.records.append(rec)
            continue

        # 目录页：收集详情链接与分页链接
        for link in extract_links(root):
            target = _candidate_url(final_url, link["href"])
            if target is None or target in seen:
                continue
            if not _same_site(start_url, target):
                continue
            href_path = urllib.parse.urlsplit(target).path + "?" + \
                        urllib.parse.urlsplit(target).query
            if _DETAIL_HINT.search(href_path):
                detail_urls.add(target)
            queue.append(target)

    return report
