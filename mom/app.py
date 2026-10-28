"""MOM — macOS 용 Mdir. 진입점과 메인 화면."""
from __future__ import annotations

import argparse
import curses
import locale
import os
import shlex
import shutil
import subprocess
import sys
import time

from . import __version__
from .canvas import PALETTE, VGA_256, Canvas
from .fs import (SORT_KEYS, SORT_LABEL, TEXT_EXT, Archive, Entry, copy_item, disk_usage, is_archive,
                 list_dir, looks_text, memory, open_with_system, remove_item, sort_entries, trash_item)
from .textutil import clean, cut, fit, fit_left, human_size, size_field, width
from .tree import Tree
from .viewer import MAX_BYTES, Viewer

ENTER = ("\n", "\r", curses.KEY_ENTER)
BACKSPACE = (curses.KEY_BACKSPACE, "\x7f", "\x08")
ESC = "\x1b"

FKEYS = [("도움말", "도움"), ("이름변경", "이름"), ("보기(VV)", "보기"), ("편집", "편집"), ("복사", "복사"),
         ("이동", "이동"), ("폴더생성", "폴더"), ("삭제", "삭제"), ("트리(MCD)", "트리"), ("종료", "종료")]

HELP = [
    "MOM — Mdir for macOS",
    "",
    "↑↓←→ PgUp PgDn Home End   커서 이동",
    "Enter        폴더 진입 · 압축 파일 열기 · 텍스트 보기 · 실행",
    "Backspace    상위 폴더",
    "Space/Ins    파일 선택(*)  +/- 전체 선택/해제",
    "Tab          한 창 ↔ 두 창 전환 (두 창에서 ←→ 로 창 이동)",
    "C / F5  복사      M / F6  이동     F2 이름 변경",
    "D / Del / F8  삭제(휴지통, ! 영구)  K / F7  폴더 생성",
    "V / F3  VV 뷰어   E / F4  편집     T / F9  MCD 트리",
    "A  정렬 바꾸기    .  숨김 파일 표시   Ctrl+R  새로 고침",
    "/  첫 글자 점프   Alt+문자  해당 글자로 점프",
    "Q / Esc / F10  종료 (셸 래퍼 m 이 마지막 폴더로 cd)",
]


class Panel:
    def __init__(self, path: str):
        self.path = path
        self.arc: Archive | None = None
        self.inner = ""
        self.entries: list[Entry] = []
        self.cursor = 0
        self.top = 0
        self.marked: set[str] = set()
        self.sort = "name"
        self.reverse = False
        self.files = self.dirs = self.total = 0

    @property
    def real_dir(self) -> str:
        return os.path.dirname(self.arc.path) if self.arc else self.path

    @property
    def location(self) -> str:
        if self.arc:
            return f"{clean(self.arc.path)}:/{clean(self.inner)}"
        return clean(self.path)

    @property
    def cur(self) -> Entry | None:
        return self.entries[self.cursor] if self.entries else None

    def reload(self, show_hidden: bool, focus: str | None = None) -> None:
        if focus is None and self.cur:
            focus = self.cur.name
        raw = self.arc.list(self.inner) if self.arc else list_dir(self.path, show_hidden)
        self.entries = sort_entries(raw, self.sort, self.reverse)
        names = {e.name for e in self.entries}
        self.marked &= names
        files = [e for e in self.entries if not e.is_dir]
        self.files, self.total = len(files), sum(e.size for e in files)
        self.dirs = sum(1 for e in self.entries if e.is_dir and not e.is_parent)
        self.cursor = next((i for i, e in enumerate(self.entries) if e.name == focus), 0)
        self.cursor = min(self.cursor, max(0, len(self.entries) - 1))

    def selection(self) -> list[Entry]:
        if self.marked:
            return [e for e in self.entries if e.name in self.marked]
        e = self.cur
        return [e] if e and not e.is_parent else []

    def marked_size(self) -> int:
        return sum(e.size for e in self.entries if e.name in self.marked and not e.is_dir)


def entry_text(e: Entry, w: int, marked: bool) -> str:
    """파일 한 칸을 정확히 w 칸 문자열로 만든다: *이름 확장자 크기 날짜."""
    date_w = 14 if w >= 48 else 8 if w >= 38 else 0
    size_w = 8 if w >= 20 else 0
    ext_w = 4 if w >= 14 else 0
    name_w = w - 1 - (ext_w + 1 if ext_w else 0) - (size_w + 1 if size_w else 0) - (date_w + 1 if date_w else 0)
    if ext_w and not e.ext:
        name, ext = fit(e.base, name_w + ext_w + 1), ""
    else:
        name = fit(e.base, name_w)
        ext = " " + fit(e.ext, ext_w) if ext_w else ""
    out = ("*" if marked else " ") + name + ext
    if size_w:
        if e.is_parent:
            s = fit("<UP>", size_w, "right")
        elif e.is_dir:
            s = fit("<APP>" if e.kind == "exe" else "<DIR>", size_w, "right")
        else:
            s = size_field(e.size, size_w)
        out += " " + s
    if date_w:
        fmt = "%y-%m-%d %H:%M" if date_w == 14 else "%y-%m-%d"
        out += " " + (time.strftime(fmt, time.localtime(e.mtime)) if e.mtime else " " * date_w)
    return fit(out, w)


def entry_style(e: Entry, marked: bool, is_cursor: bool) -> str:
    if is_cursor:
        return "cursor_mark" if marked else "cursor"
    return "mark" if marked else e.kind


def mode_string(e: Entry) -> str:
    if not e.mode:
        return ""
    import stat
    return stat.filemode(e.mode)


class App:
    def __init__(self, scr, path: str):
        """scr 가 None 이면 curses 없이 화면 상태만 만든다 (테스트용)."""
        self.scr = scr
        self.panels = [Panel(path), Panel(path)]
        self.active = 0
        self.dual = False
        self.show_hidden = False
        self.msg = ""
        self.jump: str | None = None
        self.last_target = ""
        self.layout = (1, 1)  # (행 수, 열 수)
        self.base = self.draw_main
        self._pairs: dict[tuple[int, int], int] = {}
        if scr is not None:
            self._init_curses()
        for p in self.panels:
            p.reload(self.show_hidden)

    # ── curses ────────────────────────────────────────────────

    def _init_curses(self) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.scr.keypad(True)
        curses.start_color()
        self.colors256 = curses.COLORS >= 256

    def attr(self, style: str) -> int:
        fg, bg, bold = PALETTE[style]
        if self.colors256:
            key = (VGA_256[fg], VGA_256[bg])
        else:
            basic = [curses.COLOR_BLACK, curses.COLOR_BLUE, curses.COLOR_GREEN, curses.COLOR_CYAN,
                     curses.COLOR_RED, curses.COLOR_MAGENTA, curses.COLOR_YELLOW, curses.COLOR_WHITE]
            key = (basic[fg % 8], basic[bg % 8])
            bold = bold or fg >= 8
        pair = self._pairs.get(key)
        if pair is None:
            pair = len(self._pairs) + 1
            curses.init_pair(pair, *key)
            self._pairs[key] = pair
        return curses.color_pair(pair) | (curses.A_BOLD if bold else 0)

    def render(self, overlay=None) -> Canvas:
        h, w = self.scr.getmaxyx()
        cv = Canvas(w, h)
        self.base(cv)
        if overlay:
            overlay(cv)
        for y in range(h):
            for x, text, st in cv.runs(y):
                try:
                    self.scr.addstr(y, x, text, self.attr(st))
                except curses.error:  # 오른쪽 아래 마지막 칸
                    pass
        self.scr.noutrefresh()
        curses.doupdate()
        return cv

    def get_key(self, timeout: int = -1):
        self.scr.timeout(timeout)
        try:
            k = self.scr.get_wch()
        except curses.error:
            return None
        if k == ESC:
            self.scr.timeout(30)
            try:
                k2 = self.scr.get_wch()
            except curses.error:
                k2 = None
            if isinstance(k2, str) and k2.isprintable():
                return ("alt", k2)
        return k

    def suspend(self, fn) -> None:
        curses.def_prog_mode()
        curses.endwin()
        try:
            fn()
        finally:
            curses.reset_prog_mode()
            self.scr.clear()

    # ── 화면 ──────────────────────────────────────────────────

    @property
    def panel(self) -> Panel:
        return self.panels[self.active]

    @property
    def other(self) -> Panel:
        return self.panels[1 - self.active]

    def draw_main(self, cv: Canvas) -> None:
        W, H = cv.w, cv.h
        if W < 40 or H < 12:
            cv.put(0, 0, "터미널이 너무 작습니다 (40x12 이상)", "msg")
            return
        nrows = H - 9
        # 목록 영역: (x, 폭) 칸과 세로 구분선 위치
        if self.dual:
            split = W // 2
            cols = [(1, split - 1), (split + 1, W - 2 - split)]
            seps = [split]
            self.layout = (nrows, 1)
        else:
            cols = [(1, W - 2)]
            seps = []
            self.layout = (nrows, 1)

        def hline(y, left, mid, right, junction):
            cv.put(y, 0, left + mid * (W - 2) + right, "frame")
            for s in seps:
                cv.put(y, s, junction, "frame")

        # 맨 윗줄: 제목과 시계
        hline(0, "╔", "═", "╗", "╦" if self.dual else "═")
        cv.put(0, 2, f" MOM {__version__} ─ Mdir for macOS ", "title")
        clock = time.strftime(" %Y-%m-%d %H:%M ")
        cv.put(0, W - 2 - width(clock), clock, "title")

        # 경로 줄
        cv.put(1, 0, "║", "frame")
        cv.put(1, W - 1, "║", "frame")
        if self.dual:
            cv.put(1, seps[0], "║", "frame")
            for i, (x0, cw) in enumerate(cols):
                st = "path_active" if i == self.active else "path"
                cv.put(1, x0, fit_left(" " + self.panels[i].location, cw), st)
        else:
            p = self.panel
            sort = f" 정렬:{SORT_LABEL[p.sort]}{' 역순' if p.reverse else ''} "
            cv.put(1, 1, fit_left(" " + p.location, W - 2 - width(sort)), "path")
            cv.put(1, W - 1 - width(sort), sort, "label")

        hline(2, "╠", "═", "╣", "╬" if self.dual else "╦")

        # 파일 목록
        for y in range(3, 3 + nrows):
            cv.put(y, 0, "║", "frame")
            cv.put(y, W - 1, "║", "frame")
            for s in seps:
                cv.put(y, s, "║", "frame")
        if self.dual:
            for i, (x0, cw) in enumerate(cols):
                p = self.panels[i]
                if p.cursor < p.top:
                    p.top = p.cursor
                elif p.cursor >= p.top + nrows:
                    p.top = p.cursor - nrows + 1
                self._draw_list(cv, p, i == self.active, x0, cw, 3, nrows, [p.top + r for r in range(nrows)])
        else:
            p = self.panel
            page = nrows * len(cols)
            p.top = (p.cursor // page) * page
            for c, (x0, cw) in enumerate(cols):
                start = p.top + c * nrows
                self._draw_list(cv, p, True, x0, cw, 3, nrows, list(range(start, start + nrows)))

        # 정보 영역
        y0 = H - 6
        hline(y0, "╠", "═", "╣", "╩")
        for y in (y0 + 1, y0 + 2, y0 + 3):
            cv.put(y, 0, "║", "frame")
            cv.put(y, W - 1, "║", "frame")
        self._draw_info(cv, y0 + 1, W - 2)
        hline(H - 2, "╚", "═", "╝", "═")
        self._draw_fkeys(cv, H - 1)

    def _draw_list(self, cv, p: Panel, active: bool, x0, cw, y0, nrows, indices) -> None:
        for r, i in enumerate(indices):
            if i >= len(p.entries):
                break
            e = p.entries[i]
            marked = e.name in p.marked
            cv.put(y0 + r, x0, entry_text(e, cw, marked), entry_style(e, marked, active and i == p.cursor))

    def _lr(self, cv, y, w, left, left_style, right, right_style="label") -> None:
        rw = min(width(right), w)
        cv.put(y, 1, fit(" " + left, w - rw), left_style)
        cv.put(y, 1 + w - rw, fit(right, rw), right_style)

    def _draw_info(self, cv, y, w) -> None:
        p = self.panel
        e = p.cur
        if e:
            if e.is_parent:
                left, right = "..", "상위 디렉터리 "
            else:
                kind = "<DIR>" if e.is_dir else f"{e.size:,} 바이트"
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime)) if e.mtime else ""
                link = "링크 " if e.is_link else ""
                right = f"{link}{kind}  {when}  {mode_string(e)} "
                left = e.disp
            self._lr(cv, y, w, left, entry_style(e, False, False), right, "value")
        counts = f"파일 {p.files:,}개 ({human_size(p.total)})  폴더 {p.dirs:,}개"
        mark = f"선택 {len(p.marked)}개 ({human_size(p.marked_size())}) " if p.marked else ""
        hidden = "숨김파일:표시 " if self.show_hidden else "숨김파일:감춤 "
        self._lr(cv, y + 1, w, counts, "text", (mark + "  " if mark else "") + hidden,
                 "mark" if mark else "label")
        if self.jump is not None:
            self._lr(cv, y + 2, w, f"점프: {self.jump}_", "mark", "Enter/Esc: 끝 ")
            return
        if self.msg:
            cv.put(y + 2, 1, fit(" " + self.msg, w), "msg")
            return
        parts = []
        du = disk_usage(p.real_dir)
        if du:
            parts.append(f"디스크 여유 {human_size(du[1])} / {human_size(du[0])}")
        mem = memory()
        if mem:
            parts.append(f"메모리 {human_size(mem[1])} / {human_size(mem[0])} 사용")
        mode = "두 창" if self.dual else "한 창"
        self._lr(cv, y + 2, w, "   ".join(parts), "text", f"[Tab]{mode}  F1:도움말 ")

    def _draw_fkeys(self, cv, y) -> None:
        W = cv.w
        slot = W // 10
        cv.fill(y, 0, W, "fkey_num")
        x = 0
        for i, (lab, short) in enumerate(FKEYS):
            sw = slot + (1 if i < W % 10 else 0)
            num = str(i + 1)
            lw = sw - len(num) - 1
            cv.put(y, x, num, "fkey_num")
            cv.put(y, x + len(num), fit(lab if width(lab) <= lw else short, lw), "fkey_label")
            x += sw

    # ── 대화상자 ──────────────────────────────────────────────

    def _dialog(self, cv, title, lines, danger=False, min_w=40):
        bw = min(cv.w - 4, max(min_w, max((width(l) for l in lines), default=0) + 6, width(title) + 8))
        bh = len(lines) + 4
        y, x = max(0, (cv.h - bh) // 2), max(0, (cv.w - bw) // 2)
        frame, body = ("danger_frame", "danger") if danger else ("dialog_frame", "dialog")
        cv.box(y, x, bh, bw, frame, body, title=title, title_style=frame if danger else "dialog_title")
        for i, l in enumerate(lines):
            cv.put(y + 2 + i, x + 3, fit(l, bw - 6), body)
        return y, x, bw

    def message(self, title, lines) -> None:
        self.render(lambda cv: self._dialog(cv, title, lines + ["", "아무 키나 누르세요"]))
        while self.get_key() is None:
            pass

    def confirm(self, title, lines, keys, danger=False) -> str | None:
        while True:
            self.render(lambda cv: self._dialog(cv, title, lines, danger))
            k = self.get_key()
            if k == ESC:
                return None
            if isinstance(k, str) and k.lower() in keys:
                return k.lower()

    def progress(self, title, text) -> None:
        self.render(lambda cv: self._dialog(cv, title, [text], min_w=50))

    def prompt(self, title, label, default="") -> str | None:
        buf, pos = list(default), len(default)
        while True:
            def overlay(cv):
                y, x, bw = self._dialog(cv, title, [label, "", "", "Enter:확인  Esc:취소  Ctrl+U:지우기"], min_w=60)
                iw = bw - 6
                cur_col = width("".join(buf[:pos]))
                left = max(0, cur_col - iw + 1)
                cv.put(y + 3, x + 3, cut("".join(buf), left, iw), "input")
                cv.put(y + 3, x + 3 + cur_col - left, buf[pos] if pos < len(buf) else " ", "input_cur")

            self.render(overlay)
            k = self.get_key()
            if k in ENTER:
                return "".join(buf).strip()
            if k == ESC:
                return None
            if k in BACKSPACE:
                if pos:
                    del buf[pos - 1]
                    pos -= 1
            elif k == curses.KEY_DC:
                if pos < len(buf):
                    del buf[pos]
            elif k == curses.KEY_LEFT:
                pos = max(0, pos - 1)
            elif k == curses.KEY_RIGHT:
                pos = min(len(buf), pos + 1)
            elif k in (curses.KEY_HOME, "\x01"):
                pos = 0
            elif k in (curses.KEY_END, "\x05"):
                pos = len(buf)
            elif k == "\x15":
                buf, pos = [], 0
            elif isinstance(k, str) and k.isprintable():
                buf.insert(pos, k)
                pos += 1

    # ── 이동 ──────────────────────────────────────────────────

    def flash(self, text: str) -> None:
        self.msg = text

    def reload_all(self) -> None:
        for p in self.panels:
            try:
                p.reload(self.show_hidden)
            except OSError:
                p.arc = None
                p.path = os.path.expanduser("~")
                p.reload(self.show_hidden)

    def chdir(self, p: Panel, path: str, focus: str | None = None) -> None:
        old = (p.path, p.arc, p.inner, list(p.entries), p.cursor, set(p.marked))
        p.path, p.arc, p.inner = os.path.abspath(path), None, ""
        p.marked.clear()
        try:
            p.reload(self.show_hidden, focus or "..")
        except OSError as ex:
            p.path, p.arc, p.inner, p.entries, p.cursor, p.marked = old
            self.flash(f"열 수 없습니다: {ex.strerror or ex}")

    def go_parent(self, p: Panel) -> None:
        if p.arc:
            if p.inner:
                head, _, tail = p.inner.rpartition("/")
                p.inner = head
                p.reload(self.show_hidden, tail)
            else:
                name = os.path.basename(p.arc.path)
                p.arc = None
                p.reload(self.show_hidden, name)
            return
        parent = os.path.dirname(p.path)
        if parent != p.path:
            self.chdir(p, parent, os.path.basename(p.path))

    def move_cursor(self, p: Panel, delta: int, absolute: int | None = None) -> None:
        n = len(p.entries)
        if not n:
            return
        p.cursor = max(0, min(n - 1, absolute if absolute is not None else p.cursor + delta))

    def jump_to(self, prefix: str, after_cursor: bool) -> None:
        p = self.panel
        prefix = prefix.lower()
        n = len(p.entries)
        start = p.cursor + 1 if after_cursor else 0
        for k in range(n):
            i = (start + k) % n
            if p.entries[i].disp.lower().startswith(prefix):
                p.cursor = i
                return

    # ── 동작 ──────────────────────────────────────────────────

    def read_entry(self, p: Panel, e: Entry) -> tuple[bytes, bool]:
        if p.arc:
            data = p.arc.read(e.member, MAX_BYTES + 1)
        else:
            with open(os.path.join(p.path, e.name), "rb") as f:
                data = f.read(MAX_BYTES + 1)
        return data[:MAX_BYTES], len(data) > MAX_BYTES

    def view(self, p: Panel, e: Entry) -> None:
        try:
            data, truncated = self.read_entry(p, e)
        except OSError as ex:
            self.flash(f"읽을 수 없습니다: {ex}")
            return
        v = Viewer(e.disp, data, truncated)
        self.base = v.draw
        try:
            while True:
                self.render()
                k = self.get_key()
                if k is not None and not v.handle(k, self.prompt):
                    break
        finally:
            self.base = self.draw_main

    def enter(self) -> None:
        p = self.panel
        e = p.cur
        if not e:
            return
        if e.is_parent:
            self.go_parent(p)
            return
        if p.arc:
            if e.is_dir:
                p.inner = f"{p.inner}/{e.name}".strip("/")
                p.reload(self.show_hidden, "..")
            else:
                self.view(p, e)
            return
        full = os.path.join(p.path, e.name)
        if e.is_dir:
            if e.kind == "exe":  # .app 번들
                open_with_system(full)
                self.flash(f"실행: {e.disp}")
            else:
                self.chdir(p, full)
            return
        if is_archive(full):
            try:
                p.arc, p.inner = Archive(full), ""
                p.marked.clear()
                p.reload(self.show_hidden, "..")
            except Exception as ex:  # 손상된 압축 파일
                p.arc = None
                self.flash(f"압축 파일을 열 수 없습니다: {ex}")
            return
        ext = e.ext.lower()
        if e.mode & 0o111 or ext in ("sh", "command"):
            self.run_file(p, e)
        elif ext in TEXT_EXT or (e.kind == "file" and looks_text(full)):
            self.view(p, e)
        else:
            open_with_system(full)
            self.flash(f"기본 앱으로 열기: {e.disp}")

    def run_file(self, p: Panel, e: Entry) -> None:
        full = os.path.join(p.path, e.name)
        cmd = [full] if e.mode & 0o111 else ["sh", full]

        def run():
            print(f"\n[MOM] 실행: {' '.join(shlex.quote(c) for c in cmd)}\n", flush=True)
            try:
                subprocess.run(cmd, cwd=p.path)
            except OSError as ex:
                print(f"실행 실패: {ex}")
            input("\n[MOM] Enter 를 누르면 돌아갑니다...")

        self.suspend(run)
        self.reload_all()

    def edit(self) -> None:
        p = self.panel
        e = p.cur
        if p.arc or not e or e.is_dir:
            self.flash("편집할 파일을 고르세요")
            return
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        path = os.path.join(p.path, e.name)
        self.suspend(lambda: subprocess.run(shlex.split(editor) + [path], cwd=p.path))
        self.reload_all()

    def copy_or_move(self, move: bool) -> None:
        p = self.panel
        items = p.selection()
        if not items:
            self.flash("선택된 항목이 없습니다")
            return
        if p.arc and move:
            self.flash("압축 파일 안에서는 이동할 수 없습니다 (C 로 추출)")
            return
        verb = "이동" if move else ("추출" if p.arc else "복사")
        if self.dual and not self.other.arc:
            default = self.other.path
        else:
            default = self.last_target or p.real_dir
        what = items[0].disp if len(items) == 1 else f"{len(items)}개 항목"
        target = self.prompt(verb, f"{what} → {verb}할 위치:", default)
        if not target:
            return
        target = os.path.join(p.real_dir, os.path.expanduser(target))
        self.last_target = target
        if p.arc:
            os.makedirs(target, exist_ok=True)
            try:
                n = p.arc.extract(p.inner, items, target)
                self.flash(f"{n}개 파일을 추출했습니다 → {clean(target)}")
            except Exception as ex:
                self.flash(f"추출 실패: {ex}")
            p.marked.clear()
            self.reload_all()
            return
        into_dir = os.path.isdir(target)
        if not into_dir and len(items) > 1:
            if self.confirm(verb, [f"폴더가 없습니다: {clean(target)}", "만들까요? (Y/N)"], "yn") != "y":
                return
            os.makedirs(target)
            into_dir = True
        done, overwrite_all = 0, False
        for idx, e in enumerate(items):
            src = os.path.join(p.path, e.name)
            dst = os.path.join(target, e.name) if into_dir else target
            if os.path.abspath(src) == os.path.abspath(dst):
                self.flash("원본과 대상이 같습니다")
                continue
            if os.path.lexists(dst) and not overwrite_all:
                ans = self.confirm("덮어쓰기", [f"이미 있습니다: {clean(os.path.basename(dst))}",
                                             "Y:덮어쓰기  N:건너뛰기  A:모두  Esc:중단"], "yna")
                if ans is None:
                    break
                if ans == "n":
                    continue
                overwrite_all = ans == "a"
            self.progress(verb, f"[{idx + 1}/{len(items)}] {e.disp}")
            try:
                if move:
                    if os.path.lexists(dst):
                        remove_item(dst)
                    shutil.move(src, dst)
                else:
                    copy_item(src, dst)
                done += 1
            except (OSError, shutil.Error) as ex:
                self.message("오류", [f"{e.disp}", str(ex)])
        p.marked.clear()
        self.reload_all()
        self.flash(f"{done}개 항목을 {verb}했습니다 → {clean(target)}")

    def rename(self) -> None:
        p = self.panel
        e = p.cur
        if p.arc or not e or e.is_parent:
            return
        new = self.prompt("이름 변경", f"{e.disp} 의 새 이름:", e.disp)
        if not new or new == e.disp:
            return
        dst = os.path.join(p.path, os.path.expanduser(new))
        if os.path.lexists(dst):
            self.flash(f"이미 있습니다: {new}")
            return
        try:
            os.rename(os.path.join(p.path, e.name), dst)
        except OSError as ex:
            self.flash(f"이름 변경 실패: {ex.strerror or ex}")
            return
        self.reload_all()
        if os.path.dirname(dst) == p.path:
            p.reload(self.show_hidden, os.path.basename(dst))

    def delete(self) -> None:
        p = self.panel
        if p.arc:
            self.flash("압축 파일 안에서는 삭제할 수 없습니다")
            return
        items = p.selection()
        if not items:
            return
        what = items[0].disp if len(items) == 1 else f"{len(items)}개 항목 ({human_size(sum(e.size for e in items))})"
        ans = self.confirm("삭제", [f"{what} 을(를) 삭제할까요?", "",
                                  "Y:휴지통으로   !:영구 삭제   N/Esc:취소"], "y!n", danger=True)
        if ans not in ("y", "!"):
            return
        done = 0
        for e in items:
            path = os.path.join(p.path, e.name)
            try:
                trash_item(path) if ans == "y" else remove_item(path)
                done += 1
            except OSError as ex:
                self.message("오류", [e.disp, str(ex)])
                break
        p.marked.clear()
        self.reload_all()
        self.flash(f"{done}개 항목을 {'휴지통으로 옮겼습니다' if ans == 'y' else '영구 삭제했습니다'}")

    def mkdir(self) -> None:
        p = self.panel
        if p.arc:
            return
        name = self.prompt("폴더 생성", "새 폴더 이름:")
        if not name:
            return
        try:
            os.makedirs(os.path.join(p.path, os.path.expanduser(name)))
        except OSError as ex:
            self.flash(f"폴더 생성 실패: {ex.strerror or ex}")
            return
        self.reload_all()
        p.reload(self.show_hidden, name.split("/")[0])

    def change_sort(self) -> None:
        p = self.panel
        cur = SORT_LABEL[p.sort]
        ans = self.confirm("정렬", [f"현재: {cur}{' (역순)' if p.reverse else ''}", "",
                                  "N:이름  E:확장자  S:크기  T:시간  R:역순"], "nestr")
        if ans is None:
            return
        if ans == "r":
            p.reverse = not p.reverse
        else:
            p.sort = SORT_KEYS["nest".index(ans)]
        p.reload(self.show_hidden)

    def tree(self) -> None:
        p = self.panel
        t = Tree(p.real_dir, self.show_hidden)
        self.base = t.draw
        try:
            while True:
                self.render()
                k = self.get_key()
                if k is None:
                    continue
                res = t.handle(k)
                if res is False:
                    return
                if res:
                    self.base = self.draw_main
                    self.chdir(p, res)
                    return
        finally:
            self.base = self.draw_main

    # ── 메인 루프 ─────────────────────────────────────────────

    def run(self) -> str:
        while True:
            self.render()
            k = self.get_key(1000)  # 시계를 위해 1초마다 다시 그림
            if k is None:
                continue
            if k == curses.KEY_RESIZE:
                continue
            self.msg = ""
            if self.jump is not None:
                if self.handle_jump(k):
                    continue
            if self.handle(k) is False:
                return self.panel.real_dir

    def handle_jump(self, k) -> bool:
        if k in ENTER or k == ESC:
            self.jump = None
            return True
        if k in BACKSPACE:
            self.jump = self.jump[:-1]
            return True
        if isinstance(k, str) and k.isprintable():
            self.jump += k
            self.jump_to(self.jump, False)
            return True
        self.jump = None
        return False

    def handle(self, k):
        p = self.panel
        nrows, ncol = self.layout
        if isinstance(k, tuple):  # Alt + 문자
            self.jump_to(k[1], True)
            return None
        key = k.lower() if isinstance(k, str) else k
        if key in ("q", ESC) or k == curses.KEY_F10:
            return False
        if k == curses.KEY_UP:
            self.move_cursor(p, -1)
        elif k == curses.KEY_DOWN:
            self.move_cursor(p, 1)
        elif k == curses.KEY_LEFT:
            if self.dual:
                self.active = 0
            else:
                self.move_cursor(p, -nrows)
        elif k == curses.KEY_RIGHT:
            if self.dual:
                self.active = 1
            else:
                self.move_cursor(p, nrows)
        elif k == curses.KEY_PPAGE:
            self.move_cursor(p, -nrows * ncol)
        elif k == curses.KEY_NPAGE:
            self.move_cursor(p, nrows * ncol)
        elif k == curses.KEY_HOME:
            self.move_cursor(p, 0, 0)
        elif k == curses.KEY_END:
            self.move_cursor(p, 0, len(p.entries) - 1)
        elif k in ENTER:
            self.enter()
        elif k in BACKSPACE:
            self.go_parent(p)
        elif k == "\t":
            self.dual = not self.dual
        elif k in (" ", curses.KEY_IC):
            e = p.cur
            if e and not e.is_parent:
                p.marked ^= {e.name}
            self.move_cursor(p, 1)
        elif k == "+":
            p.marked = {e.name for e in p.entries if not e.is_dir}
        elif k == "-":
            p.marked.clear()
        elif k == "/":
            self.jump = ""
        elif k == ".":
            self.show_hidden = not self.show_hidden
            self.reload_all()
        elif k == "\x12":  # Ctrl+R
            self.reload_all()
        elif key == "c" or k == curses.KEY_F5:
            self.copy_or_move(False)
        elif key == "m" or k == curses.KEY_F6:
            self.copy_or_move(True)
        elif k == curses.KEY_F2:
            self.rename()
        elif key == "d" or k in (curses.KEY_DC, curses.KEY_F8):
            self.delete()
        elif key == "k" or k == curses.KEY_F7:
            self.mkdir()
        elif key == "v" or k == curses.KEY_F3:
            e = p.cur
            if e and not e.is_dir:
                self.view(p, e)
        elif key == "e" or k == curses.KEY_F4:
            self.edit()
        elif key == "a":
            self.change_sort()
        elif key == "t" or k == curses.KEY_F9:
            self.tree()
        elif key in ("?", "h") or k == curses.KEY_F1:
            self.message("도움말", HELP)
        return None


def disable_rep() -> None:
    """현재 TERM 의 terminfo 에서 rep(문자 반복) 기능을 뺀 사본을 쓰게 한다.

    일부 ncurses(6.0 등)는 rep 의 %c 로 '═'(U+2550) 같은 비ASCII 문자를 하위 바이트만
    내보내서 테두리가 'P'(0x50) 로 찍힌다.
    """
    import hashlib

    term = os.environ.get("TERM", "")
    if not term or "/" in term:
        return
    try:  # TERMINFO 를 지정하는 터미널(cmux, kitty 등)도 있으므로 지금 쓰이는 항목을 읽는다
        src = subprocess.run(["infocmp", "-x", term], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return
    if "rep=" not in src:
        return
    fixed = "\n".join(
        ",".join(c for c in line.split(",") if not c.strip().startswith("rep=")) for line in src.splitlines())
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    db = os.path.join(base, "mom", "terminfo", hashlib.sha1(fixed.encode()).hexdigest()[:12])
    marker = os.path.join(db, ".ok")
    if not os.path.exists(marker):
        try:
            os.makedirs(db, exist_ok=True)
            r = subprocess.run(["tic", "-x", "-o", db, "-"], input=fixed, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return
            open(marker, "w").close()
        except (OSError, subprocess.SubprocessError):
            return
    os.environ["TERMINFO"] = db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mom", description="MOM — Mdir for macOS")
    ap.add_argument("path", nargs="?", default=".", help="시작 폴더")
    ap.add_argument("--cwd-file", default=os.environ.get("MOM_CWD_FILE"),
                    help="종료할 때 마지막 폴더 경로를 이 파일에 쓴다 (셸 래퍼 m 이 cd 에 사용)")
    ap.add_argument("--version", action="version", version=f"MOM {__version__}")
    args = ap.parse_args(argv)

    start = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(start):
        print(f"mom: 폴더가 아닙니다: {args.path}", file=sys.stderr)
        return 1
    locale.setlocale(locale.LC_ALL, "")  # 없으면 macOS ncurses 에서 한글이 깨진다
    os.environ.setdefault("ESCDELAY", "25")
    disable_rep()
    try:
        final = curses.wrapper(lambda scr: App(scr, start).run())
    except KeyboardInterrupt:
        final = None
    if final and args.cwd_file:
        with open(args.cwd_file, "w") as f:
            f.write(final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
