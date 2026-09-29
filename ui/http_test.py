"""Read-only live HTTP checks; attempted mutations are intentionally invalid."""
import base64
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://10.77.0.1:8787'
login = json.loads(subprocess.check_output(['sudo','-n','cat','/var/lib/atlas-vpn-ui/login.json'], text=True))
AUTH = 'Basic ' + base64.b64encode((login['username'] + ':' + login['password']).encode()).decode()


def request(path, headers=None, data=None):
    try:
        req = urllib.request.Request(BASE + path, headers=headers or {}, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


assert request('/')[0] == 401
print('AUTH_REQUIRED PASS status=401')
assert request('/', {'Authorization': AUTH, 'Host': 'attacker.invalid'})[0] == 421
print('HOST_CHECK PASS status=421')
status, body = request('/api/status', {'Authorization': AUTH})
assert status == 200 and not any(x in body for x in [b'PrivateKey', b'PresharedKey', b'password'])
assert {d['name'] for d in json.loads(body)['devices']} >= {'iphone', 'mac', 'windows'}
print('STATUS PASS initial_devices_present=true secrets_absent=true')
for name in ('iphone', 'mac', 'windows'):
    status, data = request(f'/api/profile/{name}.conf', {'Authorization': AUTH})
    assert status == 200 and data == (ROOT / f'clients/atlas-{name}.conf').read_bytes()
    status, data = request(f'/api/profile/{name}.png', {'Authorization': AUTH})
    assert status == 200 and data.startswith(b'\x89PNG\r\n\x1a\n')
print('DOWNLOADS PASS existing_profiles_unchanged=true qr_png=true')
for label, headers, data, expected in [
    ('origin', {'Authorization': AUTH, 'Origin': 'http://other.invalid', 'Content-Type': 'application/json'}, b'{"name":"rejected-test"}', 403),
    ('format', {'Authorization': AUTH, 'Origin': BASE, 'Content-Type': 'application/x-www-form-urlencoded'}, b'name=rejected-test', 415),
    ('name', {'Authorization': AUTH, 'Origin': BASE, 'Content-Type': 'application/json'}, b'{"name":"../rejected-test"}', 400),
]:
    assert request('/api/add', headers, data)[0] == expected
    print(f'BOUNDARY {label} PASS status={expected}')
