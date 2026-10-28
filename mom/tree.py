"""MCD 오마주 디렉터리 트리."""
from __future__ import annotations

import os

from .canvas import Canvas
from .textutil import clean, fit, fit_left


class Node:
    def __init__(self, path: str, name: str, parent: "Node | None" = None):
        self.path, self.name, self.parent = path, name, parent
        self.children: list[Node] | None = None
        self.expanded = False

    def load(self, show_hidden: bool) -> None:
        if self.children is not None:
            return
        names = []
        try:
            with os.scandir(self.path) as it:
                for de in it:
                    if (show_hidden or not de.name.startswith(".")) and de.is_dir():
                        names.append(de.name)
        except OSError:
            pass
        names.sort(key=lambda s: clean(s).lower())
        self.children = [Node(os.path.join(self.path, n), clean(n), self) for n in names]


class Tree:
    def __init__(self, cwd: str, show_hidden: bool):
        self.show_hidden = show_hidden
        root_path = os.path.abspath(os.sep)
        self.root = Node(root_path, root_path)
        node = self.root
        rel = os.path.relpath(cwd, root_path)
        for part in ([] if rel == "." else rel.split(os.sep)):
            node.load(show_hidden)
            node.expanded = True
            nxt = next((c for c in node.children if os.path.basename(c.path) == part), None)
            if nxt is None:
                break
            node = nxt
        self.top = 0
        self._flatten()
        self.cursor = next(i for i, (_, n) in enumerate(self.rows) if n is node)

    def _flatten(self) -> None:
        self.rows: list[tuple[str, Node]] = []

        def walk(node: Node, prefix: str, last: bool, depth: int):
            if depth == 0:
                self.rows.append(("", node))
                child_prefix = ""
            else:
                self.rows.append((prefix + ("└─" if last else "├─"), node))
                child_prefix = prefix + ("  " if last else "│ ")
            if node.expanded and node.children:
                for i, c in enumerate(node.children):
                    walk(c, child_prefix, i == len(node.children) - 1, depth + 1)

        walk(self.root, "", True, 0)

    @property
    def node(self) -> Node:
        return self.rows[self.cursor][1]

    def draw(self, cv: Canvas) -> None:
        w, h = cv.w, cv.h
        cv.box(0, 0, h, w, "frame", "tree", title="MCD ─ 디렉터리 트리", title_style="title")
        page = h - 3
        self._page = page
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + page:
            self.top = self.cursor - page + 1
        for r in range(page):
            i = self.top + r
            if i >= len(self.rows):
                break
            prefix, node = self.rows[i]
            mark = "+" if not node.expanded and (node.children is None or node.children) else " "
            cv.put(r + 1, 2, prefix, "tree_line", maxw=w - 4)
            x = 2 + len(prefix)
            style = "cursor" if i == self.cursor else "dir"
            cv.put(r + 1, x, fit(f"{mark}{node.name} ", max(0, w - 2 - x)), style, maxw=w - 2 - x)
        info = " ↑↓ 이동  → 펼침  ← 접기/상위  Enter 이동  Esc 취소 "
        cv.put(h - 2, 1, fit_left(self.node.path, w - 2), "path")
        cv.put(h - 1, 2, info, "title", maxw=w - 4)

    def handle(self, key):
        """키를 처리한다. 이동할 경로, 취소면 False, 계속이면 None."""
        import curses

        n = len(self.rows)
        page = max(1, getattr(self, "_page", 20))
        if key in ("\x1b", "q", "Q", curses.KEY_F9, curses.KEY_F10):
            return False
        if key in ("\n", "\r", curses.KEY_ENTER):
            return self.node.path
        if key == curses.KEY_DOWN:
            self.cursor = min(n - 1, self.cursor + 1)
        elif key == curses.KEY_UP:
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(n - 1, self.cursor + page)
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - page)
        elif key == curses.KEY_HOME:
            self.cursor = 0
        elif key == curses.KEY_END:
            self.cursor = n - 1
        elif key == curses.KEY_RIGHT:
            node = self.node
            node.load(self.show_hidden)
            if not node.expanded and node.children:
                node.expanded = True
                self._flatten()
            elif node.children:
                self.cursor += 1
        elif key == curses.KEY_LEFT:
            node = self.node
            if node.expanded:
                node.expanded = False
                self._flatten()
            elif node.parent:
                self.cursor = next(i for i, (_, x) in enumerate(self.rows) if x is node.parent)
        return None
