import os
from pathlib import Path

from support import Fixture
from chatgpt_linker.fs import read_source, relative_parts
from chatgpt_linker.sanitize import Policy, Sanitizer, scan, valid_text

class SanitizationTests(Fixture):
    def test_known_credentials(self):
        samples = ['sk-proj-' + 'a'*32, 'ghp_' + 'b'*30, 'AKIA' + 'A'*16,
                   '-----BEGIN RSA PRIVATE KEY-----', 'postgres://alice:supersecret@db/x',
                   'https://host/path?X-Amz-Signature=abcdef', 'password = "verysecret"']
        for sample in samples:
            with self.subTest(sample_category=sample[:5]):
                self.assertTrue(scan(sample))

    def test_env_references_and_placeholders(self):
        self.assertEqual(scan('password = ${PASSWORD}\napi_key = <REDACTED>\nsecret_key = os.environ.get("SECRET")'), [])

    def test_semantic_redactions_stable(self):
        self.write_policy(extra='[[redactions]]\nliteral = "InternalProduct"\nreplacement = "<PROJECT>"\n')
        clean = Sanitizer(Policy.load(self.policy))
        a = clean.clean('InternalProduct alice@example.com 10.1.2.3')
        self.assertEqual(a, clean.clean('InternalProduct alice@example.com 10.1.2.3'))
        self.assertNotIn('alice@', a)
        self.assertNotIn('10.1.2.3', a)
        self.assertIn('<PROJECT>', a)

    def test_rewrites_cannot_hide_credentials(self):
        key = 'sk-proj-' + 'Z'*32
        self.write_policy(extra=f'[[redactions]]\nliteral = "{key}"\nreplacement = "hidden"\n')
        self.assertBridge('SECRET_DETECTED', Sanitizer(Policy.load(self.policy)).clean, key)

    def test_block_literal(self):
        self.write_policy(extra='block_literals = ["customer-secret-name"]\n')
        self.assertBridge('SENSITIVE_LITERAL', Sanitizer(Policy.load(self.policy)).clean, 'customer-secret-name')

    def test_redaction_cannot_introduce_secret(self):
        self.write_policy(extra='[[redactions]]\nliteral = "safe"\nreplacement = "password=nonplaceholder"\n')
        self.assertBridge('SECRET_DETECTED', Sanitizer(Policy.load(self.policy)).clean, 'safe')

    def test_goal_scanned(self):
        self.assertBridge('SECRET_DETECTED', self.store.prepare, self.policy, 'PLAN.md', [], 'api_key="do-not-export-this"')

    def test_deleted_diff_line_scanned(self):
        (self.repo / 'PLAN.md').write_text('- password = "previously-leaked"\n')
        self.assertBridge('SECRET_DETECTED', self.prepare)

    def test_title_scanned(self):
        name = 'sk-proj-' + 'q'*30 + '.py'
        (self.repo / name).write_text('pass\n')
        self.assertBridge('SECRET_DETECTED', self.store.prepare, self.policy, 'PLAN.md', [name], 'Review')

    def test_excluded_names(self):
        policy = Policy.load(self.policy)
        for name in ('.env', '.env.example', 'auth.json', '.git/config', 'private.pem', 'data.csv', 'app.log', '.ssh/key'):
            with self.subTest(name=name):
                self.assertBridge('EXCLUDED_FILE', policy.check_path, name)

    def test_unknown_policy_key_rejected(self):
        self.write_policy(extra='typo_allow = true\n')
        self.assertBridge('INVALID_POLICY', Policy.load, self.policy)

    def test_policy_type_rejected(self):
        self.write_policy(extra='ttl_hours = "24"\n')
        self.assertBridge('INVALID_POLICY', Policy.load, self.policy)

    def test_policy_in_repository_rejected(self):
        inside = self.repo / 'policy.toml'
        inside.write_bytes(self.policy.read_bytes())
        self.assertBridge('UNTRUSTED_POLICY', Policy.load, inside)

    def test_file_outside_allowlist(self):
        (self.repo / 'note.txt').write_text('safe')
        self.assertBridge('OUT_OF_SCOPE', self.store.prepare, self.policy, 'PLAN.md', ['note.txt'], 'Review')

    def test_nontext_and_long_lines(self):
        for data, code in [(b'\xff', 'NON_TEXT'), (b'abc\x00def', 'NON_TEXT'), (b'x'*12001, 'LINE_TOO_LONG')]:
            self.assertBridge(code, valid_text, data)
        self.assertEqual(valid_text(b'a\r\nb\rc'), 'a\nb\nc')

    def test_traversal_forms(self):
        for name in ('../secret', '/etc/passwd', 'a//b', './a', 'a/../b', 'a\\b', 'a\x00b'):
            with self.subTest(name=repr(name)):
                self.assertBridge('INVALID_PATH', relative_parts, name)

    def test_final_symlink(self):
        (self.repo / 'linked.py').symlink_to(self.repo / 'code.py')
        self.assertBridge('UNSAFE_FILE', read_source, self.repo, 'linked.py', 1000)

    def test_intermediate_symlink(self):
        (self.repo / 'src').symlink_to(self.base, target_is_directory=True)
        self.assertBridge('UNSAFE_FILE', read_source, self.repo, 'src/policy.toml', 1000)

    def test_hardlink_and_fifo(self):
        os.link(self.repo / 'code.py', self.repo / 'hard.py')
        self.assertBridge('UNSAFE_FILE', read_source, self.repo, 'hard.py', 1000)
        os.mkfifo(self.repo / 'fifo.py')
        self.assertBridge('UNSAFE_FILE', read_source, self.repo, 'fifo.py', 1000)

    def test_size_limit(self):
        (self.repo / 'huge.py').write_bytes(b'x'*200001)
        self.assertBridge('FILE_TOO_LARGE', self.store.prepare, self.policy, 'PLAN.md', ['huge.py'], 'Review')

    def test_source_unchanged_and_no_secret_mapping_saved(self):
        original = 'Contact alice@example.com at 192.168.1.2\n'
        (self.repo / 'code.py').write_text(original)
        task = self.prepare()
        self.assertEqual((self.repo / 'code.py').read_text(), original)
        bundle = (self.store.private / task['request_id'] / 'candidate.json').read_text()
        self.assertNotIn('alice@example.com', bundle)
        self.assertNotIn('192.168.1.2', bundle)
        self.assertEqual({p.name for p in (self.store.private / task['request_id']).iterdir()}, {'candidate.json', 'provenance.json'})

    def test_policy_not_writable_by_others(self):
        self.policy.chmod(0o666)
        self.assertBridge('UNSAFE_POLICY', Policy.load, self.policy)

    def test_final_redacted_text_revalidated(self):
        self.write_policy(extra='[[redactions]]\nliteral = "xx"\nreplacement = "'+ 'y'*1000 +'"\n')
        self.assertBridge('LINE_TOO_LONG', Sanitizer(Policy.load(self.policy)).clean, 'xx'*15)
