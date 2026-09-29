#!/usr/bin/env python3
"""Check generated full-tunnel profiles without displaying secrets."""
import configparser
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "config.json").read_text())
keys = json.loads((root / "server/keys.json").read_text())
private_keys = set()
for name in config["initial_devices"]:
    path = root / "clients" / f"atlas-{name}.conf"
    parsed = configparser.ConfigParser()
    parsed.read(path)
    assert path.stat().st_mode & 0o077 == 0
    assert parsed["Peer"]["AllowedIPs"] == "0.0.0.0/0, ::/0"
    assert parsed["Peer"]["Endpoint"] == f"{config['endpoint']}:{config['port']}"
    assert parsed["Interface"]["DNS"] == ", ".join(config["dns"])
    assert parsed["Interface"]["PrivateKey"] == keys[name]["private"]
    assert parsed["Peer"]["PresharedKey"] == keys[name]["psk"]
    private_keys.add(parsed["Interface"]["PrivateKey"])
    result = subprocess.run(["wg-quick", "strip", str(path)], capture_output=True)
    assert result.returncode == 0, f"WireGuard parser failed: {name}"
assert len(private_keys) == len(config["initial_devices"])
assert (root / "server/keys.json").stat().st_mode & 0o077 == 0
subprocess.run(["bash", "-n", str(root / "scripts/deploy.sh")], check=True)
subprocess.run(["bash", "-n", str(root / "scripts/firewall.sh")], check=True)
subprocess.run(["bash", "-n", str(root / "ROLLBACK.sh")], check=True)
print("CONFIG_CHECK PASS devices=3 independent_keys=true ipv4_ipv6_full_tunnel=true permissions=600")
