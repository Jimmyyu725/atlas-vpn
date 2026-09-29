"""No live interface changes: validate configuration and transaction semantics."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('atlas_ui', Path(__file__).with_name('app.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        keys = json.loads((ROOT/'server/keys.json').read_text())
        public = app.command('wg','pubkey',data=keys['server']+'\n')
        devices = json.loads((ROOT/'server/devices.json').read_text())
        self.state = {'config':json.loads((ROOT/'config.json').read_text()),
                      'server_key':keys['server'],'server_public':public,
                      'devices':{d['name']:{**keys[d['name']], 'public':d['public_key'], 'offset':i,'enabled':True}
                                 for i,d in enumerate(devices,start=2)}}
        self.path = self.base/'state.json'
        self.path.write_text(json.dumps(self.state))
        self.applied = []
        self.store = app.Store(self.base,self.base/'atlasvpn.conf',apply=lambda s:self.applied.append(copy.deepcopy(s)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_profiles_are_byte_identical(self):
        self.assertEqual(digest(app.server_config(self.state)),digest((ROOT/'server/atlasvpn.conf').read_text()))
        for name in self.state['devices']:
            self.assertEqual(digest(app.client_config(self.state,name)),digest((ROOT/f'clients/atlas-{name}.conf').read_text()))

    def test_add_disable_enable_preserves_existing_keys(self):
        self.store.change('add','test-device')
        self.assertEqual(self.store.state['devices']['test-device']['offset'],5)
        self.store.change('disable','test-device')
        self.assertNotIn('# test-device\n',app.server_config(self.store.state))
        self.store.change('enable','test-device')
        self.assertIn('# test-device\n',app.server_config(self.store.state))
        for name,device in self.state['devices'].items():
            self.assertEqual(digest(self.store.state['devices'][name]),digest(device))

    def test_reject_names_and_duplicates(self):
        for name in ['../x','a\nHeader: bad','<script>','A','',1,'a'*32,'iphone']:
            with self.assertRaises(ValueError): self.store.change('add',name)

    def test_keep_one_enabled_profile(self):
        self.store.change('disable','iphone')
        self.store.change('disable','mac')
        with self.assertRaises(ValueError): self.store.change('disable','windows')
        self.assertTrue(self.store.state['devices']['windows']['enabled'])

    def test_restore_previous_state_on_apply_error(self):
        calls=[]
        def fail_once(state):
            calls.append(state)
            if len(calls)==1: raise RuntimeError('injected failure')
        self.store.apply=fail_once
        with self.assertRaises(RuntimeError): self.store.change('disable','iphone')
        self.assertEqual(digest(self.store.state),digest(self.state))
        self.assertEqual(digest(json.loads(self.path.read_text())),digest(self.state))
        self.assertEqual(digest(self.store.config_path.read_text()),digest(app.server_config(self.state)))
        self.assertEqual(len(calls),2)


if __name__ == '__main__':
    unittest.main()
