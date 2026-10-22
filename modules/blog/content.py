"""Validate, measure, and render plain story blocks. Stored JSON is never HTML."""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from modules.blog.errors import ApiError
from modules.blog.textutil import calc_read_time

UPLOAD_PREFIX = "/blog/backend/uploads/"
MEDIA_PREFIX = "/media/blog/"
_upload_origin: ContextVar[str] = ContextVar("upload_origin", default="")
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac")
VIDEO_EXT = (".mp4", ".webm", ".ogv")
CODE_LANGUAGES = {"text", "python", "javascript", "html", "css", "sql", "bash", "json"}
PALETTE = ("#cc203b", "#8fd4c8", "#ffffff", "#f4faf8", "#ffd166", "#9ecbff")
FONT_FAMILIES = {
    "Arial": "Arial, Helvetica, sans-serif",
    "Georgia": "Georgia, serif",
    "Times New Roman": '"Times New Roman", Times, serif',
}
FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 96
_FONT_SIZE = re.compile(r"^(\d+)px$")
_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SECTION_DEFAULT_BG = "#eff6ff"
MAX_BLOCKS = 200
# Highlight colours offered by the editor (Tiptap template names -> light background).
HIGHLIGHTS = {
    "gray": "#f8f8f7",
    "brown": "#f4eeee",
    "orange": "#fbecdd",
    "yellow": "#fef9c3",
    "green": "#dcfce7",
    "blue": "#e0f2fe",
    "purple": "#f3e8ff",
    "pink": "#fcf1f6",
    "red": "#ffe4e6",
}
ALIGNS = {"left", "center", "right", "justify"}
_SIMPLE_MARKS = {"bold", "italic", "code", "underline", "strike", "subscript", "superscript"}
_INLINE = {"strong", "em", "b", "i", "u", "s", "strike", "del", "mark", "a", "span", "font", "small", "sub", "sup", "code"}
_PALETTE = {color.lower(): color for color in PALETTE}
_PALETTE_RGB = {tuple(int(color[index:index + 2], 16) for index in (1, 3, 5)): color for color in PALETTE}
_COLOR_STYLE = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.I)
_FONT_FAMILY_STYLE = re.compile(r"(?:^|;)\s*font-family\s*:\s*([^;]+)", re.I)
_FONT_SIZE_STYLE = re.compile(r"(?:^|;)\s*font-size\s*:\s*([^;]+)", re.I)
_RGB_COLOR = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", re.I)
_SKIP = {"script", "style"}
_VOID = {"br", "img", "hr", "wbr", "source"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_TAGS = _HEADING_TAGS | {"p", "blockquote"}
_ALLOWED_TAGS = _TEXT_TAGS | {"ul", "ol", "table", "hr", "img", "video", "audio", "pre", "section"}


class _Node:
    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag = tag
        self.attrs = {key.lower(): (value or "") for key, value in attrs}
        self.children: list[_Node | str] = []


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", [])
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip or tag in _VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.skip or not data:
            return
        self.stack[-1].children.append(data)


def html_to_blocks(html: str) -> list[dict]:
    parser = _Tree()
    parser.feed(html or "")
    parser.close()
    blocks: list[dict] = []
    _walk(parser.root, blocks)
    return blocks


def convert_content(value) -> list[dict]:
    """Turn HTML, a legacy block document, or a block array into plain blocks."""
    decoded = _decode_json(value)
    if decoded is None or decoded == "":
        return []
    if isinstance(decoded, dict):
        raw = decoded.get("blocks")
        if isinstance(raw, list):
            return _convert_blocks(raw)
        return []
    if isinstance(decoded, list):
        return _convert_blocks(decoded)
    if isinstance(decoded, str):
        return html_to_blocks(decoded)
    return []


def _block_weight(block: dict) -> int:
    """Count a block and any nested section children toward MAX_BLOCKS."""
    if block.get("tag") == "section":
        children = block.get("content") or []
        return 1 + sum(_block_weight(child) for child in children if isinstance(child, dict))
    return 1


def normalize_blocks(value, site_url: str | None = None) -> list[dict]:
    token = _upload_origin.set((site_url or "").rstrip("/"))
    try:
        items = _raw_items(value)
        blocks: list[dict] = []
        total = 0
        for item in items:
            shaped = _strict_one(item)
            for block in shaped:
                total += _block_weight(block)
                if total > MAX_BLOCKS:
                    raise ApiError("Too many content blocks")
                blocks.append(block)
        return blocks
    finally:
        _upload_origin.reset(token)


def blocks_are_empty(blocks: list) -> bool:
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        tag = block.get("tag")
        if tag == "section":
            if not blocks_are_empty(block.get("content") or []):
                return False
            continue
        if tag in _TEXT_TAGS and _cell_text(block).strip():
            return False
        if tag in {"ul", "ol"} and any(_cell_text(item).strip() for item in block.get("items") or []):
            return False
        if tag == "table" and _table_has_text(block):
            return False
        if tag == "img" and _attr(block, "src"):
            return False
        if tag == "pre" and _cell_text(block).strip():
            return False
        if tag in {"audio", "video"} and _attr(block, "src"):
            return False
    return True


def story_chars(blocks) -> int:
    """Visible story text, without the spaces reading_text inserts between blocks."""
    total = 0
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        tag = block.get("tag")
        if tag == "section":
            total += story_chars(block.get("content") or [])
        elif tag in _TEXT_TAGS:
            total += len(_cell_text(block))
        elif tag == "pre":
            total += len(_cell_text(block))
        elif tag in {"ul", "ol"}:
            total += sum(len(_cell_text(item)) for item in block.get("items") or [])
        elif tag == "table":
            total += sum(len(_cell_text(cell)) for cell in block.get("headers") or [])
            for row in block.get("rows") or []:
                total += sum(len(_cell_text(cell)) for cell in row or [])
    return total


def reading_text(blocks) -> str:
    if isinstance(blocks, dict) or isinstance(blocks, str):
        blocks = convert_content(blocks)
    parts: list[str] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        tag = block.get("tag")
        if tag == "section":
            nested = reading_text(block.get("content") or [])
            if nested:
                parts.append(nested)
        elif tag in _TEXT_TAGS:
            parts.append(_cell_text(block))
        elif tag == "pre":
            parts.append(_cell_text(block))
        elif tag in {"ul", "ol"}:
            parts.extend(_cell_text(item) for item in block.get("items") or [])
        elif tag == "table":
            parts.extend(_cell_text(cell) for cell in block.get("headers") or [])
            for row in block.get("rows") or []:
                parts.extend(_cell_text(cell) for cell in row or [])
    return " ".join(part for part in parts if part)


def read_minutes(blocks) -> int:
    return calc_read_time(reading_text(blocks))


def render_blocks(blocks) -> str:
    if isinstance(blocks, dict) or isinstance(blocks, str):
        blocks = convert_content(blocks)
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)
    return "\n".join(parts)


def parse_keyword_value(value) -> list[str] | None:
    """Normalize a stored keyword list from text[], JSON, or comma-separated text."""
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(part).strip() for part in value if str(part).strip()]
        return items or None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            items = [str(part).strip() for part in loaded if str(part).strip()]
            return items or None
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return None
        items = [part.strip().strip('"') for part in inner.split(",") if part.strip().strip('"')]
        return items or None
    items = [part.strip() for part in text.split(",") if part.strip()]
    return items or None


def _decode_json(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text[0] not in "[{":
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _raw_items(value) -> list:
    if value is None:
        raise ApiError("Field 'content' is required")
    if not isinstance(value, list):
        raise ApiError("Content must be a list of blocks")
    return value


def _strict_one(item) -> list[dict]:
    if not isinstance(item, dict):
        raise ApiError("Content must be a list of blocks")
    shaped = _shape_block(item, strict=True)
    if shaped is None:
        raise ApiError("Unknown content block")
    if isinstance(shaped, list):
        return [_validate(block) for block in shaped]
    return [_validate(shaped)]


def _convert_blocks(items: list) -> list[dict]:
    blocks: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        shaped = _shape_block(item)
        if shaped is None:
            continue
        if isinstance(shaped, list):
            blocks.extend(shaped)
        else:
            blocks.append(shaped)
    return blocks


def _section_background_color(value, strict: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return SECTION_DEFAULT_BG
    if not _HEX_COLOR.match(text):
        if strict:
            raise ApiError("Section backgroundColor must be a hex color like #rgb or #rrggbb")
        return SECTION_DEFAULT_BG
    if len(text) == 4:
        _, r, g, b = text
        text = f"#{r}{r}{g}{g}{b}{b}"
    return text.lower()


def _block_attrs(block: dict) -> dict:
    attrs = block.get("attributes")
    return attrs if isinstance(attrs, dict) else {}


def _block_style(block: dict) -> dict:
    style = _block_attrs(block).get("style")
    return style if isinstance(style, dict) else {}


def _attr(block: dict, key: str) -> str:
    return str(_block_attrs(block).get(key) or "").strip()


def _section_bg_from(block: dict):
    style = _block_style(block)
    if "backgroundColor" in style:
        return style.get("backgroundColor")
    return None


def _text_align_from(block: dict) -> str | None:
    return _align(_block_style(block).get("textAlign"))


def _is_task_list(block: dict) -> bool:
    if block.get("tag") != "ul":
        return False
    return str(_block_attrs(block).get("listType") or "").strip().lower() == "task"


def _shape_section_children(raw, strict: bool = False) -> list[dict] | None:
    if not isinstance(raw, list):
        if strict:
            raise ApiError("Section content must be a list of blocks")
        return None
    children: list[dict] = []
    for child in raw:
        if not isinstance(child, dict):
            if strict:
                raise ApiError("Section content must be a list of blocks")
            continue
        if str(child.get("tag") or "").strip().lower() == "section":
            if strict:
                raise ApiError("Sections cannot be nested")
            continue
        shaped = _shape_block(child, strict=strict)
        if shaped is None:
            if strict:
                raise ApiError("Unknown content block")
            continue
        if isinstance(shaped, list):
            children.extend(shaped)
        else:
            children.append(shaped)
    return children


def _shape_block(item: dict, strict: bool = False):
    tag = str(item.get("tag") or "").strip().lower()
    if tag not in _ALLOWED_TAGS:
        return None
    if tag == "section":
        children = _shape_section_children(item.get("content"), strict=strict)
        if children is None:
            return None
        if not children:
            return None
        return {
            "tag": "section",
            "attributes": {
                "style": {
                    "backgroundColor": _section_background_color(_section_bg_from(item), strict=strict),
                }
            },
            "content": children,
        }
    if tag in _TEXT_TAGS:
        return _shape_text(tag, item, strict)
    if tag in {"ul", "ol"}:
        raw_items = item.get("items") or []
        legacy_checked = item.get("checked") if isinstance(item.get("checked"), list) else []
        is_task = tag == "ul" and _is_task_list(item)
        pairs = []
        for index, part in enumerate(raw_items):
            cell = _shape_cell(part, strict)
            if not _cell_text(cell).strip():
                continue
            done = _item_checked(part, legacy_checked, index) if is_task else False
            pairs.append((cell, done))
        if not pairs:
            return None
        return _list_block(
            tag,
            [part for part, _ in pairs],
            [done for _, done in pairs],
            is_task=is_task,
        )
    if tag == "table":
        headers = [_shape_cell(cell, strict) for cell in item.get("headers") or []]
        rows = []
        for row in item.get("rows") or []:
            if not isinstance(row, (list, tuple)):
                continue
            rows.append([_shape_cell(cell, strict) for cell in row])
        if not any(_cell_text(cell).strip() for cell in headers) and not any(
            any(_cell_text(cell).strip() for cell in row) for row in rows
        ):
            return None
        return {"tag": "table", "headers": headers, "rows": rows}
    if tag == "hr":
        return {"tag": "hr"}
    if tag == "img":
        return {
            "tag": "img",
            "attributes": {
                "src": _attr(item, "src"),
                "alt": _alt(_block_attrs(item).get("alt")),
            },
        }
    if tag == "pre":
        text = _cell_text(item)
        if not text.strip():
            return None
        language = str(_block_attrs(item).get("language") or "text").strip().lower()
        if language not in CODE_LANGUAGES:
            language = "text"
        return {"tag": "pre", "text": text, "attributes": {"language": language}}
    if tag == "audio":
        return {"tag": "audio", "attributes": {"src": _attr(item, "src")}}
    if tag == "video":
        return {"tag": "video", "attributes": {"src": _attr(item, "src")}}
    return None


def _validate(block: dict) -> dict:
    tag = block.get("tag")
    if tag == "section":
        children = [_validate(child) for child in block.get("content") or [] if isinstance(child, dict)]
        if not children:
            raise ApiError("Section content must be a list of blocks")
        if any(child.get("tag") == "section" for child in children):
            raise ApiError("Sections cannot be nested")
        return {
            "tag": "section",
            "attributes": {
                "style": {
                    "backgroundColor": _section_background_color(_section_bg_from(block), strict=True),
                }
            },
            "content": children,
        }
    if tag in _TEXT_TAGS:
        return _pack_text(tag, block, 100_000, "A text block is too long")
    if tag in {"ul", "ol"}:
        is_task = _is_task_list(block)
        legacy_checked = block.get("checked") if isinstance(block.get("checked"), list) else []
        raw_items = block.get("items") or []
        items = []
        flags = []
        for index, part in enumerate(raw_items):
            cell = _pack_cell(part, 100_000, "A text block is too long")
            items.append(cell)
            if is_task:
                flags.append(_item_checked(part, legacy_checked, index))
        return _list_block(tag, items, flags, is_task=is_task)
    if tag == "table":
        headers = [_pack_cell(cell, 10_000, "A table cell is too long") for cell in block.get("headers") or []]
        rows = [
            [_pack_cell(cell, 10_000, "A table cell is too long") for cell in row]
            for row in block.get("rows") or []
        ]
        return {"tag": "table", "headers": headers, "rows": rows}
    if tag == "hr":
        return {"tag": "hr"}
    if tag == "img":
        return {
            "tag": "img",
            "attributes": {
                "src": _optional_media(_attr(block, "src"), "image"),
                "alt": _alt(_block_attrs(block).get("alt")),
            },
        }
    if tag == "pre":
        language = str(_block_attrs(block).get("language") or "text").strip().lower()
        if language not in CODE_LANGUAGES:
            language = "text"
        return {
            "tag": "pre",
            "text": _limit(_cell_text(block), 50_000, "A code block is too long"),
            "attributes": {"language": language},
        }
    if tag == "audio":
        return {"tag": "audio", "attributes": {"src": _optional_media(_attr(block, "src"), "audio")}}
    if tag == "video":
        return {"tag": "video", "attributes": {"src": _optional_media(_attr(block, "src"), "video")}}
    raise ApiError("Unknown content block")


def _limit(value: str, limit: int, message: str) -> str:
    text = str(value)
    if len(text) > limit:
        raise ApiError(message)
    return text


def _item_checked(part, legacy_checked, index: int) -> bool:
    """Prefer per-item checked; fall back to legacy parallel checked array."""
    if isinstance(part, dict) and "checked" in part:
        return bool(part.get("checked"))
    if isinstance(legacy_checked, list) and index < len(legacy_checked):
        return bool(legacy_checked[index])
    return False


def _list_block(tag: str, items: list, checked: list[bool], is_task: bool = False) -> dict:
    if is_task and tag == "ul":
        task_items = []
        for index, item in enumerate(items):
            cell = dict(item) if isinstance(item, dict) else {"text": str(item or ""), "marks": []}
            cell["checked"] = bool(checked[index]) if index < len(checked) else False
            task_items.append(cell)
        return {"tag": "ul", "attributes": {"listType": "task"}, "items": task_items}
    plain_items = []
    for item in items:
        if isinstance(item, dict):
            plain_items.append({"text": _cell_text(item), "marks": list(item.get("marks") or [])})
        else:
            plain_items.append({"text": str(item or ""), "marks": []})
    return {"tag": tag, "items": plain_items}


def _align(value) -> str | None:
    """Stored only when it is not the default (left)."""
    text = str(value or "").strip().lower()
    return text if text in ALIGNS and text != "left" else None


def _align_attr(block: dict) -> str:
    align = _text_align_from(block)
    return f' style="text-align:{align}"' if align else ""


_LEGACY_KEYS = ("type", "url", "alt", "language", "code", "align", "level", "ordered", "backgroundColor")


def _strip_legacy(block: dict) -> dict:
    """Drop old type-based fields so API responses stay tag-only."""
    copy = {key: value for key, value in block.items() if key not in _LEGACY_KEYS}
    return copy


def present_blocks(blocks) -> list:
    if not isinstance(blocks, list):
        return []
    shown = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        tag = str(block.get("tag") or "").strip().lower()
        if tag not in _ALLOWED_TAGS:
            # Old type-only rows are not presented (breaking change; re-save required).
            continue
        if tag == "section":
            copy = _strip_legacy(block)
            copy["tag"] = "section"
            copy["content"] = present_blocks(block.get("content") or [])
            color = _section_background_color(_section_bg_from(block))
            copy["attributes"] = {"style": {"backgroundColor": color}}
            shown.append(copy)
            continue
        if tag in {"ul", "ol"}:
            copy = _strip_legacy(block)
            copy["tag"] = tag
            copy.pop("checked", None)
            if _is_task_list(block):
                legacy_checked = block.get("checked") if isinstance(block.get("checked"), list) else []
                copy["attributes"] = {"listType": "task"}
                copy["items"] = [
                    _present_task_cell(item, legacy_checked, index)
                    for index, item in enumerate(block.get("items") or [])
                ]
            else:
                copy["items"] = [_present_cell(item) for item in block.get("items") or []]
                attrs = dict(_block_attrs(block))
                attrs.pop("listType", None)
                if attrs:
                    copy["attributes"] = attrs
                else:
                    copy.pop("attributes", None)
            shown.append(copy)
            continue
        if tag == "table":
            copy = _strip_legacy(block)
            copy["tag"] = "table"
            copy["headers"] = [_present_cell(cell) for cell in block.get("headers") or []]
            copy["rows"] = [[_present_cell(cell) for cell in row or []] for row in block.get("rows") or []]
            shown.append(copy)
            continue
        if tag in _TEXT_TAGS or tag == "pre":
            copy = _strip_legacy(block)
            copy["tag"] = tag
            copy["text"] = _cell_text(block)
            copy.pop("content", None)
            if tag in _TEXT_TAGS:
                copy["marks"] = list(block.get("marks") or [])
                align = _text_align_from(block)
                if align:
                    copy["attributes"] = {"style": {"textAlign": align}}
                elif "attributes" in copy and tag != "pre":
                    attrs = dict(copy.get("attributes") or {})
                    style = dict(attrs.get("style") or {})
                    style.pop("textAlign", None)
                    if style:
                        attrs["style"] = style
                    else:
                        attrs.pop("style", None)
                    if attrs:
                        copy["attributes"] = attrs
                    else:
                        copy.pop("attributes", None)
            shown.append(copy)
            continue
        # hr / img / video / audio
        copy = _strip_legacy(block)
        copy["tag"] = tag
        shown.append(copy)
    return shown


def _present_cell(value) -> dict:
    if isinstance(value, dict):
        return {"text": _cell_text(value), "marks": list(value.get("marks") or [])}
    return {"text": str(value or ""), "marks": []}


def _present_task_cell(value, legacy_checked, index: int) -> dict:
    cell = _present_cell(value)
    cell["checked"] = _item_checked(value, legacy_checked, index)
    return cell


def _table_has_text(block: dict) -> bool:
    cells = [_cell_text(cell) for cell in block.get("headers") or []]
    for row in block.get("rows") or []:
        cells.extend(_cell_text(cell) for cell in row or [])
    return any(cell.strip() for cell in cells)


def _render_block(block: dict) -> str:
    tag = block.get("tag")
    if tag == "section":
        inner = []
        for child in block.get("content") or []:
            if not isinstance(child, dict):
                continue
            rendered = _render_block(child)
            if rendered:
                inner.append(rendered)
        if not inner:
            return ""
        color = escape(_section_background_color(_section_bg_from(block)), quote=True)
        return f'<div data-type="section" style="background-color:{color}">{"".join(inner)}</div>'
    if tag in _HEADING_TAGS or tag == "p":
        html = _inline(block, block.get("marks"))
        return f"<{tag}{_align_attr(block)}>{html}</{tag}>" if html else ""
    if tag == "blockquote":
        html = _inline(block, block.get("marks"))
        return f"<blockquote><p{_align_attr(block)}>{html}</p></blockquote>" if html else ""
    if tag == "hr":
        return "<hr>"
    if tag in {"ul", "ol"}:
        if _is_task_list(block):
            legacy_checked = block.get("checked") if isinstance(block.get("checked"), list) else []
            rows = []
            for index, item in enumerate(block.get("items") or []):
                html = _inline(item)
                if not html:
                    continue
                done = _item_checked(item, legacy_checked, index)
                box = "&#9745;" if done else "&#9744;"
                rows.append(f'<li class="task-item{" is-done" if done else ""}"><span aria-hidden="true">{box}</span> {html}</li>')
            return f'<ul class="task-list">{"".join(rows)}</ul>' if rows else ""
        items = [f"<li>{_inline(item)}</li>" for item in block.get("items") or [] if _inline(item)]
        if not items:
            return ""
        return f"<{tag}>{''.join(items)}</{tag}>"
    if tag == "table":
        return _render_table(block)
    if tag == "img" and _attr(block, "src"):
        url = escape(_attr(block, "src"), quote=True)
        alt = escape(_alt(_block_attrs(block).get("alt")), quote=True)
        return f'<img src="{url}" alt="{alt}"/>'
    if tag == "pre":
        language = escape(str(_block_attrs(block).get("language") or "text"), quote=True)
        code = escape(_cell_text(block))
        return f'<pre class="blog-code" data-language="{language}"><code>{code}</code></pre>'
    if tag == "audio" and _attr(block, "src"):
        url = escape(_attr(block, "src"), quote=True)
        return f'<audio class="blog-audio" controls src="{url}"></audio>'
    if tag == "video" and _attr(block, "src"):
        return _render_video(_attr(block, "src"))
    return ""


def _render_table(block: dict) -> str:
    headers = block.get("headers") or []
    rows = block.get("rows") or []
    if not any(_cell_text(cell).strip() for cell in headers) and not rows:
        return ""
    head = ""
    if any(_cell_text(cell).strip() for cell in headers):
        cells = "".join(f"<th>{_inline(cell)}</th>" for cell in headers)
        head = f"<thead><tr>{cells}</tr></thead>"
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_inline(cell)}</td>" for cell in row or [])
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table>{head}<tbody>{''.join(body_rows)}</tbody></table>"


def _inline(value, marks=None) -> str:
    if isinstance(value, dict):
        text = _cell_text(value)
        marks = value.get("marks") or []
    else:
        text = str(value or "")
        marks = list(marks or [])
    if not text.strip():
        return ""
    if not marks:
        return "<br>".join(escape(line) for line in text.split("\n"))
    return _paint(text, marks)


def _walk(node: _Node, out: list[dict]) -> None:
    tag = node.tag
    if tag in _SKIP:
        return
    if tag == "hr":
        out.append({"tag": "hr"})
        return
    if tag == "img":
        _append_image(node, out)
        return
    if tag == "p":
        _append_rich(out, "p", node)
        _append_descendant_images(node, out)
        return
    if tag in _HEADING_TAGS:
        _append_rich(out, tag, node)
        _append_descendant_images(node, out)
        return
    if tag in {"ul", "ol"}:
        items = []
        for child in node.children:
            if isinstance(child, _Node) and child.tag == "li":
                cell = _shape_cell_node(child)
                if _cell_text(cell).strip():
                    items.append(cell)
        if items:
            out.append({"tag": tag, "items": items})
        _append_descendant_images(node, out)
        return
    if tag == "blockquote":
        _append_rich(out, "blockquote", node)
        _append_descendant_images(node, out)
        return
    if tag == "table":
        table = _table_block(node)
        if table:
            out.append(table)
        return
    if tag == "pre":
        text = _plain(node)
        if text:
            out.append({"tag": "pre", "text": text, "attributes": {"language": "text"}})
        return
    _unwrap(node, out)


def _unwrap(node: _Node, out: list[dict]) -> None:
    chunks: list[tuple[str, list]] = []

    def flush() -> None:
        text, marks = _finish_rich(chunks)
        chunks.clear()
        if not text:
            return
        out.append({"tag": "p", "text": text, "marks": marks})

    for child in node.children:
        if isinstance(child, str):
            chunks.append((child, []))
            continue
        if child.tag == "br":
            chunks.append(("\n", []))
            continue
        if child.tag == "hr":
            flush()
            out.append({"tag": "hr"})
            continue
        if child.tag == "img":
            flush()
            _append_image(child, out)
            continue
        if child.tag in _INLINE:
            _gather(child, [], chunks)
            continue
        flush()
        _walk(child, out)
    flush()


def _append_rich(out: list[dict], tag: str, node: _Node) -> None:
    text, marks = _rich(node)
    if not text:
        return
    out.append({"tag": tag, "text": text, "marks": marks})


def _append_image(node: _Node, out: list[dict]) -> None:
    url = (node.attrs.get("src") or "").strip()
    if not url:
        return
    out.append({"tag": "img", "attributes": {"src": url, "alt": _alt(node.attrs.get("alt"))}})


def _append_descendant_images(node: _Node, out: list[dict]) -> None:
    for child in node.children:
        if not isinstance(child, _Node):
            continue
        if child.tag == "img":
            _append_image(child, out)
        else:
            _append_descendant_images(child, out)


def _plain(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag == "img":
            continue
        else:
            parts.append(_plain(child))
    return _clean("".join(parts))


def _table_block(table: _Node) -> dict | None:
    rows = _table_rows(table)
    if not rows:
        return None
    headers: list = []
    body: list[list] = []
    for index, row in enumerate(rows):
        cells: list = []
        header = False
        for child in row.children:
            if not isinstance(child, _Node) or child.tag not in {"td", "th"}:
                continue
            if child.tag == "th":
                header = True
            cells.append(_shape_cell_node(child))
        if not cells:
            continue
        if header and index == 0 and not headers:
            headers = cells
        else:
            body.append(cells)
    if not any(_cell_text(cell).strip() for cell in headers) and not any(
        any(_cell_text(cell).strip() for cell in row) for row in body
    ):
        return None
    return {"tag": "table", "headers": headers, "rows": body}


def _table_rows(table: _Node) -> list[_Node]:
    rows: list[_Node] = []

    def walk(node: _Node) -> None:
        for child in node.children:
            if not isinstance(child, _Node) or child.tag == "table":
                continue
            if child.tag == "tr":
                rows.append(child)
            elif child.tag in {"thead", "tbody", "tfoot"}:
                walk(child)

    walk(table)
    return rows


def _cell_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("text") if "text" in value else value.get("content") or "")
    return str(value or "")


def _shape_text(tag: str, item: dict, strict: bool) -> dict | None:
    text, marks = _stored_rich(item, item.get("marks"), strict)
    if not text:
        return None
    block: dict = {"tag": tag, "text": text, "marks": marks}
    align = _text_align_from(item)
    if align:
        block["attributes"] = {"style": {"textAlign": align}}
    return block


def _shape_cell(value, strict: bool) -> dict:
    if isinstance(value, dict):
        text, marks = _stored_rich(value.get("text"), value.get("marks"), strict)
    else:
        text, marks = _stored_rich(value, None, strict)
    return {"text": text, "marks": marks}


def _shape_cell_node(node: _Node) -> dict:
    text, marks = _rich(node)
    return {"text": text, "marks": marks}


def _stored_rich(content, marks, strict: bool) -> tuple[str, list]:
    raw = _cell_text(content)
    text, mapping = _clean_map(raw)
    if not marks:
        return text, []
    if not isinstance(marks, list):
        if strict:
            raise ApiError("Invalid text marks")
        return text, []
    moved = []
    for mark in marks:
        if not isinstance(mark, dict):
            if strict:
                raise ApiError("Invalid text marks")
            continue
        try:
            start = int(mark.get("start"))
            end = int(mark.get("end"))
        except (TypeError, ValueError):
            if strict:
                raise ApiError("Invalid text marks")
            continue
        new_start, new_end = _map_span(start, end, mapping)
        if new_start is None:
            continue
        copied = dict(mark)
        copied["start"] = new_start
        copied["end"] = new_end
        moved.append(copied)
    return text, _normalize_marks(moved, len(text), strict)


def _pack_text(tag: str, block: dict, limit: int, message: str) -> dict:
    text = _limit(_cell_text(block), limit, message)
    marks = _normalize_marks(block.get("marks") or [], len(text), True)
    result = {"tag": tag, "text": text, "marks": marks}
    align = _text_align_from(block)
    if align:
        result["attributes"] = {"style": {"textAlign": align}}
    return result


def _pack_cell(value, limit: int, message: str) -> dict:
    if isinstance(value, dict):
        text = _limit(_cell_text(value), limit, message)
        marks = _normalize_marks(value.get("marks") or [], len(text), True)
    else:
        text = _limit(_cell_text(value), limit, message)
        marks = []
    return {"text": text, "marks": marks}


def _rich(node: _Node) -> tuple[str, list]:
    chunks: list[tuple[str, list]] = []
    for child in node.children:
        if isinstance(child, str):
            chunks.append((child, []))
        elif child.tag == "br":
            chunks.append(("\n", []))
        elif child.tag == "img":
            continue
        elif child.tag in _INLINE:
            _gather(child, [], chunks)
        else:
            _gather_plain(child, chunks)
    return _finish_rich(chunks)


def _gather(node: _Node, marks: list, chunks: list[tuple[str, list]]) -> None:
    active = marks + _open_mark(node)
    for child in node.children:
        if isinstance(child, str):
            chunks.append((child, active))
        elif child.tag == "br":
            chunks.append(("\n", active))
        elif child.tag == "img":
            continue
        elif child.tag in _INLINE:
            _gather(child, active, chunks)
        else:
            _gather_plain(child, chunks, active)


def _gather_plain(node: _Node, chunks: list[tuple[str, list]], marks: list | None = None) -> None:
    active = marks or []
    for child in node.children:
        if isinstance(child, str):
            chunks.append((child, active))
        elif child.tag == "br":
            chunks.append(("\n", active))
        elif child.tag == "img":
            continue
        elif child.tag in _INLINE:
            _gather(child, active, chunks)
        else:
            _gather_plain(child, chunks, active)


def _open_mark(node: _Node) -> list:
    tag = node.tag
    if tag in {"strong", "b"}:
        return [{"type": "bold"}]
    if tag in {"em", "i"}:
        return [{"type": "italic"}]
    if tag == "code":
        return [{"type": "code"}]
    if tag == "u":
        return [{"type": "underline"}]
    if tag in {"s", "strike", "del"}:
        return [{"type": "strike"}]
    if tag == "sub":
        return [{"type": "subscript"}]
    if tag == "sup":
        return [{"type": "superscript"}]
    if tag == "mark":
        name = str(node.attrs.get("data-color") or "yellow").strip().lower()
        return [{"type": "highlight", "value": name if name in HIGHLIGHTS else "yellow"}]
    if tag == "a":
        href = _link_href(node.attrs.get("href"), strict=False)
        return [{"type": "link", "href": href}] if href else []
    if tag in {"span", "font"}:
        marks = []
        color = _palette_color(_color_source(node), strict=False)
        if color:
            marks.append({"type": "color", "value": color})
        if tag == "span":
            style = node.attrs.get("style") or ""
            family = _font_family_name(style)
            size = _font_size_name(style)
            if family:
                marks.append({"type": "fontFamily", "value": family})
            if size:
                marks.append({"type": "fontSize", "value": size})
        return marks
    return []


def _color_source(node: _Node) -> str:
    if node.tag == "font":
        return node.attrs.get("color") or ""
    match = _COLOR_STYLE.search(node.attrs.get("style") or "")
    return match.group(1).strip() if match else ""


def _finish_rich(chunks: list[tuple[str, list]]) -> tuple[str, list]:
    raw: list[str] = []
    marks = []
    pos = 0
    for text, active in chunks:
        if not text:
            continue
        for mark in active:
            marks.append({**mark, "start": pos, "end": pos + len(text)})
        raw.append(text)
        pos += len(text)
    text, mapping = _clean_map("".join(raw))
    moved = []
    for mark in marks:
        start, end = _map_span(mark["start"], mark["end"], mapping)
        if start is None:
            continue
        copied = {key: value for key, value in mark.items() if key not in {"start", "end"}}
        copied["start"] = start
        copied["end"] = end
        moved.append(copied)
    return text, _normalize_marks(moved, len(text), False)


def _normalize_marks(marks, length: int, strict: bool) -> list:
    cleaned = []
    for mark in marks or []:
        if not isinstance(mark, dict):
            if strict:
                raise ApiError("Invalid text marks")
            continue
        kind = mark.get("type")
        try:
            start = int(mark.get("start"))
            end = int(mark.get("end"))
        except (TypeError, ValueError):
            if strict:
                raise ApiError("Invalid text marks")
            continue
        if start < 0 or end > length or start >= end:
            if strict:
                raise ApiError("Invalid text marks")
            continue
        if kind in _SIMPLE_MARKS:
            cleaned.append({"type": kind, "start": start, "end": end})
        elif kind == "highlight":
            name = str(mark.get("value") or "").strip().lower()
            if name in HIGHLIGHTS:
                cleaned.append({"type": "highlight", "start": start, "end": end, "value": name})
            elif strict:
                raise ApiError("Highlight must be one of the editor colours")
        elif kind == "link":
            href = _link_href(mark.get("href"), strict)
            if href:
                cleaned.append({"type": "link", "start": start, "end": end, "href": href})
        elif kind == "color":
            color = _palette_color(mark.get("value"), strict)
            if color:
                cleaned.append({"type": "color", "start": start, "end": end, "value": color})
        elif kind == "fontFamily":
            family = str(mark.get("value") or "")
            if family in FONT_FAMILIES:
                cleaned.append({"type": "fontFamily", "start": start, "end": end, "value": family})
            elif strict:
                raise ApiError("Font family must be Arial, Georgia, or Times New Roman")
        elif kind == "fontSize":
            size = _font_size_value(mark.get("value"))
            if size:
                cleaned.append({"type": "fontSize", "start": start, "end": end, "value": size})
            elif strict:
                raise ApiError("Font size must be between 8px and 96px")
        elif strict:
            raise ApiError("Invalid text marks")
    return _merge_marks(cleaned)


def _merge_marks(marks: list) -> list:
    ordered = sorted(marks, key=lambda mark: (mark["start"], mark["end"], mark["type"], mark.get("href", ""), mark.get("value", "")))
    merged: list[dict] = []
    for mark in ordered:
        if merged:
            prev = merged[-1]
            same = prev["type"] == mark["type"] and prev.get("href") == mark.get("href") and prev.get("value") == mark.get("value")
            if same and mark["start"] <= prev["end"]:
                prev["end"] = max(prev["end"], mark["end"])
                continue
        merged.append(dict(mark))
    return merged


def _map_span(start: int, end: int, mapping: list) -> tuple[int | None, int | None]:
    new_start = None
    new_end = None
    for index in range(max(0, start), min(end, len(mapping))):
        mapped = mapping[index]
        if mapped is None:
            continue
        if new_start is None:
            new_start = mapped
        new_end = mapped + 1
    return new_start, new_end


def _link_href(value, strict: bool) -> str | None:
    raw = str(value or "").strip()
    if not raw or len(raw) > 2000 or any(ch.isspace() for ch in raw):
        if strict and raw:
            raise ApiError("A link must be http or https")
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        if strict:
            raise ApiError("A link must be http or https")
        return None
    return raw


def _font_family_name(style: str) -> str | None:
    match = _FONT_FAMILY_STYLE.search(style or "")
    if not match:
        return None
    name = match.group(1).split(",")[0].strip().strip("\"'")
    return name if name in FONT_FAMILIES else None


def _font_size_value(value) -> str | None:
    match = _FONT_SIZE.fullmatch(str(value or "").strip().lower())
    if not match:
        return None
    size = int(match.group(1))
    if FONT_SIZE_MIN <= size <= FONT_SIZE_MAX:
        return f"{size}px"
    return None


def _font_size_name(style: str) -> str | None:
    match = _FONT_SIZE_STYLE.search(style or "")
    if not match:
        return None
    return _font_size_value(match.group(1).strip().lower())


def _palette_color(value, strict: bool) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        if strict:
            raise ApiError("Text color must be one of the story colors")
        return None
    if text in _PALETTE:
        return _PALETTE[text]
    match = _RGB_COLOR.search(text)
    if match:
        rgb = tuple(int(part) for part in match.groups())
        if rgb in _PALETTE_RGB:
            return _PALETTE_RGB[rgb]
    if strict:
        raise ApiError("Text color must be one of the story colors")
    return None


def _paint(text: str, marks: list) -> str:
    points = {0, len(text)}
    for mark in marks:
        points.add(int(mark["start"]))
        points.add(int(mark["end"]))
    ordered = sorted(point for point in points if 0 <= point <= len(text))
    parts: list[str] = []
    for index in range(len(ordered) - 1):
        start, end = ordered[index], ordered[index + 1]
        if start == end:
            continue
        active = [mark for mark in marks if int(mark["start"]) <= start and int(mark["end"]) >= end]
        parts.append(_wrap_marks(text[start:end], active))
    return "".join(parts)


def _wrap_marks(chunk: str, marks: list) -> str:
    piece = "<br>".join(escape(line) for line in chunk.split("\n"))
    for kind in ("code", "subscript", "superscript", "strike", "underline", "highlight", "fontSize", "fontFamily", "color", "italic", "bold", "link"):
        mark = next((item for item in marks if item.get("type") == kind), None)
        if not mark:
            continue
        if kind == "code":
            piece = f"<code>{piece}</code>"
        elif kind == "subscript":
            piece = f"<sub>{piece}</sub>"
        elif kind == "superscript":
            piece = f"<sup>{piece}</sup>"
        elif kind == "strike":
            piece = f"<s>{piece}</s>"
        elif kind == "underline":
            piece = f"<u>{piece}</u>"
        elif kind == "highlight":
            background = HIGHLIGHTS.get(str(mark.get("value") or ""), HIGHLIGHTS["yellow"])
            piece = f'<mark style="background:{background};color:#0d1614">{piece}</mark>'
        elif kind == "fontSize":
            size = escape(str(mark.get("value") or ""), quote=True)
            piece = f'<span style="font-size:{size}">{piece}</span>'
        elif kind == "fontFamily":
            family = escape(FONT_FAMILIES.get(str(mark.get("value") or ""), ""), quote=True)
            piece = f'<span style="font-family:{family}">{piece}</span>'
        elif kind == "color":
            color = escape(str(mark.get("value") or ""), quote=True)
            piece = f'<span style="color:{color}">{piece}</span>'
        elif kind == "italic":
            piece = f"<em>{piece}</em>"
        elif kind == "bold":
            piece = f"<strong>{piece}</strong>"
        else:
            href = escape(str(mark.get("href") or ""), quote=True)
            piece = f'<a href="{href}" rel="noopener noreferrer">{piece}</a>'
    return piece


def _clean_map(value: str) -> tuple[str, list]:
    chars: list[tuple[str, int]] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\xa0":
            chars.append((" ", index))
        elif char == "\r":
            if index + 1 < len(value) and value[index + 1] == "\n":
                chars.append(("\n", index + 1))
                index += 1
            else:
                chars.append(("\n", index))
        else:
            chars.append((char, index))
        index += 1
    count = len(chars)
    keep = [True] * count

    def hspace(char: str) -> bool:
        return char in " \t"

    for cursor, (char, _src) in enumerate(chars):
        if char != "\n":
            continue
        previous = cursor - 1
        while previous >= 0 and keep[previous] and hspace(chars[previous][0]):
            keep[previous] = False
            previous -= 1
        nxt = cursor + 1
        while nxt < count and hspace(chars[nxt][0]):
            keep[nxt] = False
            nxt += 1
    cursor = 0
    while cursor < count:
        if keep[cursor] and hspace(chars[cursor][0]):
            nxt = cursor + 1
            while nxt < count and keep[nxt] and hspace(chars[nxt][0]):
                keep[nxt] = False
                nxt += 1
        cursor += 1
    cursor = 0
    while cursor < count:
        if not (keep[cursor] and chars[cursor][0] == "\n"):
            cursor += 1
            continue
        run = [cursor]
        nxt = cursor + 1
        while nxt < count:
            if not keep[nxt]:
                nxt += 1
                continue
            if chars[nxt][0] != "\n":
                break
            run.append(nxt)
            nxt += 1
        for extra in run[2:]:
            keep[extra] = False
        cursor = nxt
    start = 0
    while start < count and (not keep[start] or chars[start][0] in " \t\n"):
        keep[start] = False
        start += 1
    end = count - 1
    while end >= 0 and (not keep[end] or chars[end][0] in " \t\n"):
        keep[end] = False
        end -= 1
    mapping: list[int | None] = [None] * len(value)
    out: list[str] = []
    for cursor, (char, src) in enumerate(chars):
        if not keep[cursor]:
            continue
        mapping[src] = len(out)
        out.append(char)
    return "".join(out), mapping


def _clean(value: str) -> str:
    text, _mapping = _clean_map(value)
    return text


def _optional_media(value, kind: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return _media_url(raw, kind)


def _alt(value) -> str:
    return str(value or "").strip()[:300]


def _media_url(value: str, kind: str) -> str:
    raw = value.strip()
    if not raw:
        raise ApiError(f"A {kind} block needs a file or link")
    if len(raw) > 2000:
        raise ApiError(f"A {kind} link is too long")
    upload = _upload_name(raw)
    if upload is not None:
        if kind == "image" and not upload.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            raise ApiError("Image files must be JPG, PNG, WebP, or GIF")
        if kind == "audio" and not upload.lower().endswith(AUDIO_EXT):
            raise ApiError("Audio files must be MP3, M4A, WAV, OGG, or AAC")
        if kind == "video" and not upload.lower().endswith(VIDEO_EXT):
            raise ApiError("Video files must be MP4, WebM, or OGV")
        if MEDIA_PREFIX in raw:
            return raw
        path = UPLOAD_PREFIX + upload
        origin = _upload_origin.get()
        if origin:
            return origin + path
        return path
    parsed = _https(raw)
    if parsed is None:
        raise ApiError(f"A {kind} link must be https or an uploaded file")
    path = parsed.path.lower()
    if kind == "audio" and not path.endswith(AUDIO_EXT):
        raise ApiError("Audio links must end in .mp3, .m4a, .wav, .ogg, or .aac")
    if kind == "video" and not (_youtube_id(parsed) or _vimeo_id(parsed) or path.endswith(VIDEO_EXT)):
        raise ApiError("Use a YouTube, Vimeo, or direct https video link")
    return raw


def _upload_name(url: str) -> str | None:
    path = url.split("?", 1)[0].split("#", 1)[0]
    prefix = None
    if UPLOAD_PREFIX in path:
        prefix = UPLOAD_PREFIX
    elif MEDIA_PREFIX in path:
        prefix = MEDIA_PREFIX
    if prefix is None:
        return None
    name = path[path.find(prefix) + len(prefix):]
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _https(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or any(ch.isspace() for ch in url):
        return None
    return parsed


def _host(parsed) -> str:
    return parsed.netloc.lower().split(":")[0].removeprefix("www.")


def _youtube_id(parsed) -> str | None:
    host = _host(parsed)
    if host == "youtu.be":
        piece = next((part for part in parsed.path.split("/") if part), "")[:11]
        return piece if re.fullmatch(r"[\w-]{11}", piece) else None
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            piece = ""
            for key, value in _query(parsed.query):
                if key == "v":
                    piece = value
                    break
            return piece if re.fullmatch(r"[\w-]{11}", piece) else None
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] in {"embed", "shorts"} and len(parts) > 1 and re.fullmatch(r"[\w-]{11}", parts[1]):
            return parts[1]
    return None


def _vimeo_id(parsed) -> str | None:
    host = _host(parsed)
    parts = [part for part in parsed.path.split("/") if part]
    if host == "vimeo.com" and parts and parts[0].isdigit():
        return parts[0]
    if host == "player.vimeo.com" and len(parts) > 1 and parts[0] == "video" and parts[1].isdigit():
        return parts[1]
    return None


def _query(query: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for piece in query.split("&"):
        if not piece:
            continue
        key, _, value = piece.partition("=")
        pairs.append((key, value))
    return pairs


def _render_video(url: str) -> str:
    parsed = _https(url)
    if parsed is not None:
        youtube = _youtube_id(parsed)
        if youtube:
            src = f"https://www.youtube-nocookie.com/embed/{youtube}"
            return (
                '<figure class="blog-video"><iframe src="'
                + escape(src, quote=True)
                + '" title="Video"></iframe></figure>'
            )
        vimeo = _vimeo_id(parsed)
        if vimeo:
            src = f"https://player.vimeo.com/video/{vimeo}"
            return (
                '<figure class="blog-video"><iframe src="'
                + escape(src, quote=True)
                + '" title="Video"></iframe></figure>'
            )
    safe = escape(url, quote=True)
    return f'<figure class="blog-video"><video controls src="{safe}"></video></figure>'
