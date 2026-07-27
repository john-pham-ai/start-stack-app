#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

setup_alias() {
  local alias_line="alias recorder='$PROJECT_DIR/recorder.sh'"
  local rc_files=("$HOME/.bashrc" "$HOME/.bash_aliases" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.profile")

  local f
  for f in "${rc_files[@]}"; do
    if [ -f "$f" ] && grep -qF "alias recorder=" "$f" 2>/dev/null && grep -qF "$PROJECT_DIR/recorder.sh" "$f" 2>/dev/null; then
      return 0
    fi
  done

  local os shell_name target=""
  os="$(uname -s)"
  shell_name="$(basename "${SHELL:-}")"

  if [ "$shell_name" = "zsh" ]; then
    target="$HOME/.zshrc"
  elif [ "$shell_name" = "bash" ]; then
    if [ "$os" = "Darwin" ]; then
      target="$HOME/.bash_profile"
    elif [ -f "$HOME/.bash_aliases" ]; then
      target="$HOME/.bash_aliases"
    else
      target="$HOME/.bashrc"
    fi
  fi

  if [ -z "$target" ]; then
    echo "Could not detect your shell config file automatically. To add a 'recorder' alias yourself, add this line to your shell's rc file:"
    echo "  $alias_line"
    return 0
  fi

  {
    echo ""
    echo "# start_stack recorder alias (added automatically by recorder.sh)"
    echo "$alias_line"
  } >> "$target"
  echo "Added a 'recorder' alias to $target — open a new terminal (or run 'source $target') to use it."
}

setup_alias

if [ ! -d venv ]; then
  echo "Setting up virtual environment..."
  if ! python3 -m venv venv; then
    echo "Failed to create virtual environment. You may need: sudo apt install python3-venv" >&2
    exit 1
  fi
fi

./venv/bin/pip install -q -r requirements.txt

exec ./venv/bin/python recorder.py
