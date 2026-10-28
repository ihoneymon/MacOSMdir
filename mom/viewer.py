"""VV(보라) 오마주 내장 텍스트 뷰어."""
from __future__ import annotations

from .canvas import Canvas
from .textutil import clean, cut, fit, width

MAX_BYTES = 64 * 1024 * 1024
ENCODINGS = ["utf-8", "cp949", "latin-1"]


def decode(data: bytes, prefer: str | None = None) -> tuple[str, str]:
    order = ([prefer] if prefer else []) + [e for e in ENCODINGS if e != prefer]
    for enc in order:
        try:
            text = data.decode("utf-8-sig" if enc == "utf-8" else enc)
            return text, enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def hexdump(data: bytes) -> list[str]:
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08X}  {hx:<47}  |{asc}|")
    return lines


class Viewer:
    def __init__(self, title: str, data: bytes, truncated: bool = False):
        self.title = title
        self.data = data
        self.truncated = truncated
        self.binary = b"\0" in data[:8192]
        self.encoding = "hex" if self.binary else None
        self.top = 0
        self.left = 0
        self.query = ""
        self.message = ""
        self._load()

    def _load(self, prefer: str | None = None) -> None:
        if self.binary:
            self.lines = hexdump(self.data)
            return
        text, self.encoding = decode(self.data, prefer)
        self.lines = [clean(l.expandtabs(8)) for l in text.splitlines()] or [""]

    def cycle_encoding(self) -> None:
        if self.binary:
            return
        i = ENCODINGS.index(self.encoding)
        self._load(ENCODINGS[(i + 1) % len(ENCODINGS)])
        self.message = f"인코딩: {self.encoding}"

    def search(self, start: int, step: int) -> bool:
        q = self.query.lower()
        if not q:
            return False
        n = len(self.lines)
        for k in range(1, n + 1):
            i = (start + step * k) % n
            idx = self.lines[i].lower().find(q)
            if idx >= 0:
                self.top = i
                col = width(self.lines[i][:idx])
                self.left = 0 if col < self.page_w - 10 else max(0, col - 10)
                self.message = f"'{self.query}' {i + 1}행"
                return True
        self.message = f"'{self.query}' 을(를) 찾지 못했습니다"
        return False

    page_w = 80
    page_h = 20

    def draw(self, cv: Canvas) -> None:
        w, h = cv.w, cv.h
        n = len(self.lines)
        num_w = max(4, len(str(n)))
        self.page_w = w - num_w - 3
        self.page_h = h - 2
        self.top = max(0, min(self.top, max(0, n - self.page_h)))
        pct = 100 if n <= self.page_h else int((self.top + self.page_h) * 100 / n)
        pct = min(pct, 100)
        enc = self.encoding.upper()
        head = f" VV ─ {self.title}"
        right = f"{enc}  {n:,}행  {pct:3d}% "
        cv.put(0, 0, fit(head, w - width(right)) + right, "view_bar")
        q = self.query.lower()
        for r in range(self.page_h):
            i = self.top + r
            y = r + 1
            if i >= n:
                cv.put(y, 0, fit("~", w), "view_num")
                continue
            line = self.lines[i]
            cv.put(y, 0, f"{i + 1:>{num_w}} │ ", "view_num")
            x0 = num_w + 3
            cv.put(y, x0, cut(line, self.left, self.page_w), "view_text")
            if q:
                low, start = line.lower(), 0
                while (idx := low.find(q, start)) >= 0:
                    col = width(line[:idx]) - self.left
                    seg = line[idx:idx + len(q)]
                    if col >= 0:
                        cv.put(y, x0 + col, seg, "view_hit", maxw=self.page_w - col)
                    start = idx + len(q)
        keys = " ↑↓ PgUp/PgDn ←→  /:검색 n/N:다음/이전  E:인코딩  Q:닫기"
        status = self.message or ("[64MB 이후 생략] " if self.truncated else "") + keys
        bar = int(pct * w / 100)
        text = fit(status, w)
        cv.put(h - 1, 0, text, "view_bar")
        cv.put(h - 1, 0, cut(text, 0, bar), "fkey_label")

    def handle(self, key, prompt) -> bool:
        """키를 처리한다. False 를 돌려주면 뷰어를 닫는다."""
        import curses

        self.message = ""
        n = len(self.lines)
        page = max(1, self.page_h - 1)
        if key in ("q", "Q", "\x1b", curses.KEY_F3, curses.KEY_F10, "\n", "\r", curses.KEY_ENTER):
            return False
        if key in (curses.KEY_DOWN, "j"):
            self.top += 1
        elif key in (curses.KEY_UP, "k"):
            self.top -= 1
        elif key in (curses.KEY_NPAGE, " "):
            self.top += page
        elif key in (curses.KEY_PPAGE, "b"):
            self.top -= page
        elif key in (curses.KEY_HOME, "g"):
            self.top, self.left = 0, 0
        elif key in (curses.KEY_END, "G"):
            self.top = n
        elif key == curses.KEY_RIGHT:
            self.left += 8
        elif key == curses.KEY_LEFT:
            self.left = max(0, self.left - 8)
        elif key in ("e", "E"):
            self.cycle_encoding()
        elif key == "/":
            q = prompt("검색", "찾을 문자열:", self.query)
            if q:
                self.query = q
                self.search(self.top - 1, 1)
        elif key == "n":
            self.search(self.top, 1)
        elif key == "N":
            self.search(self.top, -1)
        self.top = max(0, min(self.top, max(0, n - self.page_h)))
        return True
