import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from chatgpt_linker.store import LocalStore

ROOT = Path(__file__).resolve().parents[1]
REVIEW = '''## Summary
Keep the current interface and add an optional prefix. This is a synthetic test.
## Evidence
The draft requires backward compatibility [d0001:L1-L3].
## Plan
1. Preserve the default. 2. Add a keyword-only parameter. 3. Add regression tests.
## Validation
Test default and custom prefix; empty input needs an explicit policy.
## Risks
Callers may rely on current output. Roll back the additive change if necessary.
## Open Questions
Should empty input be rejected or accepted?
'''

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / 'project'
        self.repo.mkdir()
        (self.repo / 'PLAN.md').write_text('# Draft\nPreserve compatibility.\nAdd tests.\n', encoding='utf8')
        (self.repo / 'code.py').write_text('def greet(name):\n    return f"Hello, {name}!"\n', encoding='utf8')
        self.policy = self.base / 'policy.toml'
        self.write_policy()
        self.sensitive = self.base / 'sensitive.toml'
        self._old_sensitive = os.environ.get('CHATGPT_LINKER_SENSITIVE')
        os.environ['CHATGPT_LINKER_SENSITIVE'] = str(self.sensitive)
        self.store = LocalStore(self.base / 'state', create=True)
        self.env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        self.command = [sys.executable, '-m', 'chatgpt_linker', '--state', str(self.store.root)]

    def tearDown(self):
        if self._old_sensitive is None:
            os.environ.pop('CHATGPT_LINKER_SENSITIVE', None)
        else:
            os.environ['CHATGPT_LINKER_SENSITIVE'] = self._old_sensitive
        self.temp.cleanup()

    def write_sensitive(self, text):
        self.sensitive.write_text('version = 1\n' + text, encoding='utf8')
        self.sensitive.chmod(0o600)

    def write_policy(self, *, auto=False, extra='', globs=None):
        self.policy.write_text('version = 1\nproject_root = ' + json.dumps(str(self.repo)) +
             '\nallowed_globs = ' + json.dumps(globs or ['*.md', '*.py', 'src/*']) +
             '\nauto_publish = ' + str(auto).lower() + '\n' + extra, encoding='utf8')
        self.policy.chmod(0o600)

    def prepare(self, **kwargs):
        return self.store.prepare(self.policy, 'PLAN.md', ['code.py'], 'Review compatibility', **kwargs)

    def published(self, **kwargs):
        task = self.prepare()
        self.store.publish(task['request_id'], approve=True, **kwargs)
        return task['request_id'], task['bundle_sha256']

    def assertBridge(self, code, func, *args, **kwargs):
        from chatgpt_linker.errors import BridgeError
        with self.assertRaises(BridgeError) as cm:
            func(*args, **kwargs)
        self.assertEqual(cm.exception.code, code)
