#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ $EUID == 0 ]] || exit 1
[[ $(cat /usr/local/lib/atlas-vpn-ui/owner 2>/dev/null) == "$root" ]] || exit 1
systemctl disable --now atlas-vpn-ui.service
ufw --force delete allow in on atlasvpn from 10.77.0.0/24 to 10.77.0.1 port 8787 proto tcp
python3 - "$root" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])/'deployment.json'
state=json.loads(p.read_text()); state['management_ui']='installed_inactive'
p.write_text(json.dumps(state,indent=2)+'\n')
PY
echo 'UI_ROLLBACK service=inactive rule=removed vpn=untouched data=preserved'
