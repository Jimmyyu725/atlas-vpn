#!/usr/bin/env python3
"""Test actual encrypted VPN forwarding in a temporary client namespace.

The transport socket is born on Atlas: this is deliberately not proof of an
external device's inbound UDP reachability or of Netflix playback.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

NS = "atlas-vpn-test"
LINK = "avtest0"


def run(*args, data=None, check=True):
    return subprocess.run(args, input=data, text=True, capture_output=True, check=check)


def inside(*args, check=True):
    return run("ip", "netns", "exec", NS, *args, check=check)


def trace(family):
    result = inside("curl", "--noproxy", "*", family, "-fsS", "--max-time", "20",
                    "https://www.cloudflare.com/cdn-cgi/trace")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def main():
    assert os.geteuid() == 0, "Root is needed for the isolated network namespace"
    assert NS not in [line.split()[0] for line in run("ip", "netns", "list").stdout.splitlines()]
    assert run("ip", "link", "show", LINK, check=False).returncode != 0
    assert not Path(f"/etc/netns/{NS}").exists()
    pub = None
    created = False
    with tempfile.TemporaryDirectory(prefix="atlas-vpn-test-", dir="/run") as tmp:
        private = run("wg", "genkey").stdout.strip()
        pub = run("wg", "pubkey", data=private + "\n").stdout.strip()
        server_pub = run("wg", "show", "atlasvpn", "public-key").stdout.strip()
        key_path = Path(tmp) / "key"
        key_path.write_text(private + "\n")
        key_path.chmod(0o600)
        psk_path = Path(tmp) / "psk"
        psk_path.write_text(run("wg", "genpsk").stdout)
        psk_path.chmod(0o600)
        try:
            run("ip", "netns", "add", NS)
            created = True
            run("ip", "link", "add", LINK, "type", "wireguard")
            run("wg", "set", LINK, "private-key", str(key_path), "peer", server_pub,
                "preshared-key", str(psk_path), "allowed-ips", "0.0.0.0/0,::/0", "endpoint", "127.0.0.1:51820")
            run("ip", "link", "set", LINK, "netns", NS)
            inside("ip", "link", "set", "lo", "up")
            inside("ip", "address", "add", "10.77.0.254/32", "dev", LINK)
            inside("ip", "-6", "address", "add", "fd42:6174:6c61:7300::fe/128", "dev", LINK, "nodad")
            inside("ip", "link", "set", LINK, "mtu", "1380", "up")
            inside("ip", "route", "add", "default", "dev", LINK)
            inside("ip", "-6", "route", "add", "default", "dev", LINK)
            dns = Path(f"/etc/netns/{NS}")
            dns.mkdir(parents=True)
            (dns / "resolv.conf").write_text("nameserver 1.1.1.1\nnameserver 1.0.0.1\n")
            run("wg", "set", "atlasvpn", "peer", pub,
                "preshared-key", str(psk_path), "allowed-ips", "10.77.0.254/32,fd42:6174:6c61:7300::fe/128")
            v4 = trace("-4")
            v6 = trace("-6")
            assert v4["loc"] == "US" and v6["loc"] == "US"
            # Match each family's actual host egress, not just its country label.
            for family, observed in [("-4", v4), ("-6", v6)]:
                host = run("curl", "--noproxy", "*", family, "-fsS", "--max-time", "20",
                           "https://www.cloudflare.com/cdn-cgi/trace").stdout
                expected = dict(line.split("=", 1) for line in host.splitlines() if "=" in line)
                assert observed["ip"] == expected["ip"]
            handshakes = run("wg", "show", "atlasvpn", "latest-handshakes").stdout.splitlines()
            assert any(line.startswith(pub + "\t") and int(line.split()[1]) > 0 for line in handshakes)
            print("TUNNEL PASS encrypted_handshake=true dns=true ipv4=US ipv6=US matches_atlas=true", flush=True)
            run("wg", "set", "atlasvpn", "peer", pub, "remove")
            denied = inside("curl", "--noproxy", "*", "-4", "-kfsS", "--max-time", "4",
                            "https://1.1.1.1/cdn-cgi/trace", check=False)
            assert denied.returncode != 0, "Revoked peer still has internet access"
            print(f"REVOKE PASS client_curl_exit={denied.returncode}", flush=True)
            run("wg", "set", "atlasvpn", "peer", pub,
                "preshared-key", str(psk_path), "allowed-ips", "10.77.0.254/32,fd42:6174:6c61:7300::fe/128")
            assert trace("-4")["loc"] == "US"
            print("RESTORE_PEER PASS ipv4=US", flush=True)
            state_path = Path(__file__).resolve().parents[1] / "deployment.json"
            state = json.loads(state_path.read_text())
            state["server_tunnel_test"] = "passed_ipv4_ipv6_dns"
            state_path.write_text(json.dumps(state, indent=2) + "\n")
            print("SCOPE server_namespace_only; external_device=not_tested; netflix_playback=not_tested", flush=True)
        finally:
            if pub:
                run("wg", "set", "atlasvpn", "peer", pub, "remove", check=False)
            if created:
                run("ip", "netns", "delete", NS, check=False)
            run("ip", "link", "delete", LINK, check=False)
            dns = Path(f"/etc/netns/{NS}")
            if dns.exists():
                (dns / "resolv.conf").unlink(missing_ok=True)
                dns.rmdir()


if __name__ == "__main__":
    main()
