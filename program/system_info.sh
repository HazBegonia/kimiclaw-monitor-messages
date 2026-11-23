#!/usr/bin/env bash
set -euo pipefail

printf '当前时间: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf '主机名称: %s\n' "$(hostname)"
printf '运行时间: %s\n' "$(uptime -p)"
printf '\n内存使用情况:\n'
free -h
printf '\n根分区使用情况:\n'
df -h /
