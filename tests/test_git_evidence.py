import io
import json
import os
import subprocess
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

from chatgpt_linker.git_evidence import github_json, github_slug, public_baseline, working_delta
from chatgpt_linker.cli import parser, run
from support import Fixture, REVIEW


class PublicEvidenceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic Tester')
        self.git('config', 'user.email', 'synthetic@example.invalid')
        self.git('add', '.')
        self.git('commit', '-m', 'Synthetic public baseline')
        self.sha = self.git('rev-parse', 'HEAD').strip()
        self.git('remote', 'add', 'origin', 'git@github.com:example/synthetic.git')
        self.git('update-ref', 'refs/remotes/origin/main', self.sha)
        self.git('branch', '--set-upstream-to=origin/main')
        self.api = patch('chatgpt_linker.git_evidence.github_json', side_effect=self.public_response)
        self.mock_api = self.api.start()
        self.addCleanup(self.api.stop)

    def git(self, *args):
        env = {k: v for k, v in self.env.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run(['git', '-C', str(self.repo), *args], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def public_response(self, path):
        if path == 'example/synthetic':
            return {'full_name': 'example/synthetic', 'private': False,
                    'visibility': 'public', 'default_branch': 'main'}
        return {'sha': self.sha}

    def task(self, **kwargs):
        return self.store.prepare(self.policy, None, [], 'Review the current plan',
                                  draft='Current context\nDraft plan\nCheck compatibility\n',
                                  public_repo=True, **kwargs)

    def documents(self, task):
        return json.loads((self.store.private / task['request_id'] / 'candidate.json').read_text())['payload']['documents']

    def test_clean_tree_sends_only_plan_and_public_pointer(self):
        task = self.task()
        docs = self.documents(task)
        self.assertEqual([d['kind'] for d in docs], ['original_plan', 'public_baseline'])
        self.assertIn('/tree/' + self.sha, docs[1]['text'])
        self.assertNotIn('def greet', json.dumps(docs))
        self.assertEqual(task['public_baseline']['verification'], 'anonymous_github_api')
        self.assertEqual(self.mock_api.call_count, 2)

    def test_overlay_covers_unpushed_staged_unstaged_untracked_and_rename(self):
        (self.repo / 'committed.py').write_text('committed = 1\n')
        self.git('add', 'committed.py')
        self.git('commit', '-m', 'Synthetic unpushed change')
        (self.repo / 'staged.py').write_text('staged = 2\n')
        self.git('add', 'staged.py')
        (self.repo / 'code.py').write_text('changed = 3\n')
        (self.repo / 'new file.py').write_text('untracked = 4\n')
        self.git('mv', 'PLAN.md', 'renamed.md')
        task = self.task()
        docs = self.documents(task)
        self.assertEqual({d['title'] for d in docs[2:]},
                         {'committed.py', 'staged.py', 'code.py', 'new file.py', 'renamed.md'})
        self.assertIn('"status": "D"', docs[1]['text'])
        self.assertIn('"path": "PLAN.md"', docs[1]['text'])
        self.assertIn('changed = 3', json.dumps(docs))
        self.assertEqual(task['public_baseline']['baseline_sha'], self.sha)

    def test_publish_fetch_submit_result_with_public_evidence(self):
        task = self.task()
        rid = task['request_id']
        self.store.publish(rid, approve=True)
        request = self.store.exchange.fetch(rid + ':request')
        self.assertIn('public_baseline', json.dumps(request))
        review = REVIEW + '\nPublic pointer: https://github.com/example/synthetic/blob/' + self.sha + '/code.py#L1\n'
        self.store.exchange.submit(rid, task['bundle_sha256'], review)
        result = self.store.result(rid)
        self.assertTrue(result['source_check']['unchanged'])
        self.assertEqual(result['receipt']['model_attestation'], 'unverified')

    def test_public_mode_honors_policy_and_reports_omissions(self):
        (self.repo / 'code.py').write_text('password="synthetic-sensitive-value"\n')
        (self.repo / 'image.bin').write_bytes(b'\0\1')
        (self.repo / 'internal.py').write_text('internal = 1\n')
        self.write_policy(globs=['*'], extra='denied_globs = ["internal.py"]\n')
        task = self.task()
        reasons = {item['path']: item['reason'] for item in task['skipped']}
        self.assertEqual(reasons['code.py'], 'SECRET_DETECTED')
        self.assertEqual(reasons['image.bin'], 'NON_TEXT')
        self.assertEqual(reasons['internal.py'], 'EXCLUDED_FILE')
        self.assertNotIn('synthetic-sensitive-value', json.dumps(self.documents(task)))

    def test_new_changes_and_restored_deletions_invalidate_source(self):
        (self.repo / 'code.py').unlink()
        task = self.task()
        (self.repo / 'new.py').write_text('new = 1\n')
        self.assertFalse(self.store.check_source(task['request_id'])['unchanged'])
        self.assertBridge('SOURCE_CHANGED', self.store.publish, task['request_id'], approve=True)
        (self.repo / 'new.py').unlink()
        self.assertTrue(self.store.check_source(task['request_id'])['unchanged'])
        (self.repo / 'code.py').write_text('restored = 1\n')
        self.assertTrue(self.store.check_source(task['request_id'])['git_delta_changed'])

    def test_changed_overlay_contents_invalidate_source(self):
        (self.repo / 'code.py').write_text('first = 1\n')
        task = self.task()
        (self.repo / 'code.py').write_text('second = 2\n')
        check = self.store.check_source(task['request_id'])
        self.assertEqual(check['changed_files'], ['code.py'])
        self.assertFalse(check['unchanged'])

    def test_mode_change_and_symlink_are_accounted_for(self):
        (self.repo / 'code.py').chmod(0o755)
        (self.repo / 'link.py').symlink_to('code.py')
        task = self.task()
        self.assertIn('100755', self.documents(task)[1]['text'])
        self.assertIn({'path': 'link.py', 'reason': 'UNSUPPORTED_GIT_ENTRY'}, task['skipped'])

    def test_visibility_or_unpublished_sha_failure_does_not_prepare(self):
        for response in ({'private': True, 'visibility': 'private'},
                         {'private': False, 'visibility': 'public', 'full_name': 'other/repo'}):
            self.mock_api.side_effect = None
            self.mock_api.return_value = response
            self.assertBridge('PUBLIC_REPO_UNVERIFIED', self.task)
        self.mock_api.side_effect = [self.public_response('example/synthetic'), {'sha': '0' * 40}]
        self.assertBridge('PUBLIC_REPO_UNVERIFIED', self.task)
        self.assertEqual(list(self.store.private.iterdir()), [])

    def test_no_upstream_and_explicit_base(self):
        self.git('branch', '--unset-upstream')
        self.assertEqual(public_baseline(self.repo)['baseline_sha'], self.sha)
        self.assertEqual(public_baseline(self.repo, base=self.sha)['baseline_sha'], self.sha)

    def test_non_ancestor_base_rejected(self):
        self.git('checkout', '--orphan', 'other')
        self.git('commit', '-m', 'Unrelated root')
        self.assertBridge('GIT_EVIDENCE', public_baseline, self.repo, base=self.sha)

    def test_public_mode_does_not_run_diff_helpers_or_write_index(self):
        marker = self.base / 'helper-was-run'
        self.git('config', 'diff.external', f'touch {marker}')
        self.git('config', 'core.fsmonitor', f'touch {marker}')
        (self.repo / 'code.py').write_text('changed = 1\n')
        index = self.repo / '.git' / 'index'
        before = index.read_bytes()
        self.task()
        self.assertFalse(marker.exists())
        self.assertEqual(index.read_bytes(), before)

    def test_worktree_diff_does_not_execute_clean_or_process_filters(self):
        marker = self.base / 'filter-was-run'
        (self.repo / '.gitattributes').write_text('code.py filter=custom\n')
        self.git('config', 'filter.custom.clean', f'touch {marker}')
        self.git('config', 'filter.custom.process', f'touch {marker}')
        self.git('config', 'filter.custom.required', 'true')
        (self.repo / 'code.py').write_text('changed = 1\n')
        task = self.task()
        self.assertFalse(marker.exists())
        self.assertIn('code.py', [d['title'] for d in self.documents(task)])

    def test_staged_deletion_with_recreated_file_uses_current_contents(self):
        self.git('rm', 'code.py')
        (self.repo / 'code.py').write_text('recreated = 1\n')
        task = self.task()
        docs = self.documents(task)
        self.assertIn('code.py', [d['title'] for d in docs])
        self.assertIn('recreated = 1', json.dumps(docs))
        self.assertNotIn('"status": "D"', docs[1]['text'])

    def test_assume_unchanged_does_not_hide_local_changes(self):
        self.git('update-index', '--assume-unchanged', 'code.py')
        (self.repo / 'code.py').write_text('hidden = 1\n')
        self.assertBridge('GIT_EVIDENCE', self.task)

    def test_cli_public_flags_and_repo_info_without_state_creation(self):
        missing_state = self.base / 'missing-state'
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run(parser().parse_args([
                '--state', str(missing_state), 'repo-info', '--repo', str(self.repo),
                '--remote', 'origin', '--base', self.sha])), 0)
        self.assertFalse(missing_state.exists())
        self.assertEqual(json.loads(output.getvalue())['baseline_sha'], self.sha)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run(parser().parse_args([
                '--state', str(self.store.root), 'prepare', '--policy', str(self.policy),
                '--plan', 'PLAN.md', '--goal', 'Review', '--public-repo',
                '--remote', 'origin', '--base', self.sha])), 0)
        self.assertEqual(json.loads(output.getvalue())['files'], 2)

    def test_conflicts_rejected(self):
        self.git('checkout', '-b', 'side')
        (self.repo / 'code.py').write_text('side = 1\n')
        self.git('commit', '-am', 'Side')
        self.git('checkout', 'main')
        (self.repo / 'code.py').write_text('main = 2\n')
        self.git('commit', '-am', 'Main')
        subprocess.run(['git', '-C', str(self.repo), 'merge', 'side'], capture_output=True)
        self.assertBridge('GIT_CONFLICT', working_delta, self.repo, self.sha)

    def test_public_and_auto_are_mutually_exclusive(self):
        self.assertBridge('INPUT_LIMIT', self.task, auto=True)

    def test_draft_only_bundle_limit_is_enforced(self):
        self.write_policy(extra='max_bundle_bytes = 10\n')
        self.assertBridge('BUNDLE_LIMIT', self.task)


class GitHubTransportTests(Fixture):
    def test_remote_parsing_rejects_credentials_and_other_hosts(self):
        for remote in ('git@github.com:owner/repo.git', 'https://github.com/owner/repo.git',
                       'ssh://git@github.com/owner/repo.git'):
            self.assertEqual(github_slug(remote), 'owner/repo')
        for remote in ('https://user:secret@github.com/owner/repo', 'https://example.com/owner/repo',
                       'https://github.com/owner/repo?token=secret'):
            self.assertBridge('PUBLIC_REPO_UNVERIFIED', github_slug, remote)

    def test_transport_is_anonymous_and_errors_do_not_leak_response(self):
        with patch('chatgpt_linker.git_evidence.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b'{"private": false}')
            self.assertEqual(github_json('owner/repo'), {'private': False})
            request = opener.return_value.open.call_args.args[0]
            self.assertNotIn('Authorization', request.headers)
            opener.return_value.open.side_effect = urllib.error.URLError('sensitive response')
            self.assertBridge('PUBLIC_REPO_UNVERIFIED', github_json, 'owner/repo')
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                request.full_url, 403, 'sensitive response', {}, None)
            self.assertBridge('PUBLIC_REPO_UNVERIFIED', github_json, 'owner/repo')
