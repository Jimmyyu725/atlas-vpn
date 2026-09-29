#!/usr/bin/env bash
set -euo pipefail
action=${1:?up or down required}
case "$action" in up|down) ;; *) exit 2 ;; esac
rule() {
  local binary=$1 source=$2
  local args=(-t nat -s "$source" -o enp1s0 -m comment --comment atlas-vpn -j MASQUERADE)
  if [[ "$action" == up ]]; then
    "$binary" -w 5 -C POSTROUTING "${args[@]}" 2>/dev/null ||
      "$binary" -w 5 -A POSTROUTING "${args[@]}"
  elif "$binary" -w 5 -C POSTROUTING "${args[@]}" 2>/dev/null; then
    "$binary" -w 5 -D POSTROUTING "${args[@]}"
  fi
}
rule iptables 10.77.0.0/24
rule ip6tables fd42:6174:6c61:7300::/64
