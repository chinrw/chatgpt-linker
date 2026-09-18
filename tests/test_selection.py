import json
import os
import subprocess

from chatgpt_linker.sanitize import Policy, Sanitizer, select_files
from support import Fixture


class AutoSelectionTests(Fixture):
    def populate(self):
        (self.repo / 'src').mkdir()
        (self.repo / 'src' / 'a.py').write_text('a = 1\n', encoding='utf8')
        (self.repo / 'src' / 'b.py').write_text('b = 2\n', encoding='utf8')
        (self.repo / 'src' / 'blob.bin').write_bytes(b'\x00\x01\x02')
        (self.repo / 'src' / 'huge.py').write_bytes(b'#' * 200_001)
        (self.repo / 'node_modules').mkdir()
        (self.repo / 'node_modules' / 'x.py').write_text('x = 1\n', encoding='utf8')
        (self.repo / '.env').write_text('SECRET=1\n', encoding='utf8')
        (self.repo / 'uv.lock').write_text('lock\n', encoding='utf8')
        os.symlink(self.repo / 'src' / 'a.py', self.repo / 'src' / 'link.py')

    def test_select_all_allowed_skips_denied_binary_and_oversize(self):
        self.populate()
        self.write_policy(globs=['*'])
        names, skipped = select_files(Policy.load(self.policy))
        self.assertEqual(names, ['PLAN.md', 'code.py', 'src/a.py', 'src/b.py'])
        self.assertEqual({(s['path'], s['reason']) for s in skipped},
                         {('src/blob.bin', 'not_text'), ('src/huge.py', 'too_large')})

    def test_policy_denied_globs_and_narrowing_globs(self):
        self.populate()
        self.write_policy(globs=['*'], extra='denied_globs = ["src/b.py"]\n')
        policy = Policy.load(self.policy)
        self.assertEqual(select_files(policy)[0], ['PLAN.md', 'code.py', 'src/a.py'])
        self.assertEqual(select_files(policy, ['src/*'])[0], ['src/a.py'])
        self.assertBridge('EXCLUDED_FILE', policy.check_path, 'src/b.py')

    def test_prepare_auto_records_every_selected_file(self):
        self.populate()
        self.write_policy(globs=['*'])
        task = self.store.prepare(self.policy, 'PLAN.md', [], 'Review', auto=True)
        self.assertEqual(task['files'], 4)
        self.assertEqual([s['reason'] for s in task['skipped']], ['not_text', 'too_large'])
        self.store.publish(task['request_id'], approve=True)
        found = self.store.exchange.search(task['request_id'] + ' b = 2')
        self.assertEqual([r['title'] for r in found['results']], ['src/b.py'])

    def test_max_files_is_policy_configurable_and_enforced(self):
        self.populate()
        self.write_policy(globs=['*'], extra='max_files = 3\n')
        self.assertBridge('INPUT_LIMIT', self.store.prepare, self.policy, 'PLAN.md', [], 'Review', auto=True)
        self.write_policy(globs=['*'], extra='max_files = 99999\n')
        self.assertBridge('INVALID_POLICY', Policy.load, self.policy)
        self.write_policy(globs=['*'], extra='max_bundle_bytes = 10\n')
        self.assertBridge('BUNDLE_LIMIT', self.store.prepare, self.policy, 'PLAN.md', [], 'Review', auto=True)

    def test_cli_prepare_auto_and_glob(self):
        self.populate()
        self.write_policy(auto=True, globs=['*'])
        out = subprocess.run(self.command + ['prepare', '--policy', str(self.policy), '--plan', 'PLAN.md',
                                             '--auto', '--glob', 'src/*', '--goal', 'Review', '--publish'],
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        task = json.loads(out.stdout)
        self.assertEqual(task['status'], 'waiting_for_chatgpt')
        self.assertEqual(task['files'], 3)  # PLAN.md + src/a.py + src/b.py

    def test_policy_init_writes_deny_list(self):
        out = subprocess.run(self.command + ['policy-init', '--repo', str(self.repo), '--output', str(self.base / 'p2.toml'),
                                             '--allow', '*', '--deny', 'docs/internal/*', '--auto-publish'],
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        policy = Policy.load(self.base / 'p2.toml')
        self.assertEqual(policy.denied_globs, ('docs/internal/*',))
        self.assertTrue(policy.auto_publish)


class GlobalSensitiveTests(Fixture):
    def test_global_file_merges_into_every_policy(self):
        self.write_sensitive('block_literals = ["AcmeCustomer"]\n[[redactions]]\nliteral = "acme-internal.example"\nreplacement = "<INTERNAL_HOST>"\n')
        clean = Sanitizer(Policy.load(self.policy))
        self.assertEqual(clean.clean('see acme-internal.example'), 'see <INTERNAL_HOST>')
        self.assertBridge('SENSITIVE_LITERAL', clean.clean, 'AcmeCustomer data')

    def test_global_file_only_tightens(self):
        self.write_sensitive('allowed_globs = ["*"]\n')
        self.assertBridge('INVALID_POLICY', Policy.load, self.policy)

    def test_global_file_permissions_checked(self):
        self.write_sensitive('block_literals = ["x"]\n')
        self.sensitive.chmod(0o666)
        self.assertBridge('UNSAFE_POLICY', Policy.load, self.policy)

    def test_missing_global_file_is_fine(self):
        self.assertEqual(Policy.load(self.policy).block_literals, ())
