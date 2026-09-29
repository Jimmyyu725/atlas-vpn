#!/usr/bin/env python3
"""Remove only the recorded disabled acceptance-test profile; stop UI first."""
import copy
import importlib.util
import os
from pathlib import Path
import re
import subprocess

assert os.geteuid() == 0
assert subprocess.run(['systemctl','is-active','--quiet','atlas-vpn-ui.service']).returncode != 0
root=Path(__file__).resolve().parents[1]
name=(root/'evidence/ui/browser-test-device.txt').read_text().strip()
assert re.fullmatch(r'ui-smoke-[a-z0-9]+',name)
spec=importlib.util.spec_from_file_location('atlas_ui','/usr/local/lib/atlas-vpn-ui/app.py')
app=importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
store=app.Store(); state=copy.deepcopy(store.state)
assert name in state['devices'] and not state['devices'][name]['enabled']
del state['devices'][name]
store.save(state)
print('UI_TEST_CLEANUP PASS disabled_test_profile_removed=true other_profiles=preserved')
