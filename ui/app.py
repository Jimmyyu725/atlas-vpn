#!/usr/bin/env python3
"""Single-user VPN management, reachable only on the WireGuard address."""
import argparse
import base64
import copy
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit

BASE = Path('/var/lib/atlas-vpn-ui')
WG_CONFIG = Path('/etc/wireguard/atlasvpn.conf')
HOST = '10.77.0.1:8787'
ORIGIN = 'http://' + HOST
NAME = re.compile(r'[a-z][a-z0-9-]{0,30}\Z')


def command(*args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('System command failed: ' + args[0])
    return result.stdout.strip()


def atomic(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.atlas-vpn-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def addresses(state, offset):
    config = state['config']
    v4 = ipaddress.ip_interface(config['server_ipv4']).network[offset]
    v6 = ipaddress.ip_interface(config['server_ipv6']).network[offset]
    return f'{v4}/32, {v6}/128'


def server_config(state, quick=True):
    config = state['config']
    lines = ['[Interface]', 'PrivateKey = ' + state['server_key']]
    if quick:
        lines += [f"Address = {config['server_ipv4']}, {config['server_ipv6']}"]
    lines += [f"ListenPort = {config['port']}"]
    if quick:
        lines += [f"MTU = {config['mtu']}",
                  'PostUp = /usr/local/lib/atlas-vpn/firewall.sh up',
                  'PostDown = /usr/local/lib/atlas-vpn/firewall.sh down']
    lines.append('')
    for name, device in state['devices'].items():
        if not device['enabled']:
            continue
        lines += ['# ' + name, '[Peer]', 'PublicKey = ' + device['public'],
                  'PresharedKey = ' + device['psk'],
                  'AllowedIPs = ' + addresses(state, device['offset']), '']
    return '\n'.join(lines)


def client_config(state, name):
    device = state['devices'][name]
    config = state['config']
    return '\n'.join([
        '# Atlas VPN - ' + name, '[Interface]', 'PrivateKey = ' + device['private'],
        'Address = ' + addresses(state, device['offset']),
        'DNS = ' + ', '.join(config['dns']), f"MTU = {config['mtu']}", '',
        '[Peer]', 'PublicKey = ' + state['server_public'], 'PresharedKey = ' + device['psk'],
        'AllowedIPs = 0.0.0.0/0, ::/0', f"Endpoint = {config['endpoint']}:{config['port']}",
        'PersistentKeepalive = 25', '',
    ])


class Store:
    def __init__(self, base=BASE, config_path=WG_CONFIG, apply=None):
        self.base = base
        self.config_path = config_path
        self.lock = threading.RLock()
        self.state = json.loads((base / 'state.json').read_text())
        self.apply = apply or self.apply_live

    @staticmethod
    def apply_live(state):
        command('wg', 'syncconf', 'atlasvpn', '/dev/stdin', data=server_config(state, quick=False))

    def sync(self):
        with self.lock:
            atomic(self.config_path, server_config(self.state))
            if Path('/sys/class/net/atlasvpn').exists():
                self.apply(self.state)

    def save(self, candidate):
        """Commit a whole state, restoring the previous state on an apply failure."""
        previous = copy.deepcopy(self.state)
        try:
            atomic(self.config_path, server_config(candidate))
            self.apply(candidate)
            atomic(self.base / 'state.json', json.dumps(candidate, indent=2) + '\n')
            self.state = candidate
        except Exception:
            atomic(self.config_path, server_config(previous))
            self.apply(previous)
            raise

    def change(self, action, name):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError('名称需以小写字母开头，仅含小写字母、数字、短横线，最多 31 字符。')
        with self.lock:
            candidate = copy.deepcopy(self.state)
            devices = candidate['devices']
            if action == 'add':
                if name in devices:
                    raise ValueError('这个名称已存在。')
                used = {device['offset'] for device in devices.values()}
                free = next((n for n in range(2, 254) if n not in used), None)
                if free is None:
                    raise ValueError('地址已用完。')
                private = command('wg', 'genkey')
                devices[name] = {'private': private, 'public': command('wg', 'pubkey', data=private + '\n'),
                                 'psk': command('wg', 'genpsk'), 'offset': free, 'enabled': True}
            elif action in ('enable', 'disable'):
                if name not in devices:
                    raise KeyError(name)
                if action == 'disable' and devices[name]['enabled'] and sum(d['enabled'] for d in devices.values()) == 1:
                    raise ValueError('至少保留一个启用的配置，以免失去管理入口。')
                devices[name]['enabled'] = action == 'enable'
            else:
                raise ValueError('未知操作。')
            self.save(candidate)

    def status(self):
        with self.lock:
            def field(name):
                rows = command('wg', 'show', 'atlasvpn', name).splitlines()
                return {parts[0]: parts[1:] for line in rows if (parts := line.split())}
            handshakes, transfers = field('latest-handshakes'), field('transfer')
            devices = []
            for name, device in self.state['devices'].items():
                rx, tx = map(int, transfers.get(device['public'], ['0', '0']))
                devices.append({'name': name, 'enabled': device['enabled'],
                                'last_handshake': int(handshakes.get(device['public'], ['0'])[0]),
                                'received_bytes': rx, 'sent_bytes': tx})
            return {'devices': devices, 'interface': 'atlasvpn',
                    'note': 'Netflix 连续播放：用户反馈通过；美区片库差异仍待核实。'}


def handler(store, login):
    expected = ('Basic ' + base64.b64encode((login['username'] + ':' + login['password']).encode()).decode()).encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'AtlasVPN'

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Do not log configuration URLs, credentials or user requests.

        def send(self, status, data, kind='application/json; charset=utf-8', filename=None):
            if isinstance(data, dict):
                data = json.dumps(data, ensure_ascii=False).encode()
            if isinstance(data, str):
                data = data.encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            if status == 401:
                self.send_header('WWW-Authenticate', 'Basic realm="Atlas VPN", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if self.headers.get('Host') != HOST:
                self.send(421, {'error': '无效的访问地址。'})
                return False
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected):
                self.send(401, {'error': '请输入管理页用户名和密码。'})
                return False
            return True

        def do_OPTIONS(self):
            self.send(405, {'error': '跨站请求不被接受。'})

        def do_GET(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            try:
                if path in assets:
                    name, kind = assets[path]
                    self.send(200, (Path(__file__).parent / name).read_bytes(), kind)
                elif path == '/api/status':
                    self.send(200, store.status())
                elif (match := re.fullmatch(r'/api/profile/([a-z][a-z0-9-]{0,30})\.(conf|png)', path)):
                    name, extension = match.groups()
                    with store.lock:
                        config = client_config(store.state, name)
                    if extension == 'conf':
                        self.send(200, config, 'text/plain; charset=utf-8', f'atlas-{name}.conf')
                    else:
                        result = subprocess.run(['qrencode', '-l', 'M', '-s', '6', '-o', '-'],
                                                input=config.encode(), capture_output=True, check=True, timeout=15)
                        self.send(200, result.stdout, 'image/png')
                else:
                    self.send(404, {'error': '未找到。'})
            except KeyError:
                self.send(404, {'error': '没有这个设备配置。'})
            except Exception:
                self.send(503, {'error': '服务暂时未就绪，请稍后重试。'})

        def do_POST(self):
            if not self.authorized():
                return
            if self.headers.get('Origin') != ORIGIN:
                self.send(403, {'error': '请求来源不匹配。'})
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send(415, {'error': '请求格式应为 JSON。'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    self.send(413, {'error': '请求大小不正确。'})
                    return
                data = json.loads(self.rfile.read(length))
                action = urlsplit(self.path).path.removeprefix('/api/')
                if action not in ('add', 'enable', 'disable'):
                    self.send(404, {'error': '未找到。'})
                    return
                if not isinstance(data, dict) or set(data) != {'name'}:
                    raise ValueError('只接受设备名称。')
                store.change(action, data['name'])
                self.send(200, {'ok': True})
            except (json.JSONDecodeError, TypeError):
                self.send(400, {'error': '名称无效、已存在或请求格式错误。'})
            except ValueError as error:
                self.send(400, {'error': str(error)})
            except KeyError:
                self.send(404, {'error': '没有这个设备配置。'})
            except Exception:
                self.send(503, {'error': '修改未完成，已尝试恢复之前的配置。'})

    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve', 'sync', 'status'])
    args = parser.parse_args()
    store = Store()
    if args.action == 'status':
        print(json.dumps(store.status(), ensure_ascii=False))
    else:
        store.sync()
    if args.action == 'serve':
        login = json.loads((BASE / 'login.json').read_text())
        ThreadingHTTPServer(('10.77.0.1', 8787), handler(store, login)).serve_forever()
