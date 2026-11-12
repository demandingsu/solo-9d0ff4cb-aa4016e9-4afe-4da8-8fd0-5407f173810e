"""供应商名称归一与分组。

分组规则（与需求一一对应）：
1. 统一社会信用代码相同的记录归入同一组，代码是权威依据。
2. 名称->代码组 的映射索引**只由带代码记录**的现名/曾用名建立；
   无代码记录不参与建索引，因此不可能借无代码记录把两个代码组串联。
3. 无代码记录：
   - 其名称（公告中的现名、曾用名）若全部唯一指向同一个代码组 -> 归入该组；
   - 指向多个不同代码组 -> 列为“待核实”；
   - 没有任何名称能对上代码组 -> 列为“待核实”。
4. 带代码记录之间若存在同名冲突（同一名称指向多个代码），该名称从索引中剔除，
   后续匹配视为多义，同样不会发生串组。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 统一社会信用代码：18 位，数字与大写字母（排除 I O S V Z 的校验由数据方负责，
# 这里只做长度与字符集的保守校验）
_CODE_RE = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")

# 名称归一：去除空白与全/半角括号差异
_PAREN_MAP = str.maketrans({"（": "(", "）": ")", "【": "[", "】": "]",
                            "　": " ", "　": " "})


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).translate(_PAREN_MAP)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def normalize_code(code: str | None) -> str:
    if not code:
        return ""
    text = re.sub(r"\s+", "", str(code)).upper()
    return text if _CODE_RE.match(text) else ""


# 表示“没有曾用名”的占位措辞
_EMPTY_NAME_WORDS = {"无", "暂无", "无曾用名", "无历史名称", "—", "-", "/", "N/A", "NA"}


def split_former_names(raw: str | None) -> list[str]:
    """拆分曾用名字段中的多个名称，过滤“无/暂无”等空值措辞。"""
    if not raw:
        return []
    parts = re.split(r"[、,;；，/\n\r]|(?<!\d)\s{1,}(?!\d)", raw)
    out = []
    for part in parts:
        name = part.strip(" ：:、,;；，/")
        if name and name not in _EMPTY_NAME_WORDS:
            out.append(name)
    return out


@dataclass
class Record:
    """一条公告详情抽取结果。"""
    page_url: str
    title: str = ""
    current_name: str = ""
    former_names: list[str] = field(default_factory=list)
    code: str = ""            # 已归一化；空字符串表示无有效信用代码
    source_announcement: str = ""

    @property
    def all_names(self) -> list[str]:
        names = []
        if self.current_name:
            names.append(self.current_name)
        names.extend(self.former_names)
        return names

    def to_dict(self) -> dict:
        return {
            "page_url": self.page_url,
            "title": self.title,
            "current_name": self.current_name,
            "former_names": self.former_names,
            "code": self.code,
            "source_announcement": self.source_announcement,
        }


@dataclass
class Group:
    code: str
    names: set[str] = field(default_factory=set)          # 组内出现过的全部名称（原文）
    records: list[Record] = field(default_factory=list)   # 含后归入的无代码记录

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "names": sorted(self.names),
            "records": [r.to_dict() for r in self.records],
            "announcement_sources": sorted({
                r.source_announcement or r.page_url for r in self.records
            }),
        }


@dataclass
class PendingRecord:
    record: Record
    reason: str                       # ambiguous | unmatched
    candidate_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = self.record.to_dict()
        data["reason"] = self.reason
        data["candidate_codes"] = self.candidate_codes
        return data


@dataclass
class BuildResult:
    groups: list[Group]
    pending: list[PendingRecord]

    def to_dict(self) -> dict:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "pending": [p.to_dict() for p in self.pending],
        }


def build_groups(records: list[Record]) -> BuildResult:
    # 1) 带代码记录建组
    groups_by_code: dict[str, Group] = {}
    # 归一化名称 -> 命中的代码集合（先收集，多义名称稍后剔除）
    name_to_codes: dict[str, set[str]] = {}

    for rec in records:
        if not rec.code:
            continue
        group = groups_by_code.setdefault(rec.code, Group(code=rec.code))
        group.records.append(rec)
        for name in rec.all_names:
            norm = normalize_name(name)
            if not norm:
                continue
            group.names.add(name)
            name_to_codes.setdefault(norm, set()).add(rec.code)

    # 2) 剔除多义名称：带代码记录之间同一名称指向多个代码 -> 名称不参与自动匹配
    resolved_index: dict[str, str] = {}
    ambiguous_names: set[str] = set()
    for norm, codes in name_to_codes.items():
        if len(codes) == 1:
            resolved_index[norm] = next(iter(codes))
        else:
            ambiguous_names.add(norm)

    # 3) 无代码记录匹配（只读索引，绝不回写，杜绝串组）
    pending: list[PendingRecord] = []
    for rec in records:
        if rec.code:
            continue
        hits: set[str] = set()
        matched_any = False
        for name in rec.all_names:
            norm = normalize_name(name)
            if not norm:
                continue
            if norm in ambiguous_names:
                matched_any = True
                hits.update(name_to_codes[norm])
            elif norm in resolved_index:
                matched_any = True
                hits.add(resolved_index[norm])

        if len(hits) == 1:
            code = next(iter(hits))
            group = groups_by_code[code]
            group.records.append(rec)
            for name in rec.all_names:
                if name:
                    group.names.add(name)
        elif len(hits) > 1:
            pending.append(PendingRecord(
                record=rec,
                reason="ambiguous",
                candidate_codes=sorted(hits),
            ))
        else:
            pending.append(PendingRecord(
                record=rec,
                reason="unmatched",
                candidate_codes=[],
            ))

    groups = sorted(groups_by_code.values(), key=lambda g: g.code)
    pending.sort(key=lambda p: (p.reason, p.record.page_url))
    return BuildResult(groups=groups, pending=pending)
