"""Local discovery and explicit report processing, using synthetic reviews only."""
import concurrent.futures
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from support import Fixture, REVIEW
from chatgpt_linker.fs import canonical, read_json
from chatgpt_linker.protocol import MCPApplication
from chatgpt_linker.store import LocalStore


class InboxTests(Fixture):
    def completed(self, markdown=REVIEW):
        rid, sha = self.published()
        self.store.exchange.submit(rid, sha, markdown)
        return rid, sha

    def test_list_filters_and_read_does_not_process(self):
        prepared = self.prepare()['request_id']
        waiting, _ = self.published()
        completed, _ = self.completed()
        cancelled, _ = self.published()
        self.store.cancel(cancelled)
        expired, _ = self.published()
        with patch('chatgpt_linker.store.time.time', return_value=10**12):
            states = {x['request_id']: x['status'] for x in self.store.list_tasks()['tasks']}
            self.assertEqual(states[expired], 'expired')
        tasks = self.store.list_tasks(project=str(self.repo))['tasks']
        self.assertEqual({x['request_id'] for x in tasks}, {prepared, waiting, completed, cancelled, expired})
        self.assertEqual(self.store.list_tasks(project=str(self.base / 'other'))['tasks'], [])
        self.assertEqual([x['request_id'] for x in self.store.list_tasks(status='prepared')['tasks']], [prepared])
        self.assertEqual([x['request_id'] for x in self.store.list_tasks(status='unprocessed')['tasks']], [completed])
        result = self.store.result(completed)
        self.assertEqual(result['markdown'], REVIEW)
        self.assertFalse(result['processed'])
        self.assertEqual(len(self.store.list_tasks(status='unprocessed')['tasks']), 1)

    def test_explicit_processing_is_hash_bound_persistent_and_idempotent(self):
        rid, sha = self.completed()
        bundle = (self.store.exchange.inbox / rid / 'bundle.json').read_bytes()
        result = self.store.result(rid)
        receipt = result['receipt']
        self.assertBridge('RESULT_MISMATCH', self.store.mark_processed, rid, '0' * 64)
        self.assertFalse((self.store.private / rid / 'processed.json').exists())
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            marks = list(pool.map(lambda _: self.store.mark_processed(rid, receipt['result_sha256']), range(3)))
        self.assertEqual(marks[0], marks[1])
        self.assertEqual(marks[0], marks[2])
        reloaded = LocalStore(self.store.root)
        self.assertEqual(reloaded.list_tasks(status='unprocessed')['tasks'], [])
        self.assertTrue(reloaded.result(rid)['processed'])
        self.assertEqual(reloaded.result(rid)['receipt'], receipt)
        self.assertEqual((self.store.exchange.inbox / rid / 'bundle.json').read_bytes(), bundle)
        self.assertEqual(reloaded.exchange.submit(rid, sha, REVIEW)['result_sha256'], receipt['result_sha256'])
        self.assertBridge('RESULT_CONFLICT', reloaded.exchange.submit, rid, sha, REVIEW + '\nChanged')
        marker = self.store.private / rid / 'processed.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_unicode_pagination_reconstructs_exact_report(self):
        report = REVIEW + '\n' + '中文🙂e\u0301\n' * 3000
        rid, _ = self.completed(report)
        offset, pieces = 0, []
        while True:
            page = self.store.result(rid, offset=offset, max_chars=17)
            pieces.append(page['markdown'])
            self.assertLessEqual(len(page['markdown']), 17)
            self.assertEqual(page['total_chars'], len(report))
            if page['next_offset'] is None:
                break
            self.assertGreater(page['next_offset'], offset)
            offset = page['next_offset']
        self.assertEqual(''.join(pieces), report)
        self.assertEqual(self.store.result(rid, offset=len(report))['markdown'], '')
        for opts in ({'offset': -1}, {'offset': len(report) + 1}, {'max_chars': 0}, {'max_chars': 12001}, {'offset': True}):
            self.assertBridge('INVALID_PAGE', self.store.result, rid, **opts)

    def test_list_pagination_keeps_filtered_pages_and_errors_visible(self):
        ids = [self.prepare()['request_id'] for _ in range(3)]
        wanted = max(ids)
        task = self.store.status(wanted)
        self.store.publish(wanted, approve=True)
        self.store.exchange.submit(wanted, task['bundle_sha256'], REVIEW)
        cursor, found = 0, []
        while True:
            page = self.store.list_tasks(status='unprocessed', cursor=cursor, limit=1)
            self.assertEqual(page['scanned'], 1)
            found.extend(x['request_id'] for x in page['tasks'])
            if page['next_cursor'] is None:
                break
            self.assertGreater(page['next_cursor'], cursor)
            cursor = page['next_cursor']
        self.assertEqual(found, [wanted])
        bad = min(ids)
        (self.store.private / bad / 'candidate.json').write_text('{}')
        page = self.store.list_tasks(status='unprocessed')
        self.assertEqual([x['request_id'] for x in page['tasks']], [wanted])
        self.assertEqual([x['request_id'] for x in page['errors']], [bad])
        self.assertNotIn(str(self.base), json.dumps(page['errors']))

    def test_tampering_and_cancellation_cannot_be_acknowledged(self):
        rid, _ = self.completed()
        result = self.store.result(rid)
        Path(result['artifact_path']).write_text(REVIEW + 'tampered')
        self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)
        self.assertBridge('INTEGRITY_ERROR', self.store.mark_processed, rid, result['receipt']['result_sha256'])
        self.assertFalse((self.store.private / rid / 'processed.json').exists())
        rid, _ = self.completed()
        result = self.store.result(rid)
        self.store.cancel(rid)
        self.assertBridge('NOT_COMPLETED', self.store.result, rid)
        self.assertBridge('NOT_COMPLETED', self.store.mark_processed, rid, result['receipt']['result_sha256'])
        self.assertNotIn(rid, [x['request_id'] for x in self.store.list_tasks(status='unprocessed')['tasks']])

    def test_source_drift_stays_visible_and_processing_is_not_approval(self):
        rid, _ = self.completed()
        (self.repo / 'code.py').write_text('changed\n')
        result = self.store.result(rid)
        self.assertFalse(result['source_check']['unchanged'])
        marked = self.store.mark_processed(rid, result['receipt']['result_sha256'])
        self.assertFalse(marked['source_check']['unchanged'])
        self.assertFalse(self.store.result(rid)['source_check']['unchanged'])

    def test_marker_and_task_symlinks_are_not_followed(self):
        rid, _ = self.completed()
        result = self.store.result(rid)
        outside = self.base / 'outside'
        outside.write_text('{}')
        (self.store.private / rid / 'processed.json').symlink_to(outside)
        self.assertBridge('STATE_MISSING', self.store.mark_processed, rid, result['receipt']['result_sha256'])
        self.assertEqual(outside.read_text(), '{}')
        linked = 'pr_' + 'f' * 24
        (self.store.private / linked).symlink_to(self.store.private / rid)
        page = self.store.list_tasks()
        self.assertEqual({e['request_id'] for e in page['errors']}, {rid, linked})

    def test_control_tools_and_cli_return_body_and_discover_unprocessed(self):
        rid, _ = self.completed()
        control = MCPApplication(local=self.store)
        def call(name, arguments):
            return control.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                   'params': {'name': name, 'arguments': arguments}})
        body = call('review_result', {'request_id': rid, 'max_chars': 12})['result']['structuredContent']
        self.assertEqual(body['markdown'], REVIEW[:12])
        page = call('review_list', {'status': 'unprocessed'})['result']['structuredContent']
        self.assertEqual(page['tasks'][0]['request_id'], rid)
        for args in ({'limit': True}, {'cursor': -1}, {'limit': 101}, {'unknown': 'x'}):
            self.assertEqual(call('review_list', args)['error']['code'], -32602)
        result = subprocess.run(self.command + ['result', rid], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['markdown'], REVIEW)
        sha = body['receipt']['result_sha256']
        marked = subprocess.run(self.command + ['mark-processed', rid, '--result-sha256', sha], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(marked.returncode, 0, marked.stderr)
        result = subprocess.run(self.command + ['list', '--status', 'unprocessed'], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout)['tasks'], [])
        response = call('review_mark_processed', {'request_id': rid, 'result_sha256': sha})
        self.assertFalse(response['result']['isError'])
        remote = MCPApplication(self.store.exchange)
        names = [x['name'] for x in remote.definitions]
        self.assertEqual(names, ['search', 'fetch', 'submit_review'])

    def test_invalid_filters(self):
        for args in ({'status': 'running'}, {'project': 'relative'}, {'limit': 0}, {'cursor': True}):
            with self.subTest(args=args):
                self.assertBridge('INVALID_FILTER' if 'status' in args or 'project' in args else 'INVALID_PAGE', self.store.list_tasks, **args)

    def test_wrong_processing_marker_is_not_treated_as_processed(self):
        rid, _ = self.completed()
        result = self.store.result(rid)
        self.store.mark_processed(rid, result['receipt']['result_sha256'])
        path = self.store.private / rid / 'processed.json'
        marker = read_json(path)
        marker['result_sha256'] = '0' * 64
        path.write_bytes(canonical(marker))
        self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)
        page = self.store.list_tasks(status='unprocessed')
        self.assertEqual(page['tasks'], [])
        self.assertEqual(page['errors'][0]['error'], 'INTEGRITY_ERROR')

    def test_body_is_checked_again_after_status_check(self):
        rid, _ = self.completed()
        saved_status = self.store.status(rid)
        result = self.store.result(rid)
        Path(result['artifact_path']).write_text(REVIEW + 'changed after status')
        with patch.object(self.store, 'status', return_value=saved_status):
            self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)

    def test_malformed_metadata_does_not_hide_other_tasks(self):
        bad = self.prepare()['request_id']
        (self.store.private / bad / 'provenance.json').write_text('{}')
        good, _ = self.completed()
        page = self.store.list_tasks(status='unprocessed')
        self.assertEqual([x['request_id'] for x in page['tasks']], [good])
        self.assertEqual(page['errors'][0]['request_id'], bad)
        self.assertEqual(page['errors'][0]['error'], 'CORRUPT_STATE')
