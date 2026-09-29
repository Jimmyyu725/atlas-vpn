#!/usr/bin/env python3
"""Report safe deployment metadata, never private keys or full wg dumps."""
import json
from pathlib import Path
import subprocess

active = subprocess.run(["systemctl", "is-active", "--quiet", "wg-quick@atlasvpn.service"]).returncode == 0
exists = Path("/sys/class/net/atlasvpn").exists()
port = subprocess.run(["sudo", "-n", "wg", "show", "atlasvpn", "listen-port"], capture_output=True, text=True)
print(json.dumps({"service_active": active, "interface_exists": exists,
                  "listen_port": int(port.stdout.strip()) if port.returncode == 0 else None}, sort_keys=True))
