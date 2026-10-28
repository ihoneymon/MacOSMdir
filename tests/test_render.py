import os
import stat
import tarfile
import unicodedata
import zipfile

import pytest
from wcwidth import wcswidth

from mom.app import App, entry_text
from mom.canvas import Canvas
from mom.fs import Archive, Entry
from mom.textutil import cut, fit, fit_left, width
from mom.tree import Tree
from mom.viewer import Viewer

NAMES = [
    "한글파일이름_아주아주아주아주긴_문서입니다.txt",
    "가나다라마바사아자차카타파하.hwp",
    "mixed영문English혼합.json",
    "a.py",
    "image.png",
    "README",
    "x" * 80 + ".md",
    "보고서.markdown",
]


@pytest.fixture
def tree(tmp_path):
    for n in NAMES:
        (tmp_path / n).write_text("안녕하세요\tMdir\n" * 3, encoding="utf-8")
    # macOS 가 돌려주는 NFD(자모 분리) 파일명
    (tmp_path / unicodedata.normalize("NFD", "자모분리.md")).write_text("x")
    (tmp_path / "폴더").mkdir()
    (tmp_path / "Applications.app").mkdir()
    run = tmp_path / "run.sh"
    run.write_text("echo hi\n")
    run.chmod(run.stat().st_mode | stat.S_IXUSR)
    (tmp_path / ".hidden").write_text("")
    with zipfile.ZipFile(tmp_path / "압축.zip", "w") as zf:
        zf.writestr("문서/메모.txt", "메모")
    for i in range(60):
        (tmp_path / f"파일{i:02d}.dat").write_bytes(b"\0" * i)
    return tmp_path


def assert_exact(cv: Canvas):
    for y in range(cv.h):
        row = cv.row_text(y)
        assert wcswidth(row) == cv.w, (y, row)


def separator_columns(cv: Canvas):
    return [x for x in range(cv.w) if cv.chars[2][x] in "╠╦╬╣"]


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (132, 43), (57, 20), (41, 12), (200, 50)])
@pytest.mark.parametrize("dual", [False, True])
def test_main_screen_rows_are_exact_width(tree, size, dual):
    w, h = size
    app = App(None, str(tree))
    app.dual = dual
    for cursor in (0, 5, len(app.panel.entries) - 1):
        app.panel.cursor = cursor
        app.panel.marked = {e.name for e in app.panel.entries[1:4]}
        cv = Canvas(w, h)
        app.draw_main(cv)
        assert_exact(cv)
        cols = separator_columns(cv)
        assert cols[0] == 0 and cols[-1] == w - 1
        for y in range(3, h - 6):  # 목록 줄의 세로선이 한 칸도 밀리지 않는다
            for x in cols:
                assert cv.chars[y][x] == "║", (y, x, cv.row_text(y))


def test_nfd_names_are_shown_as_nfc(tree):
    app = App(None, str(tree))
    disp = [e.disp for e in app.panel.entries]
    assert "자모분리" in [d.split(".")[0] for d in disp]


@pytest.mark.parametrize("w", [12, 14, 20, 26, 38, 48, 60])
def test_entry_text_width(w):
    for name in NAMES + ["..", "폴더"]:
        e = Entry(name, name in ("..", "폴더"), 123456789, 1_700_000_000)
        assert width(entry_text(e, w, True)) == w


def test_dialog_overlay_keeps_width(tree):
    app = App(None, str(tree))
    cv = Canvas(80, 24)
    app.draw_main(cv)
    app._dialog(cv, "복사", ["한글파일이름_아주아주아주아주긴_문서입니다.txt → 복사할 위치:", "가" * 100])
    assert_exact(cv)


def test_textutil():
    assert width("한a") == 3
    assert width(fit("한글한글", 5)) == 5
    assert fit("한글한글", 5) == "한글~"
    assert fit("한글한글", 6) == "한글~ "
    assert width(fit_left("/아주/긴/경로/입니다", 9)) == 9
    assert cut("가나다", 1, 3) == " 나"
    assert cut("가나다", 1, 4) == " 나 "
    assert width(cut("abc가나다", 2, 5)) == 5


def test_viewer_draw_exact(tree):
    data = ("가나다라마바사 " * 30 + "\n" + "탭\t문자\n") * 50
    v = Viewer("문서.txt", data.encode("cp949"))
    assert v.encoding == "cp949"
    for left in (0, 1, 3, 7):
        v.left = left
        v.query = "마바"
        cv = Canvas(80, 24)
        v.draw(cv)
        assert_exact(cv)


def test_viewer_binary_hex():
    v = Viewer("a.bin", bytes(range(256)))
    assert v.encoding == "hex" and v.lines[0].startswith("00000000  00 01")


def test_tree_draw(tree):
    t = Tree(str(tree), False)
    assert t.node.path == str(tree)
    cv = Canvas(70, 20)
    t.draw(cv)
    assert_exact(cv)


def test_zip_cp949_names(tmp_path, monkeypatch):
    """UTF-8 플래그 없는 윈도우식 한글 zip."""
    path = tmp_path / "win.zip"
    monkeypatch.setattr(zipfile.ZipInfo, "_encodeFilenameFlags",
                        lambda self: (self.filename.encode("cp437"), self.flag_bits))
    with zipfile.ZipFile(path, "w") as zf:
        name = "한글폴더/보고서.txt".encode("cp949").decode("cp437")
        zf.writestr(name, "내용")
    monkeypatch.undo()
    ar = Archive(str(path))
    assert [e.name for e in ar.list("")][1:] == ["한글폴더"]
    files = ar.list("한글폴더")
    assert files[1].name == "보고서.txt"
    assert ar.read(files[1].member, 100).decode() == "내용"
    out = tmp_path / "out"
    out.mkdir()
    assert ar.extract("", [ar.list("")[1]], str(out)) == 1
    assert (out / "한글폴더" / "보고서.txt").read_text() == "내용"


def test_tar_gz(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("A")
    (src / "b.txt").write_text("B")
    path = tmp_path / "x.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        tf.add(src, arcname="src")
    ar = Archive(str(path))
    names = {e.name for e in ar.list("src")}
    assert names == {"..", "sub", "b.txt"}
    out = tmp_path / "out"
    out.mkdir()
    sub = next(e for e in ar.list("src") if e.name == "sub")
    ar.extract("src", [sub], str(out))
    assert (out / "sub" / "a.txt").read_text() == "A"
