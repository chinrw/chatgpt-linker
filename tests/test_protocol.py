import io
import json
import subprocess

from support import Fixture, REVIEW
from plan_review_bridge.protocol import MCPApplication, RpcError, encode, loads, serve_stdio


def request(method, params=None, identifier=1):
    return {'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params or {}}


class ProtocolTests(Fixture):
    def setUp(self):
        super().setUp()
        self.rid, self.sha = self.published()
        self.app = MCPApplication(self.store.exchange)

    def call(self, name, args, app=None):
        return (app or self.app).handle(request('tools/call', {'name': name, 'arguments': args}))

    def test_initialize_and_version_negotiation(self):
        for version in ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05', '2099-01-01'):
            answer = self.app.handle(request('initialize', {'protocolVersion': version}))['result']
            self.assertEqual(answer['protocolVersion'], version if version != '2099-01-01' else '2025-11-25')
            self.assertIn('tools', answer['capabilities'])
            self.assertNotIn('sampling', answer['capabilities'])
        self.assertIn('error', self.app.handle(request('initialize')))

    def test_exact_tools_and_annotations(self):
        tools = self.app.handle(request('tools/list'))['result']['tools']
        self.assertEqual([x['name'] for x in tools], ['search', 'fetch', 'submit_review'])
        for t in tools:
            self.assertEqual(t['annotations']['readOnlyHint'], t['name'] != 'submit_review')
            self.assertFalse(t['annotations']['destructiveHint'])
            self.assertTrue(t['annotations']['idempotentHint'])
            self.assertFalse(t['inputSchema']['additionalProperties'])
        self.assertNotIn('path', tools[2]['inputSchema']['properties'])

    def test_structured_and_text_outputs_match(self):
        result = self.call('fetch', {'id': self.rid + ':request'})['result']
        self.assertFalse(result['isError'])
        self.assertEqual(json.loads(result['content'][0]['text']), result['structuredContent'])

    def test_readonly_surface_omits_write(self):
        app = MCPApplication(self.store.exchange, read_only=True)
        self.assertEqual([t['name'] for t in app.definitions], ['search', 'fetch'])
        self.assertIn('error', self.call('submit_review', {'request_id': self.rid, 'bundle_sha256': self.sha, 'markdown': REVIEW}, app))

    def test_no_extra_arguments(self):
        result = self.call('fetch', {'id': self.rid + ':request', 'path': '/etc/passwd'})
        self.assertEqual(result['error']['code'], -32602)
        self.assertNotIn('/etc/passwd', json.dumps(result))

    def test_schema_bounds_types_unicode(self):
        for args in ({'id': 1}, {'id': self.rid + ':request', 'max_lines': True},
                     {'id': self.rid + ':request', 'max_lines': 501}, {'id': '\ud800'}, {}):
            self.assertEqual(self.call('fetch', args)['error']['code'], -32602)
        self.assertEqual(self.call('submit_review', {'request_id': self.rid, 'bundle_sha256': 'bad', 'markdown': REVIEW})['error']['code'], -32602)

    def test_unknown_tools_cannot_dispatch(self):
        for name in ('exec_command', 'write_file', 'review_result', 'bash', 'review_start'):
            self.assertEqual(self.call(name, {})['error']['code'], -32602)

    def test_notification_never_submits(self):
        req = request('tools/call', {'name': 'submit_review', 'arguments': {'request_id': self.rid, 'bundle_sha256': self.sha, 'markdown': REVIEW}})
        del req['id']
        self.assertIsNone(self.app.handle(req))
        self.assertEqual(self.store.status(self.rid)['status'], 'waiting_for_chatgpt')

    def test_domain_errors_safe_and_tool_errors(self):
        result = self.call('fetch', {'id': self.rid + ':d9999'})['result']
        self.assertTrue(result['isError'])
        self.assertNotIn(str(self.base), json.dumps(result))

    def test_resources_are_real_and_authorized(self):
        uri = 'planreview://' + self.rid + '/d0001'
        answer = self.app.handle(request('resources/read', {'uri': uri}))['result']
        self.assertIn('Preserve compatibility', answer['contents'][0]['text'])
        self.assertEqual(answer['contents'][0]['uri'], uri)
        self.store.cancel(self.rid)
        self.assertIn('error', self.app.handle(request('resources/read', {'uri': uri})))
        self.assertEqual(self.app.handle(request('resources/list'))['result'], {'resources': []})

    def test_invalid_resource_and_unsupported_method(self):
        for uri in ('file:///etc/passwd', 'https://example.com', 'planreview://bad/../x'):
            self.assertIn('error', self.app.handle(request('resources/read', {'uri': uri})))
        self.assertEqual(self.app.handle(request('sampling/createMessage'))['error']['code'], -32601)

    def test_json_rejects_duplicates_batches_nan(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{oops', b'null'):
            with self.assertRaises(RpcError):
                loads(data)

    def test_stdio_requires_initialization(self):
        source = io.BytesIO(encode(request('tools/list')) + b'\n')
        target = io.BytesIO()
        serve_stdio(self.app, source, target)
        self.assertIn('error', json.loads(target.getvalue()))

    def test_stdio_real_subprocess_roundtrip_and_no_noise(self):
        messages = [request('initialize', {'protocolVersion': '2025-11-25'}, 1),
                    {'jsonrpc':'2.0', 'method':'notifications/initialized'},
                    request('tools/list', identifier=2),
                    request('tools/call', {'name':'fetch', 'arguments':{'id':self.rid+':request'}}, 3),
                    request('tools/call', {'name':'submit_review', 'arguments':{'request_id':self.rid, 'bundle_sha256':self.sha, 'markdown':REVIEW}}, 4)]
        process = subprocess.run(self.command + ['serve', '--exchange', str(self.store.exchange.root)],
                                 env=self.env, input=b'\n'.join(encode(m) for m in messages)+b'\n', capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, b'')
        replies = [json.loads(x) for x in process.stdout.splitlines()]
        self.assertEqual([x['id'] for x in replies], [1,2,3,4])
        self.assertEqual(replies[-1]['result']['structuredContent']['status'], 'completed')
        self.assertEqual(self.store.result(self.rid)['status'], 'completed')

    def test_oversize_stdio_is_bounded_and_closes(self):
        from plan_review_bridge.protocol import MAX_MESSAGE
        target = io.BytesIO()
        serve_stdio(self.app, io.BytesIO(b'x'*(MAX_MESSAGE+1)+b'\n'), target)
        self.assertLess(len(target.getvalue()), 300)
        self.assertEqual(json.loads(target.getvalue())['error']['code'], -32700)

    def test_control_surface_and_wait_resume(self):
        control = MCPApplication(local=self.store)
        self.assertEqual([x['name'] for x in control.definitions], ['review_status', 'review_result', 'review_wait'])
        args = {'request_id': self.rid, 'timeout_seconds': 0}
        state = self.call('review_wait', args, control)['result']['structuredContent']
        self.assertEqual(state['status'], 'waiting_for_chatgpt')
        self.store.exchange.submit(self.rid, self.sha, REVIEW)
        result = self.call('review_wait', args, control)['result']['structuredContent']
        self.assertIn('artifact_path', result)
        self.assertIn('error', self.call('submit_review', {}, control))

    def test_invalid_rpc_id_is_not_reflected(self):
        for identifier in (True, [], {}, None):
            answer = self.app.handle(request('ping', identifier=identifier))
            self.assertIsNone(answer['id'])
            self.assertEqual(answer['error']['code'], -32600)
