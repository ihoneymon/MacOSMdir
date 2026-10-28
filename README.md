# MOM — Mdir for macOS

1990년대 DOS 에서 `M` 한 글자로 띄우던 최정한 님의 파일 관리자 **Mdir III** 를 macOS·Linux 터미널로 옮긴 TUI 입니다.
파란 VGA 화면, 이중선 테두리, 확장자별 색, 단일 키 명령, VV 뷰어, MCD 트리를 그대로 살렸습니다.

```
╔═ MOM 1.0 ─ Mdir for macOS ══════════════════════════════════════ 2026-10-28 22:59 ═╗
║ /Users/me/work                                                           정렬:이름 ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ ..                                                              <UP>               ║
║ 한글폴더                                                       <DIR> 26-10-28 22:41║
║ app                                                    py        900 26-10-28 22:37║
║*보고서                                                 hwp   204,800 26-10-28 22:37║
║ 사진                                                   png    12,345 26-10-28 22:37║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ 보고서.hwp                            204,800 바이트  2026-10-28 22:37  -rw-r--r-- ║
║ 파일 5개 (213.2K)  폴더 1개                      선택 1개 (200.0K)   숨김파일:감춤 ║
║ 디스크 여유 1.6T / 1.8T   메모리 46.2G / 64.0G 사용          [Tab]한 창  F1:도움말 ║
╚════════════════════════════════════════════════════════════════════════════════════╝
1도움말  2이름    3보기    4편집    5복사    6이동    7폴더   8삭제   9트리   10종료
```

## 설치

Python 3.9 이상. [uv](https://docs.astral.sh/uv/) 로 설치하면 `mom` 명령이 생깁니다.

```sh
cd ~/git-repos/mom
uv tool install --python 3.12 -e .     # ~/.local/bin/mom
```

uv 가 없다면 `pip install -r requirements.txt` 후 `python -m mom` 으로 실행합니다.

### `m` 한 글자로 실행 + 종료하면 그 폴더로 cd

자식 프로세스는 부모 셸의 현재 폴더를 바꿀 수 없으므로 `alias` 가 아니라 **셸 함수**가 필요합니다.
MOM 은 종료할 때 마지막 폴더를 `--cwd-file` 로 받은 파일에 쓰고, 함수 `m` 이 그 경로로 `cd` 합니다.

```sh
echo 'source ~/git-repos/mom/shell/mom.sh' >> ~/.zshrc   # bash 는 ~/.bashrc
exec zsh
m            # 현재 폴더에서 시작
m ~/Downloads
```

`shell/mom.sh` 의 내용:

```sh
m() {
  local tmp dir
  tmp="$(mktemp -t mom.XXXXXX)" || return
  command mom --cwd-file "$tmp" "$@"
  dir="$(cat "$tmp" 2>/dev/null)"
  rm -f "$tmp"
  if [ -n "$dir" ] && [ -d "$dir" ] && [ "$dir" != "$PWD" ]; then
    cd "$dir" || return
  fi
}
```

cd 가 필요 없으면 `alias m=mom` 만으로도 됩니다.

## 키

| 키 | 동작 |
|---|---|
| `↑↓←→` `PgUp` `PgDn` `Home` `End` | 커서 이동 (한 창 모드의 `←→` 는 한 페이지씩) |
| `Enter` | 폴더 진입 · `..` 상위 · 압축 파일 열기 · 텍스트는 VV · 실행 파일은 실행 · 그 밖은 기본 앱(`open`) |
| `Backspace` | 상위 폴더 |
| `Space` / `Insert` | 선택(`*`) 후 다음 줄로. `+` 파일 전체 선택, `-` 해제 |
| `Tab` | 한 창(목록 1개) ↔ 두 창(좌우 분할, 목록 2개). 두 창에서는 `←` `→` 로 창 이동 |
| `C` / `F5` | 복사 (두 창이면 반대편 창이 기본 대상). 압축 파일 안에서는 **추출** |
| `M` / `F6` | 이동 · 이름 변경 |
| `F2` | 이름 변경 |
| `D` / `Del` / `F8` | 삭제 확인 창: `Y` 휴지통, `!` 영구 삭제 |
| `K` / `F7` | 폴더 생성 |
| `V` / `F3` | VV 뷰어 |
| `E` / `F4` | `$VISUAL` → `$EDITOR` → `vi` 로 편집 |
| `A` | 정렬: `N` 이름 · `E` 확장자 · `S` 크기 · `T` 시간 · `R` 역순 |
| `T` / `F9` | MCD 디렉터리 트리 |
| `/` | 첫 글자 점프 (입력하는 대로 이동, Enter/Esc 로 끝) |
| `Alt+문자` | 그 글자로 시작하는 다음 항목으로 점프 |
| `.` | 숨김 파일 표시 전환 · `Ctrl+R` 새로 고침 |
| `F1` / `?` | 도움말 |
| `Q` / `Esc` / `F10` | 종료 |

### VV 뷰어

줄 번호, 진행률 막대(맨 아랫줄이 퍼센트만큼 채워짐), 인코딩 자동 판별(UTF-8 → CP949 → Latin-1), `E` 로 인코딩 바꾸기,
`/` 검색과 `n`/`N`, `←→` 가로 스크롤. NUL 바이트가 있으면 16진 덤프로 보여 줍니다. 64MB 까지 읽습니다.

### MCD 트리

`/` 부터 현재 폴더까지 펼친 트리. `→` 펼치기, `←` 접기/상위, `Enter` 로 그 폴더로 이동.

### 압축 파일 가상 폴더

`.zip` `.jar` `.tar` `.tar.gz` `.tgz` `.tar.bz2` `.tar.xz` 에서 Enter 를 치면 풀지 않고 폴더처럼 탐색합니다.
파일에서 Enter/`V` 는 뷰어, `C` 는 선택 항목 추출입니다. 윈도우에서 만든 한글 zip(CP949, UTF-8 플래그 없음)의 파일명도 바로잡아 보여 줍니다.

## 색

| 종류 | 색 | 확장자 예 |
|---|---|---|
| 폴더 | 흰색 굵게 | `<DIR>` |
| 실행 | 밝은 초록 `#55FF55` | `exe com sh app command` + 실행 권한 파일 |
| 스크립트 | 밝은 노랑 `#FFFF55` | `bat cmd py js ts rb go rs …` |
| 압축 | 밝은 자홍 `#FF55FF` | `zip tar gz 7z rar lzh arj …` |
| 문서 | 밝은 하늘 `#55FFFF` | `txt md doc hwp json pdf yaml …` |
| 이미지·미디어 | 밝은 빨강 `#FF5555` | `jpg png gif mp3 mp4 mov …` |
| 그 밖 | 밝은 회색 `#AAAAAA` | |

256색 터미널에서는 VGA 팔레트에 가장 가까운 xterm-256 색(배경 `#0000AA` → 19번)을, 8색 터미널에서는 기본색 + 굵게를 씁니다.

## 한글(CJK)

- 모든 칸 계산은 `wcwidth` 로 표시 폭을 셉니다. 전각 문자가 칸 경계에 걸리면 공백으로 채워 세로선이 밀리지 않습니다.
- macOS 가 돌려주는 NFD(자모 분리) 파일명을 NFC 로 합쳐 표시합니다. 파일 작업에는 원래 이름을 씁니다.
- 테스트(`tests/test_render.py`)가 여러 화면 크기·한 창/두 창·대화상자·뷰어에서 모든 줄의 표시 폭이 정확히 화면 폭과 같은지, 세로선이 같은 열에 있는지 검사합니다.

## 터미널 설정 팁

- **Alt+문자 점프**: Terminal.app 은 설정 › 프로필 › 키보드 › "Option 키를 Meta 키로 사용", iTerm2 는 Profiles › Keys › Left Option = Esc+.
- **F1~F10**: Mac 키보드에서는 `fn` 과 함께 누르거나 "F1, F2 등의 키를 표준 기능 키로 사용" 을 켭니다. 단일 문자 키(C, M, D, K, V, T, Q)는 언제나 동작합니다.
- 테두리가 `PPPP` 로 찍히는 문제: 일부 ncurses(6.0)는 문자 반복(`rep`) 시퀀스로 `═` 를 내보낼 때 하위 바이트(0x50 = `P`)만 보냅니다. MOM 은 실행할 때 `rep` 를 뺀 terminfo 사본을 `~/.cache/mom/terminfo/` 에 만들어 씁니다.
- iTerm2 의 "Treat ambiguous-width characters as double width" 를 켜면 테두리 문자 `═` 가 두 칸이 되어 화면이 깨집니다. 꺼 두세요.

## 개발

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv -e '.[dev]'
.venv/bin/pytest -q
```

구조: `mom/app.py`(화면·키·파일 작업), `canvas.py`(셀 격자와 VGA 팔레트), `textutil.py`(표시 폭), `fs.py`(목록·분류·압축·휴지통·시스템 정보), `viewer.py`(VV), `tree.py`(MCD).
