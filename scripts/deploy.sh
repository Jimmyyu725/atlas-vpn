#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ $EUID == 0 ]] || { echo 'Run with sudo'; exit 1; }
[[ $(hostname) == atlas-ewr ]] || { echo 'Unexpected host'; exit 1; }
[[ -s "$root/server/atlasvpn.conf" ]] || exit 1
# Fail closed if the reserved paths are owned by another deployment.
if [[ -e /etc/wireguard/atlasvpn.conf || -e /etc/sysctl.d/90-atlas-vpn.conf || -e /usr/local/lib/atlas-vpn/owner ]]; then
  [[ $(cat /usr/local/lib/atlas-vpn/owner 2>/dev/null) == "$root" ]] || {
    echo 'Existing unmanaged deployment paths'; exit 1;
  }
fi
install -d -m 700 /etc/wireguard
install -d -m 755 /usr/local/lib/atlas-vpn
printf '%s\n' "$root" > /usr/local/lib/atlas-vpn/owner
install -m 755 "$root/scripts/firewall.sh" /usr/local/lib/atlas-vpn/firewall.sh
if [[ -f /var/lib/atlas-vpn-ui/state.json ]]; then
  [[ $(cat /usr/local/lib/atlas-vpn-ui/owner 2>/dev/null) == "$root" ]] || exit 1
  python3 /usr/local/lib/atlas-vpn-ui/app.py sync
else
  install -m 600 "$root/server/atlasvpn.conf" /etc/wireguard/atlasvpn.conf
fi
cat > /etc/sysctl.d/90-atlas-vpn.conf <<'EOF'
# Atlas VPN: preserve IPv6 router advertisements while routing VPN clients.
net.ipv4.ip_forward=1
net.ipv6.conf.enp1s0.accept_ra=2
net.ipv6.conf.all.forwarding=1
EOF
sysctl -p /etc/sysctl.d/90-atlas-vpn.conf
ufw allow in on enp1s0 to any port 51820 proto udp comment 'atlas-vpn-entry'
ufw route deny in on atlasvpn out on enp1s0 to 169.254.0.0/16 comment 'atlas-vpn-metadata'
ufw route allow in on atlasvpn out on enp1s0 from 10.77.0.0/24 comment 'atlas-vpn-forward-v4'
ufw route allow in on atlasvpn out on enp1s0 from fd42:6174:6c61:7300::/64 comment 'atlas-vpn-forward-v6'
systemctl enable wg-quick@atlasvpn.service
if systemctl is-active --quiet wg-quick@atlasvpn.service; then
  wg syncconf atlasvpn <(wg-quick strip /etc/wireguard/atlasvpn.conf)
  /usr/local/lib/atlas-vpn/firewall.sh up
else
  systemctl start wg-quick@atlasvpn.service
fi
python3 - "$root" <<'PY'
import json, pathlib, subprocess, sys
p = pathlib.Path(sys.argv[1]) / 'deployment.json'
state = json.loads(p.read_text())
ui_active = subprocess.run(['systemctl','is-active','--quiet','atlas-vpn-ui.service']).returncode == 0
ui_state = 'deployed_private_authenticated' if ui_active else ('installed_inactive' if pathlib.Path('/var/lib/atlas-vpn-ui/state.json').exists() else 'not_started_playback_gate')
state.update(deployed=True, interface='atlasvpn', port=51820,
             server_tunnel_test='pending', external_device_test='pending',
             netflix_playback='not_tested', management_ui=ui_state)
p.write_text(json.dumps(state, indent=2) + '\n')
PY
printf 'DEPLOYED interface=atlasvpn port=51820\n'
