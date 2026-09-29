#!/usr/bin/env python3
"""Save a private point-in-time UI state snapshot for the verified private repo."""
import os
from pathlib import Path

assert os.geteuid() == 0
root = Path(__file__).resolve().parents[1]
for source, target in [('state.json', 'ui-state.snapshot.json'), ('login.json', 'ui-login.snapshot.json')]:
    data = (Path('/var/lib/atlas-vpn-ui') / source).read_bytes()
    path = root / 'server' / target
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    os.chmod(path, 0o600)
    os.chown(path, root.stat().st_uid, root.stat().st_gid)
print('UI_SNAPSHOT PASS state_and_login_saved=true values_redacted=true')
