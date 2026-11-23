#!/usr/bin/env bash
set -euo pipefail

target="${1:-/}"
threshold="${2:-80}"

if [[ ! -d "$target" ]]; then
    printf '错误：目录不存在：%s\n' "$target" >&2
    exit 2
fi

if [[ ! "$threshold" =~ ^[0-9]+$ ]] || (( 10#$threshold > 100 )); then
    printf '用法: %s [目录] [告警阈值]\n告警阈值必须是 0 到 100 之间的整数。\n' "$0" >&2
    exit 2
fi

usage_percent="$(df -P "$target" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
df -h "$target"

if (( usage_percent >= 10#$threshold )); then
    printf '告警：%s 当前使用率为 %s%%，已达到阈值 %s%%。\n' "$target" "$usage_percent" "$threshold"
    exit 1
fi

printf '正常：%s 当前使用率为 %s%%，低于阈值 %s%%。\n' "$target" "$usage_percent" "$threshold"
