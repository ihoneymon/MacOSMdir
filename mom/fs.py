"""파일 목록, 확장자 분류, 정렬, 압축 가상 폴더, 파일 작업, 시스템 정보."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass, field

from .textutil import clean

EXE_EXT = {"exe", "com", "sh", "app", "command", "bin", "run", "out", "msi", "pkg", "dmg"}
SCRIPT_EXT = {"bat", "cmd", "py", "js", "mjs", "ts", "tsx", "jsx", "rb", "pl", "lua", "zsh", "bash",
              "fish", "ps1", "php", "kt", "kts", "java", "go", "rs", "c", "h", "cpp", "swift", "gradle"}
ARC_EXT = {"zip", "tar", "gz", "tgz", "bz2", "tbz", "xz", "txz", "7z", "rar", "lzh", "arj", "zst", "jar", "war"}
DOC_EXT = {"txt", "md", "doc", "docx", "hwp", "hwpx", "json", "pdf", "rtf", "csv", "tsv", "xml", "yaml",
           "yml", "toml", "ini", "cfg", "conf", "log", "adoc", "html", "htm", "css", "xls", "xlsx",
           "ppt", "pptx", "key", "pages", "numbers", "properties", "sql", "env"}
MEDIA_EXT = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "svg", "ico", "tif", "tiff", "mp3",
             "mp4", "wav", "flac", "aac", "m4a", "ogg", "mov", "avi", "mkv", "webm", "m4v"}
BINARY_DOC_EXT = {"doc", "docx", "hwp", "hwpx", "pdf", "xls", "xlsx", "ppt", "pptx", "key", "pages", "numbers"}
TEXT_EXT = (DOC_EXT - BINARY_DOC_EXT) | SCRIPT_EXT | {"sh", "command"}

# 확장자 칸에 넣을 최대 길이. 더 긴 확장자는 이름에 붙여 보여 준다.
EXT_MAX = 4


def split_name(name: str) -> tuple[str, str]:
    dot = name.rfind(".")
    if dot <= 0 or len(name) - dot - 1 > EXT_MAX:
        return name, ""
    return name[:dot], name[dot + 1:]


@dataclass
class Entry:
    name: str  # 실제 이름 (파일 작업용)
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    mode: int = 0
    is_link: bool = False
    member: str = ""  # 압축 파일 안의 멤버 경로
    disp: str = field(init=False)
    base: str = field(init=False)
    ext: str = field(init=False)

    def __post_init__(self):
        self.disp = clean(self.name)
        if self.is_dir:
            self.base, self.ext = self.disp, ""
        else:
            self.base, self.ext = split_name(self.disp)

    @property
    def is_parent(self) -> bool:
        return self.name == ".."

    @property
    def kind(self) -> str:
        e = self.ext.lower() or split_name(self.disp)[1].lower()
        if self.is_dir:
            return "exe" if e == "app" else "dir"
        lower = self.disp.lower()
        if lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
            return "arc"
        if e in EXE_EXT:
            return "exe"
        if e in SCRIPT_EXT:
            return "script"
        if e in ARC_EXT:
            return "arc"
        if e in DOC_EXT:
            return "doc"
        if e in MEDIA_EXT:
            return "media"
        if self.mode & 0o111 and not self.member:
            return "exe"
        return "file"


SORT_KEYS = ["name", "ext", "size", "time"]
SORT_LABEL = {"name": "이름", "ext": "확장자", "size": "크기", "time": "시간"}


def sort_entries(entries: list[Entry], key: str, reverse: bool = False) -> list[Entry]:
    parent = [e for e in entries if e.is_parent]
    dirs = [e for e in entries if e.is_dir and not e.is_parent]
    files = [e for e in entries if not e.is_dir]
    name_key = lambda e: e.disp.lower()
    keyf = {
        "name": name_key,
        "ext": lambda e: (e.ext.lower(), e.disp.lower()),
        "size": lambda e: (-e.size, e.disp.lower()),
        "time": lambda e: (-e.mtime, e.disp.lower()),
    }[key]
    dirs.sort(key=name_key if key in ("ext", "size") else keyf, reverse=reverse)
    files.sort(key=keyf, reverse=reverse)
    return parent + dirs + files


def list_dir(path: str, show_hidden: bool) -> list[Entry]:
    out = [Entry("..", True)] if os.path.dirname(path) != path else []
    with os.scandir(path) as it:
        for de in it:
            if not show_hidden and de.name.startswith("."):
                continue
            try:
                st = de.stat()
            except OSError:
                st = de.stat(follow_symlinks=False)
            out.append(Entry(de.name, stat.S_ISDIR(st.st_mode), st.st_size, st.st_mtime, st.st_mode,
                             de.is_symlink()))
    return out


# ── 압축 파일 가상 폴더 ─────────────────────────────────────────────

def is_archive(path: str) -> bool:
    if os.path.isdir(path):
        return False
    lower = path.lower()
    if lower.endswith((".zip", ".jar", ".war")):
        return zipfile.is_zipfile(path)
    if lower.endswith((".tar", ".tgz", ".tbz", ".txz", ".tar.gz", ".tar.bz2", ".tar.xz")):
        return tarfile.is_tarfile(path)
    return False


def _zip_name(info: zipfile.ZipInfo) -> str:
    """UTF-8 플래그가 없는 zip(윈도우 한글판 압축)은 CP949 로 다시 해석한다."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return info.filename


class Archive:
    """압축 파일 내용을 디렉터리 트리처럼 보여 준다."""

    def __init__(self, path: str):
        self.path = path
        self.dirs: dict[str, dict[str, Entry]] = {"": {}}
        if path.lower().endswith((".zip", ".jar", ".war")):
            self.kind = "zip"
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    mt = time.mktime(info.date_time + (0, 0, -1))
                    self._add(_zip_name(info), info.filename, info.is_dir(), info.file_size, mt)
        else:
            self.kind = "tar"
            with tarfile.open(path, "r:*") as tf:
                for m in tf.getmembers():
                    if m.isdir() or m.isfile():
                        self._add(m.name, m.name, m.isdir(), m.size, m.mtime, m.mode)

    def _ensure_dir(self, d: str) -> None:
        if d in self.dirs:
            return
        parent, _, name = d.rpartition("/")
        self._ensure_dir(parent)
        self.dirs[d] = {}
        self.dirs[parent].setdefault(name, Entry(name, True, member=d + "/"))

    def _add(self, name: str, member: str, is_dir: bool, size: int, mtime: float, mode: int = 0o644):
        name = name.strip("/")
        while name.startswith("./"):
            name = name[2:]
        if not name or name == ".":
            return
        parent, _, base = name.rpartition("/")
        self._ensure_dir(parent)
        if is_dir:
            self._ensure_dir(name)
            self.dirs[parent][base].member = member
        else:
            self.dirs[parent][base] = Entry(base, False, size, mtime, mode, member=member)

    def list(self, inner: str) -> list[Entry]:
        return [Entry("..", True)] + list(self.dirs.get(inner, {}).values())

    def read(self, member: str, limit: int) -> bytes:
        if self.kind == "zip":
            with zipfile.ZipFile(self.path) as zf, zf.open(member) as f:
                return f.read(limit)
        with tarfile.open(self.path, "r:*") as tf:
            f = tf.extractfile(member)
            return f.read(limit) if f else b""

    def _members_under(self, inner: str, e: Entry) -> list[tuple[str, str]]:
        """(멤버 이름, 상대 경로) 목록. 디렉터리면 하위 파일을 모두 모은다."""
        rel_root = f"{inner}/{e.name}".strip("/")
        if not e.is_dir:
            return [(e.member, e.name)]
        out = []
        for d, children in self.dirs.items():
            if d == rel_root or d.startswith(rel_root + "/"):
                for c in children.values():
                    if not c.is_dir:
                        rel = f"{d}/{c.name}"[len(rel_root) - len(e.name):]
                        out.append((c.member, rel))
        if not out:
            out.append(("", e.name + "/"))
        return out

    def extract(self, inner: str, entries: list[Entry], dest: str) -> int:
        count = 0
        opener = zipfile.ZipFile(self.path) if self.kind == "zip" else tarfile.open(self.path, "r:*")
        with opener as ar:
            for e in entries:
                for member, rel in self._members_under(inner, e):
                    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
                    target = os.path.join(dest, *parts)
                    if rel.endswith("/") or not member:
                        os.makedirs(target, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    src = ar.open(member) if self.kind == "zip" else ar.extractfile(member)
                    with src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                    count += 1
        return count


# ── 파일 작업 ─────────────────────────────────────────────────────

def copy_item(src: str, dst: str) -> None:
    if os.path.isdir(src) and not os.path.islink(src):
        real_src, real_dst = os.path.realpath(src), os.path.realpath(dst)
        if real_dst == real_src or real_dst.startswith(real_src + os.sep):
            raise OSError(f"폴더를 자기 자신 안으로 복사할 수 없습니다: {src}")
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def remove_item(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _unique(path: str) -> str:
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    stamp = time.strftime("%H.%M.%S")
    cand = f"{base} {stamp}{ext}"
    n = 2
    while os.path.lexists(cand):
        cand = f"{base} {stamp} {n}{ext}"
        n += 1
    return cand


def trash_item(path: str) -> None:
    """휴지통으로 보낸다. macOS 는 ~/.Trash, 리눅스는 freedesktop 휴지통."""
    path = os.path.abspath(path)
    if sys.platform == "darwin":
        try:
            shutil.move(path, _unique(os.path.join(os.path.expanduser("~/.Trash"), os.path.basename(path))))
            return
        except PermissionError:
            script = f'tell application "Finder" to delete POSIX file "{path}"'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if r.returncode != 0:
                raise OSError(r.stderr.strip() or "휴지통으로 옮기지 못했습니다")
            return
    if sys.platform.startswith("linux"):
        base = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "Trash")
        os.makedirs(os.path.join(base, "files"), exist_ok=True)
        os.makedirs(os.path.join(base, "info"), exist_ok=True)
        dest = _unique(os.path.join(base, "files", os.path.basename(path)))
        with open(os.path.join(base, "info", os.path.basename(dest) + ".trashinfo"), "w") as f:
            f.write(f"[Trash Info]\nPath={path}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        shutil.move(path, dest)
        return
    raise OSError("이 OS 에서는 휴지통을 지원하지 않습니다 (영구 삭제를 사용하세요)")


def open_with_system(path: str) -> None:
    if sys.platform == "darwin":
        cmd = ["open", path]
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    else:
        cmd = ["xdg-open", path]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def looks_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return b"\0" not in head


# ── 시스템 정보 ────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = None
    _cache[key] = (now, val)
    return val


def disk_usage(path: str):
    """(전체, 여유) 바이트."""
    def f():
        u = shutil.disk_usage(path)
        return u.total, u.free
    return _cached("disk:" + path, 2.0, f)


def memory():
    """(전체, 사용) 바이트."""
    def f():
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=1).stdout
            page = int(out.split("page size of ")[1].split()[0])
            vals = {}
            for line in out.splitlines()[1:]:
                k, _, v = line.partition(":")
                if v.strip().rstrip(".").isdigit():
                    vals[k.strip()] = int(v.strip().rstrip("."))
            avail = (vals.get("Pages free", 0) + vals.get("Pages inactive", 0)
                     + vals.get("Pages speculative", 0)) * page
            return total, total - avail
        with open("/proc/meminfo") as fh:
            info = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in fh}
        return total, total - info.get("MemAvailable", 0)
    return _cached("mem", 5.0, f)
