"""화면을 셀 단위 격자로 그린 뒤 curses 로 한 번에 내보낸다.

전각 문자는 두 칸을 차지하며, 두 번째 칸은 빈 문자열('')로 표시한다.
덮어쓰기로 전각 문자가 반쪽만 남으면 공백으로 바꿔 줄 밀림을 막는다.
"""
from __future__ import annotations

from .textutil import char_width

# VGA 16색 (텍스트 모드 팔레트)
BLACK, BLUE, GREEN, CYAN, RED, MAGENTA, BROWN, LGRAY = range(8)
DGRAY, LBLUE, LGREEN, LCYAN, LRED, LMAGENTA, YELLOW, WHITE = range(8, 16)

# VGA 색 → xterm-256 근사값 (#0000AA → 19 등)
VGA_256 = [16, 19, 34, 37, 124, 127, 130, 248, 240, 63, 83, 87, 203, 207, 227, 231]

# 스타일 이름 → (전경, 배경, 굵게)
PALETTE = {
    "frame": (LCYAN, BLUE, False),
    "title": (YELLOW, BLUE, True),
    "text": (LGRAY, BLUE, False),
    "label": (LCYAN, BLUE, False),
    "value": (WHITE, BLUE, True),
    "path": (WHITE, BLUE, True),
    "path_active": (BLACK, CYAN, False),
    "msg": (YELLOW, RED, True),
    "dir": (WHITE, BLUE, True),
    "exe": (LGREEN, BLUE, False),
    "script": (YELLOW, BLUE, False),
    "arc": (LMAGENTA, BLUE, False),
    "doc": (LCYAN, BLUE, False),
    "media": (LRED, BLUE, False),
    "file": (LGRAY, BLUE, False),
    "mark": (YELLOW, BLUE, True),
    "cursor": (BLACK, CYAN, False),
    "cursor_mark": (YELLOW, CYAN, True),
    "fkey_num": (WHITE, BLACK, True),
    "fkey_label": (BLACK, CYAN, False),
    "dialog": (BLACK, LGRAY, False),
    "dialog_frame": (WHITE, LGRAY, True),
    "dialog_title": (BLUE, LGRAY, True),
    "danger": (WHITE, RED, False),
    "danger_frame": (YELLOW, RED, True),
    "input": (WHITE, BLACK, False),
    "input_cur": (BLACK, LGRAY, False),
    "view_text": (LGRAY, BLUE, False),
    "view_num": (LGREEN, BLUE, False),
    "view_bar": (BLACK, GREEN, False),
    "view_hit": (BLACK, YELLOW, False),
    "tree": (LGRAY, BLUE, False),
    "tree_line": (LCYAN, BLUE, False),
}

DOUBLE = {"h": "═", "v": "║", "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝"}


class Canvas:
    def __init__(self, w: int, h: int, style: str = "text"):
        self.w, self.h = w, h
        self.chars = [[" "] * w for _ in range(h)]
        self.styles = [[style] * w for _ in range(h)]

    def _set(self, y: int, x: int, c: str, style: str) -> None:
        row = self.chars[y]
        if row[x] == "" and x > 0:  # 전각 문자의 뒷칸을 덮으면 앞칸을 지운다
            row[x - 1] = " "
        if x + 1 < self.w and row[x + 1] == "" and char_width(row[x]) == 2:
            row[x + 1] = " "
        row[x] = c
        self.styles[y][x] = style

    def put(self, y: int, x: int, text: str, style: str, maxw: int | None = None) -> int:
        """(y, x) 부터 text 를 쓴다. 쓴 칸 수를 돌려준다."""
        if not 0 <= y < self.h:
            return 0
        limit = self.w if maxw is None else min(self.w, x + maxw)
        col = x
        for c in text:
            cw = char_width(c)
            if cw == 0:
                continue
            if col + cw > limit:
                if cw == 2 and col < limit:
                    self._set(y, col, " ", style)
                    col += 1
                break
            if col >= 0:
                self._set(y, col, c, style)
                if cw == 2:
                    nxt = col + 2
                    if nxt < self.w and self.chars[y][nxt] == "":  # 뒤 전각 문자의 앞칸을 덮음
                        self.chars[y][nxt] = " "
                    self.chars[y][col + 1] = ""
                    self.styles[y][col + 1] = style
            col += cw
        return col - x

    def fill(self, y: int, x: int, w: int, style: str, c: str = " ") -> None:
        self.put(y, x, c * max(0, w), style)

    def box(self, y: int, x: int, h: int, w: int, style: str, fill_style: str | None = None,
            title: str = "", title_style: str | None = None) -> None:
        b = DOUBLE
        self.put(y, x, b["tl"] + b["h"] * (w - 2) + b["tr"], style)
        for r in range(y + 1, y + h - 1):
            self.put(r, x, b["v"], style)
            if fill_style:
                self.fill(r, x + 1, w - 2, fill_style)
            self.put(r, x + w - 1, b["v"], style)
        self.put(y + h - 1, x, b["bl"] + b["h"] * (w - 2) + b["br"], style)
        if title:
            self.put(y, x + 2, f" {title} ", title_style or style, maxw=w - 4)

    def row_text(self, y: int) -> str:
        return "".join(self.chars[y])

    def runs(self, y: int):
        """같은 스타일이 이어지는 구간을 (x, 문자열, 스타일) 로 돌려준다."""
        row, styles = self.chars[y], self.styles[y]
        x = 0
        while x < self.w:
            start, st, buf = x, styles[x], []
            while x < self.w and (styles[x] == st or row[x] == ""):
                buf.append(row[x])
                x += 1
            yield start, "".join(buf), st
