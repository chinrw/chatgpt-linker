import concurrent.futures
import copy
import http.client
import json
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from support import Fixture, REVIEW
from chatgpt_linker.errors import BridgeError
from chatgpt_linker.exchange_http import ExchangeHTTPServer, RemoteExchange
from chatgpt_linker.fs import MAX_JSON, atomic_write, canonical, digest, read_json, write_new
from chatgpt_linker.store import LocalStore


class ExchangeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.node = LocalStore(self.base / 'node', create=True)
        self.token_file = self.base / 'exchange-token'
        self.token = secrets.token_urlsafe(48)
        write_new(self.token_file, (self.token + '\n').encode())
        self.server = ExchangeHTTPServer(('127.0.0.1', 0), self.node.exchange, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.remote = RemoteExchange(f'http://127.0.0.1:{self.server.server_port}', str(self.token_file))
        self.store.remote = self.remote

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def run_cli(self, *args, data=None):
        return subprocess.run(self.command + list(args), input=data, text=True, capture_output=True,
                              env=self.env, timeout=10)

    def request(self, *, method='POST', path='/v1/tasks', body=b'{}', headers=None):
        hdr = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        hdr.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=hdr)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_cli_publish_mcp_submit_and_resume_without_remote_configuration(self):
        before = {p.name: p.read_bytes() for p in self.repo.iterdir()}
        task = self.prepare()
        rid, sha = task['request_id'], task['bundle_sha256']
        published = self.run_cli('--exchange-url', self.remote.url, '--exchange-token-file', str(self.token_file),
                                 'publish', rid, '--approve')
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse((self.store.exchange.inbox / rid).exists())
        self.assertFalse((self.node.private / rid).exists())
        self.assertIn(rid, self.run_cli('prompt', rid).stdout)
        waiting = self.run_cli('wait', rid, '--timeout', '0')
        self.assertEqual(waiting.returncode, 3, waiting.stderr)
        requests = [
            {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
             'params': {'name': 'fetch', 'arguments': {'id': rid + ':request'}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'submit_review',
             'arguments': {'request_id': rid, 'bundle_sha256': sha, 'markdown': REVIEW}}},
        ]
        mcp = self.run_cli('serve', '--exchange', str(self.node.exchange.root),
                           data='\n'.join(json.dumps(r) for r in requests) + '\n')
        self.assertEqual(mcp.returncode, 0, mcp.stderr)
        responses = [json.loads(line) for line in mcp.stdout.splitlines()][1:]
        self.assertEqual([t['name'] for t in responses[0]['result']['tools']], ['search', 'fetch', 'submit_review'])
        self.assertEqual(responses[2]['result']['structuredContent']['status'], 'completed')
        received = self.run_cli('wait', rid, '--timeout', '0')
        self.assertEqual(received.returncode, 0, received.stderr)
        result = json.loads(received.stdout)
        artifact = Path(result['artifact_path'])
        self.assertEqual(artifact.read_text(), REVIEW)
        self.assertTrue(artifact.is_relative_to(self.store.private))
        self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result['receipt'], self.node.exchange.status(rid)['receipt'])
        self.assertTrue(result['source_check']['unchanged'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.repo.iterdir()})
        self.assertEqual(self.run_cli('result', rid).returncode, 0)
        (self.repo / 'code.py').write_text('changed\n')
        self.assertFalse(json.loads(self.run_cli('result', rid).stdout)['source_check']['unchanged'])

    def test_control_mcp_declares_and_performs_remote_result_download(self):
        from chatgpt_linker.protocol import MCPApplication
        rid, sha = self.published()
        self.node.exchange.submit(rid, sha, REVIEW)
        control = MCPApplication(local=LocalStore(self.store.root))
        hints = {tool['name']: tool['annotations']['readOnlyHint'] for tool in control.definitions}
        self.assertEqual(hints, {'review_status': True, 'review_result': False, 'review_wait': False})
        response = control.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'review_wait', 'arguments': {'request_id': rid, 'timeout_seconds': 0}}})
        result = response['result']['structuredContent']
        self.assertEqual(Path(result['artifact_path']).read_text(), REVIEW)
        self.assertEqual(result['receipt']['source'], 'mcp_submit')

    def test_approval_source_and_policy_checks_precede_network_publication(self):
        task = self.prepare()
        rid = task['request_id']
        self.assertBridge('APPROVAL_REQUIRED', self.store.publish, rid)
        self.assertFalse((self.store.private / rid / 'remote.json').exists())
        self.assertEqual(list(self.node.exchange.inbox.iterdir()), [])
        (self.repo / 'code.py').write_text('changed\n')
        self.assertBridge('SOURCE_CHANGED', self.store.publish, rid, approve=True)
        self.write_policy(auto=True)
        self.assertBridge('POLICY_CHANGED', self.store.publish, rid, approve=True)
        self.assertEqual(list(self.node.exchange.inbox.iterdir()), [])

    def test_remote_auto_publish_uses_existing_policy(self):
        self.write_policy(auto=True)
        result = self.run_cli('--exchange-url', self.remote.url, '--exchange-token-file', str(self.token_file),
                              'prepare', '--policy', str(self.policy), '--plan', 'PLAN.md', '--goal', 'Review', '--publish')
        self.assertEqual(result.returncode, 0, result.stderr)
        task = json.loads(result.stdout)
        self.assertEqual(self.node.exchange.status(task['request_id'])['status'], 'waiting_for_chatgpt')

    def test_uploaded_bundle_contains_no_source_paths_or_credentials(self):
        rid, _ = self.published()
        bundle = (self.node.exchange.inbox / rid / 'bundle.json').read_text()
        for private in (str(self.repo), str(self.policy), str(self.token_file), self.token):
            self.assertNotIn(private, bundle)
        binding = read_json(self.store.private / rid / 'remote.json')
        self.assertNotIn(self.token, json.dumps(binding))

    def test_publication_retry_and_conflict_do_not_change_grant_or_expiry(self):
        rid, sha = self.published()
        wrapper = read_json(self.store.private / rid / 'candidate.json')
        original = self.remote.status(rid)
        self.assertEqual(self.remote.publish(wrapper, 168), original)
        self.assertBridge('GRANT_MISMATCH', self.remote.publish, wrapper, 24, allow_submit=False)
        changed = copy.deepcopy(wrapper)
        changed['payload']['goal'] = 'Different goal'
        changed['bundle_sha256'] = digest(canonical(changed['payload']))
        self.assertBridge('BUNDLE_MISMATCH', self.remote.publish, changed, 24)
        self.assertEqual(self.remote.status(rid)['bundle_sha256'], sha)
        self.remote.cancel(rid)
        self.assertEqual(self.remote.publish(wrapper, 24)['status'], 'cancelled')

    def test_lost_publication_reply_keeps_target_and_retry_is_idempotent(self):
        task = self.prepare()
        rid = task['request_id']
        original = self.node.exchange.publish
        def published_then_lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('synthetic lost reply')
        with patch.object(self.node.exchange, 'publish', side_effect=published_then_lost):
            self.assertBridge('EXCHANGE_HTTP', self.store.publish, rid, approve=True)
        resumed = LocalStore(self.store.root)
        self.assertEqual(resumed.status(rid)['status'], 'waiting_for_chatgpt')
        self.assertEqual(resumed.publish(rid, approve=True)['status'], 'waiting_for_chatgpt')
        self.store.remote = RemoteExchange('http://127.0.0.1:1', str(self.token_file))
        self.assertBridge('TARGET_MISMATCH', self.store.publish, rid, approve=True)
        self.assertBridge('TARGET_MISMATCH', self.store.status, rid)
        self.assertFalse((self.store.exchange.inbox / rid).exists())

    def test_local_task_cannot_silently_move_to_remote(self):
        self.store.remote = None
        rid, _ = self.published()
        self.store.remote = self.remote
        self.assertBridge('TARGET_MISMATCH', self.store.publish, rid, approve=True)
        self.assertEqual(list(self.node.exchange.inbox.iterdir()), [])

    def test_cancel_and_expiry_keep_existing_result_semantics(self):
        rid, sha = self.published()
        self.node.exchange.submit(rid, sha, REVIEW)
        with patch('chatgpt_linker.store.time.time', return_value=time.time() + 200000):
            self.assertEqual(self.store.result(rid)['status'], 'completed')
            self.assertBridge('UNAVAILABLE', self.node.exchange.fetch, rid + ':request')
        self.assertEqual(self.store.cancel(rid)['status'], 'cancelled')
        self.assertBridge('NOT_COMPLETED', self.store.result, rid)
        self.assertBridge('UNAVAILABLE', self.node.exchange.submit, rid, sha, REVIEW)
        other, _ = self.published()
        with patch('chatgpt_linker.store.time.time', return_value=time.time() + 200000):
            self.assertEqual(self.store.status(other)['status'], 'expired')

    def test_manual_import_retains_provenance_and_readonly_grant(self):
        rid, sha = self.published(allow_submit=False)
        self.assertBridge('READ_ONLY', self.node.exchange.submit, rid, sha, REVIEW)
        path = self.base / 'review.md'
        path.write_text(REVIEW)
        result = self.run_cli('import', rid, '--file', str(path), '--bundle-sha256', sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.store.result(rid)['receipt']['source'], 'manual_import')

    def test_authentication_host_origin_and_unknown_routes(self):
        rid, _ = self.published()
        for headers, status in (({'Authorization': 'Bearer wrong'}, 401),
                                ({'Host': 'evil.invalid'}, 403),
                                ({'Origin': 'https://evil.invalid'}, 403)):
            with self.subTest(headers=headers):
                actual, _ = self.request(method='GET', path=f'/v1/tasks/{rid}/result', headers=headers)
                self.assertEqual(actual, status)
        self.assertEqual(self.request(path='/mcp')[0], 404)
        self.assertEqual(self.request(path='/v1/tasks/../../private')[0], 404)
        self.assertEqual(self.request(method='DELETE', path=f'/v1/tasks/{rid}')[0], 405)
        self.assertEqual(self.store.status(rid)['status'], 'waiting_for_chatgpt')

    def test_malformed_uploads_create_no_tasks(self):
        task = self.prepare()
        wrapper = read_json(self.store.private / task['request_id'] / 'candidate.json')
        variants = [None, {}, {'payload': {}}, copy.deepcopy(wrapper), copy.deepcopy(wrapper)]
        variants[3]['payload']['documents'][0]['text'] = 'tampered'
        variants[4]['payload']['extra_path'] = '/etc/passwd'
        variants[4]['bundle_sha256'] = digest(canonical(variants[4]['payload']))
        for bundle in variants:
            with self.subTest(bundle=bundle):
                status, _ = self.request(body=canonical({'bundle': bundle, 'ttl_hours': 24, 'allow_submit': True}))
                self.assertEqual(status, 409)
        for raw in (b'{"bundle":1,"bundle":2}', b'{"bundle":NaN}', b'[]', b'not-json'):
            self.assertEqual(self.request(body=raw)[0], 400)
        self.assertEqual(self.request(headers={'Content-Length': str(MAX_JSON + 1)})[0], 409)
        self.assertEqual(list(self.node.exchange.inbox.iterdir()), [])
        self.assertEqual(list(self.node.exchange.outbox.iterdir()), [])

    def test_upload_checks_secrets_and_supports_bundles_above_mcp_message_limit(self):
        files = []
        for n in range(8):
            name = f'file{n}.py'
            (self.repo / name).write_text('evidence\n' * 18000)
            files.append(name)
        task = self.store.prepare(self.policy, 'PLAN.md', files, 'Review')
        self.store.publish(task['request_id'], approve=True)
        self.assertEqual(len(self.node.exchange.search(task['request_id'])['results']), 10)
        bad = read_json(self.store.private / task['request_id'] / 'candidate.json')
        bad['payload']['request_id'] = 'pr_' + 'a' * 24
        bad['payload']['goal'] = 'password=credential-value-849'
        bad['bundle_sha256'] = digest(canonical(bad['payload']))
        self.assertBridge('SECRET_DETECTED', self.remote.publish, bad, 24)
        self.assertFalse((self.node.exchange.inbox / bad['payload']['request_id']).exists())
        bad['payload']['goal'] = 'Review'
        document = bad['payload']['documents'][0]
        document['text'] = 'password = "credential-value-849"\n'
        document['sha256'] = digest(document['text'].encode())
        bad['bundle_sha256'] = digest(canonical(bad['payload']))
        self.assertBridge('SECRET_DETECTED', self.remote.publish, bad, 24)

    def test_sanitized_expansion_preserves_the_existing_source_file_limit(self):
        self.write_policy(extra='[[redactions]]\nliteral = "expandme"\nreplacement = "a longer approved replacement"\n')
        (self.repo / 'code.py').write_text('expandme\n' * 10000)
        task = self.prepare()
        wrapper = read_json(self.store.private / task['request_id'] / 'candidate.json')
        self.assertGreater(len(wrapper['payload']['documents'][1]['text']), 200000)
        self.assertEqual(self.store.publish(task['request_id'], approve=True)['status'], 'waiting_for_chatgpt')

    def test_result_integrity_conflict_and_atomic_download(self):
        rid, sha = self.published()
        self.node.exchange.submit(rid, sha, REVIEW)
        reply = self.node.exchange.result(rid)
        reply['markdown'] += '\ntampered'
        with patch.object(self.node.exchange, 'result', return_value=reply):
            self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)
        self.assertFalse((self.store.private / rid / 'result').exists())
        with patch('chatgpt_linker.store.os.rename', side_effect=OSError('synthetic crash')):
            with self.assertRaises(OSError):
                self.store.result(rid)
        self.assertFalse((self.store.private / rid / 'result').exists())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.result(rid), range(4)))
        self.assertTrue(all(r['receipt'] == results[0]['receipt'] for r in results))
        atomic_write(Path(results[0]['artifact_path']), b'tampered cache')
        self.assertBridge('INTEGRITY_ERROR', self.store.result, rid)

    def test_remote_errors_and_redirects_never_fall_back_or_expose_token(self):
        rid, _ = self.published()
        with patch('chatgpt_linker.exchange_http.ExchangeHandler.do_GET',
                   lambda handler: handler.reply(302, {'token': self.token})):
            result = self.run_cli('status', rid)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(self.token, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stderr)['error'], 'EXCHANGE_HTTP')
        with patch.object(self.node.exchange, 'status', side_effect=OSError('synthetic storage failure')):
            self.assertBridge('EXCHANGE_HTTP', self.store.status, rid)
        self.assertFalse((self.store.exchange.inbox / rid).exists())

    def test_nonlocal_plaintext_is_rejected(self):
        for url in ('http://192.168.0.2:8767', 'https://user:pass@example.com',
                    'https://example.com/path', 'https://example.com/?token=x', 'https://example.com:0'):
            self.assertBridge('HTTP_CONFIG', RemoteExchange, url, str(self.token_file))
        self.assertBridge('HTTP_CONFIG', ExchangeHTTPServer, ('0.0.0.0', 0), self.node.exchange, self.token)


class ExchangeTLSTests(Fixture):
    def test_https_cli_listener_certificate_verification_and_result_roundtrip(self):
        openssl = shutil.which('openssl')
        if not openssl:
            self.skipTest('OpenSSL is required to generate a temporary test certificate')
        cert, key = self.base / 'cert.pem', self.base / 'key.pem'
        subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=exchange-test.invalid', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        token = self.base / 'token'
        write_new(token, (secrets.token_urlsafe(48) + '\n').encode())
        node = LocalStore(self.base / 'node', create=True)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'chatgpt_linker', 'serve-exchange',
                                    '--exchange', str(node.exchange.root), '--port', str(port),
                                    '--token-file', str(token), '--tls-cert', str(cert), '--tls-key', str(key)],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while True:
                if process.poll() is not None:
                    self.fail(process.communicate()[1].decode())
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        self.fail('HTTPS listener did not start')
                    time.sleep(0.02)
            url = f'https://127.0.0.1:{port}'
            self.store.remote = RemoteExchange(url, str(token), str(cert))
            rid, sha = self.published()
            node.exchange.submit(rid, sha, REVIEW)
            self.assertEqual(Path(self.store.result(rid)['artifact_path']).read_text(), REVIEW)
            untrusted = RemoteExchange(url, str(token))
            self.assertBridge('EXCHANGE_TLS', untrusted.status, rid)
            wrong_name = RemoteExchange(f'https://localhost:{port}', str(token), str(cert))
            self.assertBridge('EXCHANGE_TLS', wrong_name.status, rid)
        finally:
            process.terminate()
            process.communicate(timeout=5)


class ExchangeOriginTests(Fixture):
    def make_server(self, port, *, tls=True, allowed_hosts=None):
        import ssl
        from chatgpt_linker.http_server import BoundedHTTPServer
        def bind_without_socket(server, address, handler, token):
            server.server_port, server.token = port, token
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER) if tls else None
        with patch.object(BoundedHTTPServer, '__init__', bind_without_socket):
            return ExchangeHTTPServer(('127.0.0.1', port), self.store.exchange, 'x' * 48,
                                      allowed_hosts=allowed_hosts, tls_context=context)

    def authorized(self, server, host):
        from email.message import Message
        from unittest.mock import Mock
        from chatgpt_linker.exchange_http import ExchangeHandler
        handler = ExchangeHandler.__new__(ExchangeHandler)
        handler.server = server
        handler.headers = Message()
        handler.headers['Host'] = host
        handler.headers['Authorization'] = 'Bearer ' + server.token
        handler.reply = Mock()
        return handler.authorized()

    def test_standard_client_host_matches_default_and_nondefault_ports(self):
        from email.parser import BytesParser
        from unittest.mock import Mock
        for tls, port in ((True, 443), (True, 8443), (False, 80), (False, 8767)):
            with self.subTest(tls=tls, port=port):
                server = self.make_server(port, tls=tls)
                connection_type = http.client.HTTPSConnection if tls else http.client.HTTPConnection
                connection = connection_type('127.0.0.1', port)
                connection.sock = Mock()
                connection.request('GET', '/v1/tasks/pr_' + 'a' * 24)
                raw = b''.join(call.args[0] for call in connection.sock.sendall.call_args_list)
                headers = BytesParser().parsebytes(raw.split(b'\r\n', 1)[1])
                self.assertTrue(self.authorized(server, headers['Host']), headers['Host'])

    def test_host_allowlist_normalizes_case_without_accepting_other_authorities(self):
        server = self.make_server(443, allowed_hosts=['LINKER.Example:443'])
        for host in ('linker.example', 'LINKER.EXAMPLE', 'linker.example:443'):
            with self.subTest(host=host):
                self.assertTrue(self.authorized(server, host))
        for host in ('other.example', 'linker.example:8443', 'user@linker.example',
                     'linker.example/path', 'linker.example?query', 'linker.example#fragment',
                     'linker.example/', 'linker.example?', 'linker.example#',
                     ' linker.example', 'linker.example\t', 'linker.example:0'):
            with self.subTest(host=host):
                self.assertFalse(self.authorized(server, host))

    def test_old_saved_origin_resumes_status_and_result_with_equivalent_spelling(self):
        task = self.prepare()
        rid = task['request_id']
        node = LocalStore(self.base / 'node', create=True)
        node.exchange.publish(read_json(self.store.private / rid / 'candidate.json'), 24)
        node.exchange.submit(rid, task['bundle_sha256'], REVIEW)
        binding = {'url': 'https://LINKER.Example:443/', 'token_file': str(self.base / 'token'), 'ca_file': None}
        atomic_write(self.store.private / rid / 'remote.json', canonical(binding))
        def response(method, path, payload=None):
            return node.exchange.result(rid) if path.endswith('/result') else node.exchange.status(rid)
        for url in ('https://linker.example', 'https://LINKER.EXAMPLE:443', 'https://Linker.Example/'):
            with self.subTest(url=url), patch.object(RemoteExchange, 'request', side_effect=response):
                resumed = LocalStore(self.store.root, remote=RemoteExchange(url, str(self.base / 'token')))
                self.assertEqual(resumed.status(rid)['status'], 'completed')
                result = resumed.result(rid)
                self.assertEqual(Path(result['artifact_path']).read_text(), REVIEW)
                self.assertTrue(result['source_check']['unchanged'])
        self.assertEqual(read_json(self.store.private / rid / 'remote.json'), binding)

    def test_changed_host_scheme_or_nondefault_port_cannot_retarget_task(self):
        task = self.prepare()
        rid = task['request_id']
        cases = (('https://linker.example', 'https://other.example'),
                 ('https://linker.example', 'https://linker.example:8443'),
                 ('https://localhost', 'http://localhost'))
        for saved, configured in cases:
            with self.subTest(saved=saved, configured=configured):
                atomic_write(self.store.private / rid / 'remote.json', canonical({
                    'url': saved, 'token_file': str(self.base / 'token'), 'ca_file': None}))
                resumed = LocalStore(self.store.root, remote=RemoteExchange(configured, str(self.base / 'token')))
                with patch.object(RemoteExchange, 'request') as transport:
                    self.assertBridge('TARGET_MISMATCH', resumed.status, rid)
                    self.assertBridge('TARGET_MISMATCH', resumed.result, rid)
                    transport.assert_not_called()
