"""供应商归一核对工具包。"""
from .normalize import (
    Record, Group, PendingRecord, BuildResult,
    build_groups, normalize_name, normalize_code, split_former_names,
)
from .crawler import crawl, CrawlReport, FetchFailure

__all__ = [
    "Record", "Group", "PendingRecord", "BuildResult",
    "build_groups", "normalize_name", "normalize_code", "split_former_names",
    "crawl", "CrawlReport", "FetchFailure",
]
