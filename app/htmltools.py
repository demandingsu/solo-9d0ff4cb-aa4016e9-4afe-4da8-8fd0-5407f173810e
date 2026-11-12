"""极简 HTML 解析工具（仅依赖标准库 html.parser）。

提供：
- parse_html: 把 HTML 文本解析为一棵轻量 DOM 树
- Node.text_content / Node.iter: 文本与遍历
- extract_links: 抽取全部超链接
- extract_fields: 按中文标签抽取“标签: 值”形式的字段（兼容 table / dt-dd / div 等结构）
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# 内容原样保留、不需要解析子元素的标签
RAW_TAGS = {"script", "style"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "data", "tokens")

    def __init__(self, tag: str, attrs=None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = {k: (v or "") for k, v in (attrs or [])}
        self.children: list[Node] = []
        self.parent = parent
        self.data = ""
        # 按文档顺序记录文本片段与子节点，保证混合内容顺序正确
        self.tokens: list[str | Node] = []

    def text_content(self) -> str:
        return "".join(
            tok if isinstance(tok, str) else tok.text_content()
            for tok in self.tokens
        )

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def __repr__(self):
        return f"<Node {self.tag}>"


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack: list[Node] = [self.root]
        self._raw_tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if self._raw_tag is not None:
            return
        node = Node(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].tokens.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)
        if tag in RAW_TAGS:
            self._raw_tag = tag

    def handle_startendtag(self, tag, attrs):
        if self._raw_tag is not None:
            return
        node = Node(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].tokens.append(node)

    def handle_endtag(self, tag):
        if self._raw_tag is not None:
            if tag == self._raw_tag:
                self._raw_tag = None
                # script/style 节点本身仍在栈上
                if self.stack and self.stack[-1].tag == tag:
                    self.stack.pop()
            return
        # 容错：向上找到最近的同名标签再闭合
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._raw_tag is not None:
            return
        current = self.stack[-1]
        current.data += data
        current.tokens.append(data)


def parse_html(markup: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(markup or "")
    builder.close()
    return builder.root


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def extract_links(root: Node) -> list[dict]:
    """返回 [{href, text, rel}]，href 为页面中的原始值（可能是相对链接）。"""
    links = []
    for node in root.iter():
        if node.tag != "a":
            continue
        href = node.attrs.get("href")
        if not href:
            continue
        links.append({
            "href": href.strip(),
            "text": _clean(node.text_content()),
            "rel": node.attrs.get("rel", ""),
        })
    return links


def _sibling_value(node: Node) -> str | None:
    """标签独占一个单元格/节点时，从相邻节点或父节点剩余文本中取值。"""
    parent = node.parent
    if parent is None:
        return None
    try:
        idx = parent.children.index(node)
    except ValueError:
        idx = -1
    # 1) 相邻元素节点（th->td、dt->dd、span->span 等）
    for sibling in parent.children[idx + 1:]:
        text = _clean(sibling.text_content())
        if text:
            return text
    # 2) 父节点自身承载的剩余文本，例如 <div><b>名称：</b>某某公司</div>
    #    解析后裸文本可能出现在标签前后，因此不锚定行首，替换后必须发生变化才采用
    parent_text = _clean(parent.text_content())
    label_text = _clean(node.text_content())
    pattern = rf"{re.escape(label_text.rstrip('：:'))}\s*(?:[:：])?\s*(.*)"
    remainder = _clean(re.sub(pattern, r"\1", parent_text, count=1, flags=re.S))
    if remainder and remainder != parent_text:
        return remainder
    return None


def extract_fields(markup: str, labels: list[str]) -> dict[str, str]:
    """按标签抽取字段值。

    覆盖常见版式：
      <td>统一社会信用代码：9131...</td>
      <th>供应商名称</th><td>某某公司</td>
      <dt>曾用名</dt><dd>旧名称</dd>
      <div><span>供应商名称：</span>某某公司</div>
    同一标签命中多处时，取最具体（文本最短）的节点，避免拿到整页文本。
    """
    root = parse_html(markup)
    best: dict[str, tuple[int, str]] = {}

    def offer(label: str, score: int, value: str):
        value = _clean(value)
        if not value:
            return
        current = best.get(label)
        if current is None or score < current[0]:
            best[label] = (score, value)

    for node in root.iter():
        text = _clean(node.text_content())
        if not text:
            continue
        for label in labels:
            # 同一节点内 “标签: 值”。值组先吃掉可选冒号，再取内容，
            # 避免标签自带“：”时把冒号本身当成值
            match = re.match(
                rf"^{re.escape(label)}\s*(?:[:：]\s*)?(?P<v>[^：:].*?)\s*$",
                text,
            )
            if match:
                offer(label, len(text), match.group("v"))
            # 标签独占节点，值在相邻节点 / 父节点剩余文本
            if text in (label, f"{label}：", f"{label}:"):
                value = _sibling_value(node)
                if value:
                    offer(label, len(text) + 1, value)

    return {label: best[label][1] for label in labels if label in best}
