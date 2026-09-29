#!/usr/bin/env python3
"""Read-only checks on the explicitly verified Mac SSH target.

An observation exiting successfully does not mean the VPN passed. Inspect
vpn_session and full_tunnel_egress_verified. No Mac setting is changed.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6',
       '-o', 'StrictHostKeyChecking=yes', 'jingtian-mac']


def remote(command):
    result = subprocess.run(SSH + [command], capture_output=True, text=True, timeout=25)
    return {'exit': result.returncode, 'output': result.stdout.strip(), 'stderr': result.stderr.strip()}


def egress_verified(before, after, results):
    return before['exit'] == after['exit'] == 0 and before['output'] == after['output'] == 'Connected' and all(
        results['ipv' + family]['exit'] == 0 and results['ipv' + family]['output']['matches_atlas']
        and results['ipv' + family]['output']['country'] == 'US' for family in ('4', '6'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        connected = {'exit': 0, 'output': 'Connected'}
        disconnected = {'exit': 0, 'output': 'Disconnected'}
        good = {f'ipv{f}': {'exit': 0, 'output': {'country': 'US', 'matches_atlas': True}} for f in ('4', '6')}
        assert egress_verified(connected, connected, good)
        assert not egress_verified(disconnected, disconnected, good)
        assert not egress_verified(connected, disconnected, good)
        good['ipv6']['exit'] = 28
        assert not egress_verified(connected, connected, good)
        good['ipv6']['exit'] = 0
        good['ipv6']['output']['matches_atlas'] = False
        assert not egress_verified(connected, connected, good)
        good['ipv6']['output']['matches_atlas'] = True
        good['ipv6']['output']['country'] = 'TW'
        assert not egress_verified(connected, connected, good)
        print('MAC_CHECK_LOGIC PASS offline_cases=6 no_live_vpn_claim=true')
        return
    identity = remote('uname -s')
    if identity['exit'] or identity['output'] != 'Darwin':
        raise SystemExit('Mac SSH identity not verified')
    config = json.loads((ROOT / 'config.json').read_text())
    addresses = json.loads(subprocess.check_output(['ip', '-j', '-6', 'address', 'show', 'dev', config['uplink']], text=True))
    expected_v6 = {address['local'] for link in addresses for address in link['addr_info'] if address['scope'] == 'global'}
    status_command = '/usr/sbin/scutil --nc status Shadowrocket | head -1'
    before = remote(status_command)
    results = {}
    for family in ('4', '6'):
        result = remote(f"/usr/bin/curl --noproxy '*' -{family} -fsS --max-time 12 https://www.cloudflare.com/cdn-cgi/trace")
        fields = dict(line.split('=', 1) for line in result['output'].splitlines() if '=' in line)
        result['output'] = {'country': fields.get('loc'),
                            'matches_atlas': fields.get('ip') == config['endpoint'] if family == '4' else fields.get('ip') in expected_v6}
        results['ipv' + family] = result
    results['route_ipv4'] = remote("/sbin/route -n get 1.1.1.1 | grep 'interface:'")
    results['route_ipv6'] = remote("/sbin/route -n get -inet6 2606:4700:4700::1111 | grep 'interface:'")
    results['dns'] = remote("/usr/sbin/scutil --dns | grep 'nameserver\\[' | sort -u")
    results['management_page'] = remote("/usr/bin/curl --noproxy '*' -sS --max-time 4 -o /dev/null -w '%{http_code}' http://10.77.0.1:8787/")
    after = remote(status_command)
    stable = before['exit'] == after['exit'] == 0 and before['output'] == after['output']
    verified = egress_verified(before, after, results)
    report = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'source': 'verified_jingtian-mac_ssh_read_only', 'settings_changed': False,
              'vpn_session_before': before['output'], 'vpn_session_after': after['output'],
              'session_stable_during_measurement': stable, 'checks': results,
              'full_tunnel_egress_verified': verified,
              'limits': 'Specific IPv4/IPv6 egress probes only; no claim about Netflix region or all application DNS traffic.'}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
