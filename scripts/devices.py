#!/usr/bin/env python3
"""Show handshake and transfer counters using only public WireGuard fields."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

if Path('/usr/local/lib/atlas-vpn-ui/owner').exists():
    result = subprocess.check_output(['sudo', '-n', 'python3', '/usr/local/lib/atlas-vpn-ui/app.py', 'status'], text=True)
    for device in json.loads(result)['devices']:
        last = device.pop('last_handshake')
        device['last_handshake_utc'] = datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None
        print(json.dumps(device, ensure_ascii=False))
    raise SystemExit(0)

root = Path(__file__).resolve().parents[1]
devices = json.loads((root / "server/devices.json").read_text())


def field(name):
    result = subprocess.run(["sudo", "-n", "wg", "show", "atlasvpn", name],
                            check=True, capture_output=True, text=True)
    return {row[0]: row[1:] for line in result.stdout.splitlines() if (row := line.split())}


handshakes = field("latest-handshakes")
traffic = field("transfer")
for device in devices:
    key = device["public_key"]
    last = int(handshakes.get(key, ["0"])[0])
    received, sent = map(int, traffic.get(key, ["0", "0"]))
    print(json.dumps({"device": device["name"], "enabled": key in handshakes,
                      "last_handshake_utc": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                      "received_bytes": received, "sent_bytes": sent}, ensure_ascii=False))
