#!/usr/bin/env bash
# kimiclaw-monitor-messages 一键安装(Linux,systemd --user)
#
# 用法:
#   scripts/linux/install.sh [--python /path/to/python] [--no-start]
#
# 做的事:
#   1. 准备 Python 环境(优先 --python 指定的解释器;其次已有 conda env
#      kimiclaw-monitor-messages;否则在仓库下建 .venv,要求 python>=3.11)
#      并 pip install -r requirements.txt
#   2. config/ 与 templates/ 下的 *.example.json → 同目录实际 JSON(已存在则跳过,不覆盖)
#   3. state/secrets/wecom-bot.json 不存在则放模板并提醒填写(chmod 600)
#   4. 渲染 scripts/linux/*.service.template → ~/.config/systemd/user/
#      (可用环境变量 SYSTEMD_USER_DIR 覆盖目标目录,便于测试)
#      检测到 openclaw 才装 gateway unit;没有 openclaw 时监控+推送仍可用,
#      只是 bot_tool 拉活 Claw 那步会一直欠账(推送本身不受影响)
#   5. daemon-reload 并 enable;默认随即 start(--no-start 可跳过)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
PYTHON=""
NO_START=0

while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --no-start) NO_START=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

say() { printf '[install] %s\n' "$*"; }

# --- 1. Python 环境 -----------------------------------------------------------
if [ -z "$PYTHON" ]; then
  if command -v conda >/dev/null 2>&1; then
    if ! conda env list | grep -qE '^kimiclaw-monitor-messages\s'; then
      say "创建 conda env kimiclaw-monitor-messages (python 3.11)"
      conda create -y -n kimiclaw-monitor-messages python=3.11
    fi
    PYTHON="$(conda run -n kimiclaw-monitor-messages python -c 'import sys; print(sys.executable)')"
  else
    if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
      say "创建 .venv"
      python3 -m venv "$REPO_DIR/.venv"
    fi
    PYTHON="$REPO_DIR/.venv/bin/python"
  fi
fi

PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 需要 >= 3.11(当前 $PY_VER: $PYTHON)" >&2; exit 1
fi
say "Python: $PYTHON ($PY_VER)"

"$PYTHON" -m pip install -q -r "$REPO_DIR/requirements.txt"
say "依赖安装完成(requirements.txt)"

# --- 2. config 模板 -----------------------------------------------------------
for f in "$REPO_DIR"/config/*.example.json; do
  # wecom-bot.example.json 是凭证模板,归 state/secrets/,不进 config/
  [ "$(basename "$f")" = "wecom-bot.example.json" ] && continue
  target="${f%.example.json}.json"
  if [ -e "$target" ]; then
    say "已存在,跳过: ${target#$REPO_DIR/}"
  else
    cp "$f" "$target"
    say "生成: ${target#$REPO_DIR/}  ← 请按实际情况编辑"
  fi
done

for f in "$REPO_DIR"/templates/*.example.json; do
  target="${f%.example.json}.json"
  if [ -e "$target" ]; then
    say "已存在,跳过: ${target#$REPO_DIR/}"
  else
    cp "$f" "$target"
    say "生成: ${target#$REPO_DIR/}"
  fi
done

# --- 3. 凭证 ------------------------------------------------------------------
SECRETS="$REPO_DIR/state/secrets/wecom-bot.json"
if [ ! -e "$SECRETS" ]; then
  mkdir -p "$(dirname "$SECRETS")"
  cp "$REPO_DIR/config/wecom-bot.example.json" "$SECRETS"
  chmod 600 "$SECRETS"
  say "!! 请填写凭证: state/secrets/wecom-bot.json (botId/secret)"
fi

# --- 4. systemd unit ----------------------------------------------------------
OPENCLAW_BIN_DIR=""
if command -v openclaw >/dev/null 2>&1; then
  OPENCLAW_BIN_DIR="$(cd "$(dirname "$(command -v openclaw)")" && pwd)"
fi

mkdir -p "$SYSTEMD_USER_DIR"
render() { # render <template> <unit-name>
  sed -e "s|@REPO_DIR@|$REPO_DIR|g" \
      -e "s|@PYTHON@|$PYTHON|g" \
      -e "s|@OPENCLAW_BIN_DIR@|${OPENCLAW_BIN_DIR:-/usr/local/bin}|g" \
      "$REPO_DIR/scripts/linux/$1" > "$SYSTEMD_USER_DIR/$2"
  say "unit: $SYSTEMD_USER_DIR/$2"
}

render kimiclaw-monitor.service.template  kimiclaw-monitor.service
render kimiclaw-notifier.service.template kimiclaw-notifier.service
UNITS="kimiclaw-monitor.service kimiclaw-notifier.service"
if [ -n "$OPENCLAW_BIN_DIR" ]; then
  render kimiclaw-openclaw-gateway.service.template kimiclaw-openclaw-gateway.service
  UNITS="$UNITS kimiclaw-openclaw-gateway.service"
else
  say "未检测到 openclaw,跳过 gateway unit(仅监控+推送可用)"
fi

# --- 5. 启用 -------------------------------------------------------------------
if [ "$SYSTEMD_USER_DIR" != "$HOME/.config/systemd/user" ]; then
  say "测试模式(SYSTEMD_USER_DIR 已覆盖),跳过 daemon-reload/enable"
elif systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable $UNITS
  if [ "$NO_START" -eq 0 ]; then
    systemctl --user restart $UNITS
    say "已启动: $UNITS"
  else
    say "已 enable 未启动(--no-start): $UNITS"
  fi
  if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
    say "提示: 需要开机自启/注销不掉请执行 loginctl enable-linger $USER"
  fi
else
  say "systemctl --user 不可用(可能在容器/无 systemd 会话),unit 已渲染,请手工加载"
fi

say "完成。验证: $PYTHON -m src.intranet_notifier --once --dry-run"
