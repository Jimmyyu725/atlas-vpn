#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
if [[ ${1:-} == --test-copy ]]; then
  target=${2:?target copy required}
  [[ $(realpath "$target") != "$root/deployment.json" ]] || exit 2
  cp "$root/baseline/deployment.json" "$target"
  echo 'ROLLBACK_COPY deployed=false netflix_playback=not_tested'
  exit 0
fi
[[ ${1:-} == --deployment && $EUID == 0 ]] || { echo 'Use sudo ROLLBACK.sh --deployment'; exit 2; }
[[ $(cat /usr/local/lib/atlas-vpn/owner 2>/dev/null) == "$root" ]] || { echo 'Ownership mismatch'; exit 1; }
systemctl disable --now wg-quick@atlasvpn.service
/usr/local/lib/atlas-vpn/firewall.sh down
ufw --force delete allow in on enp1s0 to any port 51820 proto udp
ufw --force route delete deny in on atlasvpn out on enp1s0 to 169.254.0.0/16
ufw --force route delete allow in on atlasvpn out on enp1s0 from 10.77.0.0/24
ufw --force route delete allow in on atlasvpn out on enp1s0 from fd42:6174:6c61:7300::/64
# Restore only settings this project changed; do not restore whole firewall dumps.
python3 - "$root" <<'PY'
import json, pathlib, shutil, subprocess, sys
root = pathlib.Path(sys.argv[1])
for key, value in json.loads((root / 'baseline/sysctl.json').read_text()).items():
    subprocess.run(['sysctl', '-w', f'{key}={value}'], check=True)
for name in ['/etc/wireguard/atlasvpn.conf', '/etc/sysctl.d/90-atlas-vpn.conf']:
    pathlib.Path(name).unlink(missing_ok=True)
shutil.copyfile(root / 'baseline/deployment.json', root / 'deployment.json')
PY
echo 'ROLLBACK_DEPLOYMENT interface=absent service=inactive previous_forwarding=restored'
