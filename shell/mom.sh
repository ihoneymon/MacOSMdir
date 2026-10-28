# MOM 셸 래퍼 — ~/.zshrc 또는 ~/.bashrc 에서 source 한다.
#   source ~/git-repos/mom/shell/mom.sh
# m 한 글자로 실행하고, 종료하면 마지막으로 보던 폴더로 cd 한다.
# (자식 프로세스는 부모 셸의 폴더를 바꿀 수 없어서 alias 가 아니라 함수여야 한다.)
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
