"""Synthetic review rounds preserve snapshots while refreshing current inputs."""
import json
import subprocess
from pathlib import Path

from support import Fixture, REVIEW
from chatgpt_linker.fs import read_json
from chatgpt_linker.protocol import MCPApplication
from chatgpt_linker.store import LocalStore, checked_bundle


class FollowupTests(Fixture):
    def complete(self, task=None, report=REVIEW):
        task = task or self.prepare()
        rid = task['request_id']
        self.store.publish(rid, approve=True)
        self.store.exchange.submit(rid, task['bundle_sha256'], report)
        return rid

    def bundle(self, rid):
        return checked_bundle(read_json(self.store.private / rid / 'candidate.json'))

    def test_followup_refreshes_files_and_carries_full_verified_report(self):
        report = REVIEW + '\n' + 'Historical explanation.\n' * 800
        parent = self.complete(report=report)
        parent_bundle = self.bundle(parent)
        receipt = self.store.result(parent)['receipt']
        (self.repo / 'code.py').write_text('def greet(name):\n    return "Updated"\n')
        (self.repo / 'extra.md').write_text('New measurements\n')
        child = self.store.followup(parent, 'Reconsider the implementation.', ['extra.md'])
        self.assertEqual(child['conversation_id'], parent)
        self.assertEqual(child['parent_request_id'], parent)
        self.assertEqual(child['round'], 2)
        docs = {d['title']: d['text'] for d in self.bundle(child['request_id'])['payload']['documents']}
        self.assertIn('Updated', docs['code.py'])
        self.assertEqual(docs['extra.md'], 'New measurements\n')
        self.assertIn(report, docs['Previous review (historical)'])
        self.assertIn(receipt['result_sha256'], docs['Previous review (historical)'])
        self.assertIn('Preserve compatibility', docs['Previous task context (historical)'])
        self.assertEqual(self.bundle(parent), parent_bundle)
        self.assertEqual(self.store.result(parent)['receipt'], receipt)
        self.assertFalse(self.store.result(parent)['processed'])
        self.assertBridge('APPROVAL_REQUIRED', self.store.publish, child['request_id'])
        self.store.publish(child['request_id'], approve=True)
        self.store.cancel(parent)
        text = self.store.exchange.fetch(child['request_id'] + ':request')['text']
        self.assertIn('Previous review (historical)', text)
        prompt = self.store.prompt(child['request_id'])
        self.assertIn(parent, prompt)
        self.assertIn(child['request_id'], prompt)
        self.assertIn('第 2 轮', prompt)
        self.assertNotIn('deep research', prompt.lower())
        self.assertNotIn('/deepresearch', prompt.lower())
        self.assertIn('在当前对话中完成复审和报告提交', prompt)
        self.assertIn('普通 Chat', prompt)
        self.assertIn('无需访问旧任务', prompt)

    def test_conversation_supports_branches_and_restart(self):
        parent = self.complete()
        first = self.store.followup(parent, 'First branch', [])
        sibling = self.store.followup(parent, 'Second branch', [])
        self.complete(first)
        reloaded = LocalStore(self.store.root)
        third = reloaded.followup(first['request_id'], 'Continue first branch', [])
        unrelated = self.prepare()
        page = reloaded.list_tasks(conversation_id=parent)
        tasks = {t['request_id']: t for t in page['tasks']}
        self.assertEqual(set(tasks), {parent, first['request_id'], sibling['request_id'], third['request_id']})
        self.assertEqual(tasks[third['request_id']]['round'], 3)
        self.assertEqual(tasks[third['request_id']]['parent_request_id'], first['request_id'])
        self.assertNotIn(unrelated['request_id'], tasks)
        app = MCPApplication(local=reloaded)
        response = app.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'review_list', 'arguments': {'conversation_id': parent}}})
        self.assertEqual(len(response['result']['structuredContent']['tasks']), 4)

    def test_unfinished_cancelled_and_corrupt_parents_are_rejected(self):
        parent, _ = self.published()
        before = set(self.store.private.iterdir())
        self.assertBridge('NOT_COMPLETED', self.store.followup, parent, 'Question', [])
        self.assertEqual(set(self.store.private.iterdir()), before)
        parent = self.complete()
        self.store.cancel(parent)
        self.assertBridge('NOT_COMPLETED', self.store.followup, parent, 'Question', [])
        parent = self.complete()
        result = self.store.result(parent)
        Path(result['artifact_path']).write_text(REVIEW + 'tampered')
        before = set(self.store.private.iterdir())
        self.assertBridge('INTEGRITY_ERROR', self.store.followup, parent, 'Question', [])
        self.assertEqual(set(self.store.private.iterdir()), before)

    def test_changed_policy_and_limits_apply_to_followup(self):
        parent = self.complete()
        self.write_policy(globs=['*.md'])
        before = set(self.store.private.iterdir())
        self.assertBridge('OUT_OF_SCOPE', self.store.followup, parent, 'Question', [])
        self.assertEqual(set(self.store.private.iterdir()), before)
        self.write_policy(extra='max_files = 3\n')
        self.assertBridge('INPUT_LIMIT', self.store.followup, parent, 'Question', [])
        self.write_policy(extra='max_bundle_bytes = 200\n')
        self.assertBridge('BUNDLE_LIMIT', self.store.followup, parent, 'Question', [])
        self.assertEqual(set(self.store.private.iterdir()), before)

    def test_history_is_resanitized_under_current_policy(self):
        parent = self.complete(report=REVIEW + '\nContact alice@example.com\n')
        child = self.store.followup(parent, 'Question', [])
        report = next(d['text'] for d in self.bundle(child['request_id'])['payload']['documents']
                      if d['title'] == 'Previous review (historical)')
        self.assertNotIn('alice@example.com', report)
        self.assertIn('alice@example.com', self.store.result(parent)['markdown'])

    def test_deleted_or_secret_supplements_do_not_silently_disappear(self):
        parent = self.complete()
        (self.repo / 'code.py').unlink()
        self.assertBridge('UNSAFE_FILE', self.store.followup, parent, 'Question', [])
        (self.repo / 'code.py').write_text('code restored\n')
        (self.repo / 'extra.md').write_text('OPENAI_API_KEY=' + 'a8b7c6d5' * 8)
        self.assertBridge('SECRET_DETECTED', self.store.followup, parent, 'Question', ['extra.md'])

    def test_policy_cannot_move_followup_to_another_project(self):
        parent = self.complete()
        other = self.base / 'other'
        other.mkdir()
        self.policy.write_text(self.policy.read_text().replace(str(self.repo), str(other)))
        self.assertBridge('PROJECT_MISMATCH', self.store.followup, parent, 'Question', [])

    def test_cli_prepares_and_publishes_child_with_updated_context(self):
        parent = self.complete()
        (self.repo / 'extra.md').write_text('New evidence\n')
        cli = subprocess.run(self.command + ['followup', parent, '--goal', 'Check revision',
                            '--file', 'extra.md', '--draft-stdin', '--publish', '--approve'],
                             input='# Current rules\nKeep the interface.\n', text=True, env=self.env,
                             capture_output=True, timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        child = json.loads(cli.stdout)
        self.assertEqual(child['status'], 'waiting_for_chatgpt')
        self.assertEqual(child['parent_request_id'], parent)
        docs = self.bundle(child['request_id'])['payload']['documents']
        self.assertEqual(docs[0]['text'], '# Current rules\nKeep the interface.\n')
        listing = subprocess.run(self.command + ['list', '--conversation', parent],
                                 text=True, env=self.env, capture_output=True, timeout=10)
        self.assertEqual(len(json.loads(listing.stdout)['tasks']), 2)

    def test_cli_failed_publish_keeps_prepared_child_for_retry(self):
        parent = self.complete()
        cli = subprocess.run(self.command + ['followup', parent, '--goal', 'Question', '--publish'],
                             text=True, env=self.env, capture_output=True, timeout=10)
        self.assertEqual(cli.returncode, 2, cli.stderr)
        child = json.loads(cli.stdout)
        self.assertEqual(child['error'], 'APPROVAL_REQUIRED')
        self.assertEqual(self.store.status(child['request_id'])['status'], 'prepared')
        self.store.publish(child['request_id'], approve=True)
        self.assertEqual(self.store.status(child['request_id'])['status'], 'waiting_for_chatgpt')

    def test_reselection_can_replace_deleted_material_with_a_frozen_explanation(self):
        parent = self.complete()
        old = self.bundle(parent)
        (self.repo / 'code.py').unlink()
        (self.repo / 'replacement.py').write_text('new implementation\n')
        child = self.store.followup(parent, 'Review replacement', ['replacement.py'], replace_files=True,
                                   selection_note='code.py was deleted; replacement.py supersedes it. The old plan is historical.')
        docs = {d['title']: d['text'] for d in self.bundle(child['request_id'])['payload']['documents']}
        self.assertEqual(docs['replacement.py'], 'new implementation\n')
        self.assertNotIn('code.py', docs)
        selection = docs['Material selection changes']
        self.assertIn('code.py was deleted', selection)
        selection_data = json.loads(selection.rsplit('\n\n', 1)[1])
        self.assertEqual(selection_data['omitted_files'], ['PLAN.md', 'code.py'])
        self.assertEqual(selection_data['selected_files'], ['replacement.py'])
        self.assertEqual(self.bundle(parent), old)
        self.store.publish(child['request_id'], approve=True)
        self.assertTrue(self.store.check_source(child['request_id'])['unchanged'])

    def test_reselection_requires_reason_and_keeps_policy_and_secret_checks(self):
        parent = self.complete()
        before = set(self.store.private.iterdir())
        self.assertBridge('SELECTION_NOTE_REQUIRED', self.store.followup, parent, 'Question', [], replace_files=True)
        self.assertEqual(set(self.store.private.iterdir()), before)
        (self.repo / 'denied.txt').write_text('Not approved\n')
        self.assertBridge('OUT_OF_SCOPE', self.store.followup, parent, 'Question', ['denied.txt'],
                          replace_files=True, selection_note='Replace the previous evidence.')
        self.assertBridge('SECRET_DETECTED', self.store.followup, parent, 'Question', [], replace_files=True,
                          selection_note='OPENAI_API_KEY=' + 'a8b7c6d5' * 8)
        self.assertEqual(set(self.store.private.iterdir()), before)

    def test_cli_context_only_followup_keeps_explicit_omissions(self):
        parent = self.complete()
        cli = subprocess.run(self.command + ['followup', parent, '--goal', 'Clarify the recommendation',
                            '--replace-files', '--selection-note', 'This question only concerns the previous report.'],
                             env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        child = json.loads(cli.stdout)
        docs = self.bundle(child['request_id'])['payload']['documents']
        self.assertEqual(len(docs), 4)
        self.assertIn('Material selection changes', [d['title'] for d in docs])
        self.assertFalse(self.store.result(parent)['processed'])
