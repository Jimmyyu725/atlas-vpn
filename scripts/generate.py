#!/usr/bin/env python3
"""Generate per-device WireGuard files without printing key material."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args, data=None):
    return subprocess.check_output(args, input=data, text=True).strip()


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)
    path.chmod(0o600)


def generate():
    os.umask(0o077)
    config = json.loads((ROOT / "config.json").read_text())
    key_path = ROOT / "server/keys.json"
    keys = json.loads(key_path.read_text()) if key_path.exists() else {}
    if "server" not in keys:
        keys["server"] = run("wg", "genkey")
    for name in config["initial_devices"]:
        if name not in keys:
            keys[name] = {"private": run("wg", "genkey"), "psk": run("wg", "genpsk")}
    private_write(key_path, json.dumps(keys, indent=2) + "\n")
    server_public = run("wg", "pubkey", data=keys["server"] + "\n")
    v4 = ipaddress.ip_interface(config["server_ipv4"]).network
    v6 = ipaddress.ip_interface(config["server_ipv6"]).network
    server = [
        "[Interface]", f"PrivateKey = {keys['server']}",
        f"Address = {config['server_ipv4']}, {config['server_ipv6']}",
        f"ListenPort = {config['port']}", f"MTU = {config['mtu']}",
        "PostUp = /usr/local/lib/atlas-vpn/firewall.sh up",
        "PostDown = /usr/local/lib/atlas-vpn/firewall.sh down", "",
    ]
    devices = []
    for offset, name in enumerate(config["initial_devices"], start=2):
        key = keys[name]
        public = run("wg", "pubkey", data=key["private"] + "\n")
        address = f"{v4[offset]}/32, {v6[offset]}/128"
        client = "\n".join([
            f"# Atlas VPN - {name}", "[Interface]",
            f"PrivateKey = {key['private']}", f"Address = {address}",
            f"DNS = {', '.join(config['dns'])}", f"MTU = {config['mtu']}", "",
            "[Peer]", f"PublicKey = {server_public}", f"PresharedKey = {key['psk']}",
            "AllowedIPs = 0.0.0.0/0, ::/0",
            f"Endpoint = {config['endpoint']}:{config['port']}",
            "PersistentKeepalive = 25", "",
        ])
        path = ROOT / "clients" / f"atlas-{name}.conf"
        private_write(path, client)
        subprocess.run(["qrencode", "-l", "M", "-s", "6", "-o", str(path.with_suffix(".png"))],
                       input=client, text=True, check=True)
        path.with_suffix(".png").chmod(0o600)
        server.extend([f"# {name}", "[Peer]", f"PublicKey = {public}",
                       f"PresharedKey = {key['psk']}", f"AllowedIPs = {address}", ""])
        devices.append({"name": name, "public_key": public, "address": address})
    private_write(ROOT / "server/atlasvpn.conf", "\n".join(server))
    private_write(ROOT / "server/devices.json", json.dumps(devices, indent=2) + "\n")
    print(f"GENERATED devices={len(devices)}; keys_redacted=true")


if __name__ == "__main__":
    generate()
