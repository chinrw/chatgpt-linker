import concurrent.futures
import json
import os
import time
from unittest.mock import patch

from support import Fixture, REVIEW
from plan_review_bridge.errors import BridgeError
from plan_review_bridge.fs import atomic_write, canonical, read_json
from plan_review_bridge.store import Exchange, LocalStore

class StoreTests(Fixture):
    def test_requires_publication_approval(self):
        task = self.prepare()
        rid = task['request_id']
        self.assertEqual(self.store.status(rid)['status'], 'prepared')
        self.assertBridge('APPROVAL_REQUIRED', self.store.publish, rid)
        self.assertBridge('STATE_MISSING', self.store.exchange.fetch, rid + ':request')

    def test_approved_auto_publish(self):
        self.write_policy(auto=True)
        task = self.prepare()
        self.assertEqual(self.store.publish(task['request_id'])['status'], 'waiting_for_chatgpt')

    def test_policy_change_invalidates_prepared_task(self):
        task = self.prepare()
        self.write_policy(auto=True)
        self.assertBridge('POLICY_CHANGED', self.store.publish, task['request_id'], approve=True)

    def test_capture_detects_concurrent_changes(self):
        from plan_review_bridge.store import read_source as actual
        calls = 0
        def modified(root, name, limit):
            nonlocal calls
            if name == 'code.py':
                calls += 1
                if calls == 2:
                    (self.repo / 'code.py').write_text('changed\n')
            return actual(root, name, limit)
        with patch('plan_review_bridge.store.read_source', side_effect=modified):
            self.assertBridge('SOURCE_CHANGED', self.prepare)

    def test_source_changed_before_publish(self):
        task = self.prepare()
        (self.repo / 'code.py').write_text('changed\n')
        self.assertBridge('SOURCE_CHANGED', self.store.publish, task['request_id'], approve=True)

    def test_frozen_bytes_after_publish_and_drift(self):
        rid, sha = self.published()
        (self.repo / 'code.py').write_text('new code\n')
        self.assertIn('greet', self.store.exchange.fetch(rid + ':d0002')['text'])
        self.store.exchange.submit(rid, sha, REVIEW)
        self.assertFalse(self.store.result(rid)['source_check']['unchanged'])

    def test_inline_draft_does_not_write_source(self):
        before = {p.name: p.read_bytes() for p in self.repo.iterdir()}
        task = self.store.prepare(self.policy, None, ['code.py'], 'Review', draft='# Draft\nKeep APIs.\nAdd tests.\n')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.repo.iterdir()})
        self.store.publish(task['request_id'], approve=True)
        text = self.store.exchange.fetch(task['request_id'] + ':d0001')['text']
        self.assertIn('Keep APIs', text)

    def test_search_fetch_and_pagination(self):
        rid, sha = self.published()
        found = self.store.exchange.search(rid + ' greet')['results']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['id'], rid + ':d0002')
        first = self.store.exchange.fetch(rid + ':d0001', max_lines=1)
        self.assertEqual(first['metadata']['next_start_line'], 2)
        second = self.store.exchange.fetch(rid + ':d0001', start_line=2)
        self.assertIsNone(second['metadata']['next_start_line'])
        self.assertEqual(second['metadata']['bundle_sha256'], sha)
        self.assertTrue(second['url'].startswith('planreview://'))

    def test_search_multiple_pages(self):
        files = []
        for n in range(25):
            f = f'f{n}.py'
            (self.repo / f).write_text('evidence\n')
            files.append(f)
        task = self.store.prepare(self.policy, 'PLAN.md', files, 'Review')
        self.store.publish(task['request_id'], approve=True)
        first = self.store.exchange.search(task['request_id'])
        self.assertEqual(len(first['results']), 20)
        last = self.store.exchange.search(task['request_id'], cursor=first['next_cursor'])
        self.assertEqual(len(last['results']), 7)
        self.assertIsNone(last['next_cursor'])

    def test_no_arbitrary_paths(self):
        rid, _ = self.published()
        for bad in ('/etc/passwd', rid + ':../private', 'https://example.com/file'):
            self.assertBridge('INVALID_ID', self.store.exchange.fetch, bad)
        self.assertBridge('UNAVAILABLE', self.store.exchange.fetch, rid + ':d9999')
        self.assertBridge('INVALID_RANGE', self.store.exchange.fetch, rid + ':d0001', start_line=999)

    def test_task_scope_prevents_cross_task(self):
        rid, _ = self.published()
        other, _ = self.published()
        scoped = Exchange(self.store.exchange.root, request_scope=rid)
        self.assertBridge('UNAVAILABLE', scoped.fetch, other + ':request')
        self.assertIn(rid, scoped.fetch(rid + ':request')['text'])

    def test_hash_tampering_detected(self):
        rid, _ = self.published()
        path = self.store.exchange.inbox / rid / 'bundle.json'
        obj = read_json(path)
        obj['payload']['goal'] = 'tampered'
        atomic_write(path, canonical(obj))
        self.assertBridge('INTEGRITY_ERROR', self.store.exchange.fetch, rid + ':request')

    def test_wrong_hash_rejected(self):
        rid, _ = self.published()
        self.assertBridge('BUNDLE_MISMATCH', self.store.exchange.submit, rid, '0'*64, REVIEW)
        self.assertEqual(self.store.status(rid)['status'], 'waiting_for_chatgpt')

    def test_submit_receipt_fixed_path_and_retry(self):
        rid, sha = self.published()
        first = self.store.exchange.submit(rid, sha, REVIEW)
        self.assertEqual(first, self.store.exchange.submit(rid, sha, REVIEW))
        result = self.store.result(rid)
        expected = self.store.exchange.outbox / rid / 'result' / 'review.md'
        self.assertEqual(result['artifact_path'], str(expected))
        self.assertEqual(expected.read_text(), REVIEW)
        self.assertEqual(first['model_attestation'], 'unverified')
        self.assertEqual(os.stat(expected).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(expected.parent).st_mode & 0o777, 0o700)

    def test_conflicting_result_rejected(self):
        rid, sha = self.published()
        self.store.exchange.submit(rid, sha, REVIEW)
        self.assertBridge('RESULT_CONFLICT', self.store.exchange.submit, rid, sha, REVIEW + '\nDifferent.')

    def test_concurrent_identical_submissions(self):
        rid, sha = self.published()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: self.store.exchange.submit(rid, sha, REVIEW), range(16)))
        self.assertTrue(all(r == receipts[0] for r in receipts))
        self.assertEqual(len(list((self.store.exchange.outbox / rid).glob('.pending-*'))), 0)

    def test_concurrent_conflicting_submissions(self):
        rid, sha = self.published()
        def submit(n):
            try:
                self.store.exchange.submit(rid, sha, REVIEW + '\n' + str(n))
                return 'ok'
            except BridgeError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(8)))
        self.assertEqual(results.count('ok'), 1)
        self.assertEqual(results.count('RESULT_CONFLICT'), 7)

    def test_failed_atomic_result_does_not_complete(self):
        rid, sha = self.published()
        with patch('plan_review_bridge.store.os.rename', side_effect=OSError('synthetic crash')):
            with self.assertRaises(OSError):
                self.store.exchange.submit(rid, sha, REVIEW)
        self.assertEqual(self.store.status(rid)['status'], 'waiting_for_chatgpt')
        self.assertFalse((self.store.exchange.outbox / rid / 'result').exists())
        self.store.exchange.submit(rid, sha, REVIEW)
        self.assertEqual(self.store.status(rid)['status'], 'completed')

    def test_output_symlink_rejected(self):
        rid, sha = self.published()
        (self.store.exchange.outbox / rid / 'result').symlink_to(self.repo, target_is_directory=True)
        self.assertBridge('UNSAFE_STATE', self.store.exchange.submit, rid, sha, REVIEW)
        self.assertFalse((self.repo / 'review.md').exists())

    def test_result_integrity(self):
        rid, sha = self.published()
        self.store.exchange.submit(rid, sha, REVIEW)
        atomic_write(self.store.exchange.outbox / rid / 'result' / 'review.md', b'changed')
        self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)

    def test_missing_sections_citations_and_out_of_bounds(self):
        rid, sha = self.published()
        for text, code in [(REVIEW.replace('## Risks', '## Other'), 'MISSING_SECTIONS'),
                           (REVIEW.replace('[d0001:L1-L3]', ''), 'MISSING_EVIDENCE'),
                           (REVIEW.replace('[d0001:L1-L3]', '[d0001:L1-L99]'), 'INVALID_EVIDENCE'),
                           (REVIEW.replace('[d0001:L1-L3]', '[d9999:L1]'), 'INVALID_EVIDENCE')]:
            self.assertBridge(code, self.store.exchange.submit, rid, sha, text)

    def test_output_scanned_and_bounded(self):
        rid, sha = self.published()
        self.assertBridge('SECRET_DETECTED', self.store.exchange.submit, rid, sha, REVIEW + '\npassword=actual-sensitive-value')
        self.assertBridge('RESULT_SIZE', self.store.exchange.submit, rid, sha, 'short')
        self.assertBridge('RESULT_SIZE', self.store.exchange.submit, rid, sha, REVIEW + 'x'*256000)

    def test_readonly_grant_manual_fallback(self):
        rid, sha = self.published(allow_submit=False)
        self.assertBridge('READ_ONLY', self.store.exchange.submit, rid, sha, REVIEW)
        receipt = self.store.exchange.submit(rid, sha, REVIEW, source='manual_import')
        self.assertEqual(receipt['source'], 'manual_import')

    def test_cancel_revokes_reads_and_writes(self):
        rid, sha = self.published()
        self.assertEqual(self.store.cancel(rid)['status'], 'cancelled')
        self.assertBridge('UNAVAILABLE', self.store.exchange.fetch, rid + ':request')
        self.assertBridge('UNAVAILABLE', self.store.exchange.submit, rid, sha, REVIEW)
        self.assertBridge('NOT_COMPLETED', self.store.result, rid)

    def test_expiry_revokes_remote_access(self):
        rid, sha = self.published()
        with patch('plan_review_bridge.store.time.time', return_value=time.time()+200000):
            self.assertEqual(self.store.status(rid)['status'], 'expired')
            self.assertBridge('UNAVAILABLE', self.store.exchange.fetch, rid + ':request')
            self.assertBridge('UNAVAILABLE', self.store.exchange.submit, rid, sha, REVIEW)

    def test_completed_local_result_survives_expiry(self):
        rid, sha = self.published()
        self.store.exchange.submit(rid, sha, REVIEW)
        with patch('plan_review_bridge.store.time.time', return_value=time.time()+200000):
            self.assertEqual(self.store.result(rid)['status'], 'completed')
            self.assertBridge('UNAVAILABLE', self.store.exchange.fetch, rid + ':request')

    def test_state_must_be_outside_project(self):
        local = LocalStore(self.repo / 'state', create=True)
        self.assertBridge('STATE_IN_PROJECT', local.prepare, self.policy, 'PLAN.md', [], 'Review')

    def test_world_readable_state_rejected(self):
        self.store.root.chmod(0o755)
        self.assertBridge('UNSAFE_STATE', LocalStore, self.store.root)
