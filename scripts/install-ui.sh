#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ $EUID == 0 && $(hostname) == atlas-ewr ]] || exit 1
systemctl is-active --quiet wg-quick@atlasvpn.service
if [[ -e /usr/local/lib/atlas-vpn-ui/owner ]]; then
  [[ $(cat /usr/local/lib/atlas-vpn-ui/owner) == "$root" ]] || exit 1
elif [[ -e /var/lib/atlas-vpn-ui || -e /usr/local/lib/atlas-vpn-ui ]]; then
  echo 'Existing unmanaged UI paths'; exit 1
fi
install -d -m 700 /var/lib/atlas-vpn-ui
install -d -m 755 /usr/local/lib/atlas-vpn-ui
python3 - "$root" <<'PY'
import importlib.util, json, os, pathlib, secrets, subprocess, sys
root=pathlib.Path(sys.argv[1]); base=pathlib.Path('/var/lib/atlas-vpn-ui')
os.umask(0o077)
if not (base/'state.json').exists():
    keys=json.loads((root/'server/keys.json').read_text())
    devices=json.loads((root/'server/devices.json').read_text())
    current=set(subprocess.check_output(['wg','show','atlasvpn','peers'],text=True).split())
    assert current == {d['public_key'] for d in devices}, 'Live peer set differs from the known initial profiles'
    state={'config':json.loads((root/'config.json').read_text()), 'server_key':keys['server'],
           'server_public':subprocess.check_output(['wg','pubkey'],input=keys['server']+'\n',text=True).strip(), 'devices':{}}
    for offset,device in enumerate(devices,start=2):
        name=device['name']; state['devices'][name]={**keys[name], 'public':device['public_key'], 'offset':offset, 'enabled':True}
    (base/'state.json').write_text(json.dumps(state,indent=2)+'\n')
if not (base/'login.json').exists():
    (base/'login.json').write_text(json.dumps({'username':'atlas','password':secrets.token_urlsafe(24)},indent=2)+'\n')
login=json.loads((base/'login.json').read_text())
guide=root/'clients/管理页登录.txt'
guide.write_text('先连接 Atlas VPN，再访问 http://10.77.0.1:8787\n用户名：'+login['username']+'\n密码：'+login['password']+'\n')
os.chmod(guide,0o600); os.chown(guide,root.stat().st_uid,root.stat().st_gid)
print('UI_STATE_INITIALIZED credentials=not_printed')
PY
printf '%s\n' "$root" > /usr/local/lib/atlas-vpn-ui/owner
install -m 644 "$root/ui/app.py" "$root/ui/index.html" "$root/ui/app.js" "$root/ui/style.css" /usr/local/lib/atlas-vpn-ui/
install -m 644 "$root/ui/atlas-vpn-ui.service" /etc/systemd/system/atlas-vpn-ui.service
ufw allow in on atlasvpn from 10.77.0.0/24 to 10.77.0.1 port 8787 proto tcp comment 'atlas-vpn-ui-private'
systemctl daemon-reload
systemctl enable atlas-vpn-ui.service
systemctl restart atlas-vpn-ui.service
systemctl is-active --quiet atlas-vpn-ui.service
python3 - "$root" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])/'deployment.json'
state=json.loads(p.read_text())
state.update(management_ui='deployed_private_authenticated', management_url='http://10.77.0.1:8787')
p.write_text(json.dumps(state,indent=2)+'\n')
PY
echo 'UI_DEPLOYED bind=10.77.0.1:8787 authentication=required public_listener=false'
