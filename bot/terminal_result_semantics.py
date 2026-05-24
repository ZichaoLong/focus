from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass


_ZERO_WIDTH_DIGITS = ("\u200b", "\u200c", "\u200d", "\ufeff")
_ZERO_WIDTH_TO_BITS = {char: index for index, char in enumerate(_ZERO_WIDTH_DIGITS)}
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_BULLET_LIST_RE = re.compile(r"^\s*[-*+][ \t]+.+$")
_ORDERED_LIST_RE = re.compile(r"^\s*\d+\.[ \t]+.+$")
_QUOTE_RE = re.compile(r"^\s*>[ \t]?.+$")
_MAX_HEADING_COUNT = 6
_MAX_HEADING_TEXT = 80
_MAX_SUMMARY_PAYLOAD_CHARS = 512


@dataclass(frozen=True, slots=True)
class TerminalHeading:
    level: int
    text: str


@dataclass(frozen=True, slots=True)
class TerminalStructureSummary:
    headings: tuple[TerminalHeading, ...] = ()
    has_list: bool = False
    has_quote: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.headings and not self.has_list and not self.has_quote


def summarize_terminal_result_text(text: str) -> TerminalStructureSummary:
    headings: list[TerminalHeading] = []
    has_list = False
    has_quote = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match and len(headings) < _MAX_HEADING_COUNT:
            heading_text = str(heading_match.group(2) or "").strip()
            if heading_text:
                headings.append(
                    TerminalHeading(
                        level=len(heading_match.group(1)),
                        text=heading_text[:_MAX_HEADING_TEXT],
                    )
                )
            continue
        if not has_quote and _QUOTE_RE.match(line):
            has_quote = True
        if not has_list and (_BULLET_LIST_RE.match(line) or _ORDERED_LIST_RE.match(line)):
            has_list = True
    return TerminalStructureSummary(
        headings=tuple(headings),
        has_list=has_list,
        has_quote=has_quote,
    )


def encode_terminal_structure_summary(summary: TerminalStructureSummary) -> str:
    if summary.is_empty:
        return ""
    payload: dict[str, object] = {}
    if summary.headings:
        payload["h"] = [[heading.level, heading.text] for heading in summary.headings]
    if summary.has_list:
        payload["l"] = 1
    if summary.has_quote:
        payload["q"] = 1
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    invisible = _base64_to_zero_width(encoded)
    if len(invisible) > _MAX_SUMMARY_PAYLOAD_CHARS:
        return ""
    return invisible


def decode_terminal_structure_summary(payload: str) -> TerminalStructureSummary:
    normalized = str(payload or "").strip()
    if not normalized:
        return TerminalStructureSummary()
    try:
        encoded = _zero_width_to_base64(normalized)
        padding = "=" * (-len(encoded) % 4)
        data = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return TerminalStructureSummary()
    headings: list[TerminalHeading] = []
    for item in data.get("h", []) if isinstance(data, dict) else []:
        if not isinstance(item, list) or len(item) != 2:
            continue
        try:
            level = int(item[0])
        except (TypeError, ValueError):
            continue
        text = str(item[1] or "").strip()
        if not text:
            continue
        headings.append(TerminalHeading(level=max(1, min(level, 6)), text=text[:_MAX_HEADING_TEXT]))
    has_list = bool(data.get("l")) if isinstance(data, dict) else False
    has_quote = bool(data.get("q")) if isinstance(data, dict) else False
    return TerminalStructureSummary(
        headings=tuple(headings[:_MAX_HEADING_COUNT]),
        has_list=has_list,
        has_quote=has_quote,
    )


def _base64_to_zero_width(encoded: str) -> str:
    chars: list[str] = []
    for byte in encoded.encode("ascii"):
        chars.append(_ZERO_WIDTH_DIGITS[(byte >> 6) & 0b11])
        chars.append(_ZERO_WIDTH_DIGITS[(byte >> 4) & 0b11])
        chars.append(_ZERO_WIDTH_DIGITS[(byte >> 2) & 0b11])
        chars.append(_ZERO_WIDTH_DIGITS[byte & 0b11])
    return "".join(chars)


def _zero_width_to_base64(payload: str) -> str:
    values = [_ZERO_WIDTH_TO_BITS[char] for char in payload if char in _ZERO_WIDTH_TO_BITS]
    if not values or len(values) % 4 != 0:
        raise ValueError("invalid zero-width payload")
    decoded = bytearray()
    for index in range(0, len(values), 4):
        decoded.append(
            (values[index] << 6)
            | (values[index + 1] << 4)
            | (values[index + 2] << 2)
            | values[index + 3]
        )
    return decoded.decode("ascii")
