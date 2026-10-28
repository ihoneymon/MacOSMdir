"""문자열 표시 폭 계산 — 한글(전각) 파일명이 섞여도 테두리가 밀리지 않게 한다."""
from __future__ import annotations

import unicodedata

from wcwidth import wcwidth


def clean(s: str) -> str:
    """macOS 의 NFD(자모 분리) 파일명을 NFC 로 합치고, 제어 문자는 '?' 로 바꾼다."""
    s = unicodedata.normalize("NFC", s)
    if s.isprintable():
        return s
    return "".join(c if c.isprintable() else "?" for c in s)


def char_width(c: str) -> int:
    w = wcwidth(c)
    return 1 if w < 0 else w


def width(s: str) -> int:
    return sum(char_width(c) for c in s)


def fit(s: str, w: int, align: str = "left", ellipsis: str = "~") -> str:
    """s 를 정확히 w 칸으로 맞춘다. 넘치면 잘라 끝에 ellipsis 를 붙인다."""
    if w <= 0:
        return ""
    sw = width(s)
    if sw <= w:
        pad = " " * (w - sw)
        return pad + s if align == "right" else s + pad
    budget = w - width(ellipsis)
    out, used = [], 0
    for c in s:
        cw = char_width(c)
        if used + cw > budget:
            break
        out.append(c)
        used += cw
    out.append(ellipsis)
    used += width(ellipsis)
    return "".join(out) + " " * (w - used)


def fit_left(s: str, w: int, ellipsis: str = "…") -> str:
    """경로처럼 앞을 잘라 뒷부분을 보여 준다."""
    if width(s) <= w:
        return fit(s, w)
    budget = w - width(ellipsis)
    out, used = [], 0
    for c in reversed(s):
        cw = char_width(c)
        if used + cw > budget:
            break
        out.append(c)
        used += cw
    return fit(ellipsis + "".join(reversed(out)), w)


def cut(s: str, left: int, w: int) -> str:
    """표시 칸 기준으로 [left, left+w) 구간을 잘라 정확히 w 칸 문자열로 돌려준다."""
    out, col = [], 0
    for c in s:
        cw = char_width(c)
        if cw == 0:
            continue
        end = col + cw
        if end <= left:
            col = end
            continue
        if col >= left + w:
            break
        if col < left or end > left + w:  # 경계에 걸친 전각 문자
            out.append(" " * (min(end, left + w) - max(col, left)))
        else:
            out.append(c)
        col = end
    res = "".join(out)
    return res + " " * (w - width(res))


def human_size(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def size_field(n: int, w: int) -> str:
    """Mdir 처럼 바이트 수를 쉼표로 보여 주되, 칸이 모자라면 단위로 줄인다."""
    s = f"{n:,}"
    if len(s) > w:
        s = human_size(n)
    return fit(s, w, align="right")
