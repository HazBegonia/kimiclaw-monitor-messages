#!/usr/bin/env bash
set -euo pipefail

interval="${1:-5}"

if [[ ! "$interval" =~ ^[1-9][0-9]*$ ]]; then
    printf '用法: %s [间隔秒数]\n间隔秒数必须是正整数。\n' "$0" >&2
    exit 2
fi

trap 'printf "[%s] 心跳任务已停止，PID: %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$$"; exit 0' INT TERM

printf '[%s] 心跳任务已启动，PID: %s，间隔: %s 秒\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$$" "$interval"
while true; do
    printf '[%s] heartbeat，PID: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$$"
    sleep "$interval"
done
