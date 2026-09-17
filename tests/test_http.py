import http.client
import json
import threading

from support import Fixture, REVIEW
from test_protocol import request
from plan_review_bridge.http_server import LocalHTTPServer
from plan_review_bridge.protocol import MCPApplication

class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.rid, self.sha = self.published()
        self.token = 't'*48
        self.server = LocalHTTPServer(0, MCPApplication(self.store.exchange), self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        super().tearDown()

    def send(self, payload=None, *, method='POST', headers=None, path='/mcp', raw=None):
        merged = {'Authorization': 'Bearer '+self.token, 'Content-Type':'application/json',
                  'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-11-25'}
        merged.update(headers or {})
        merged = {k:v for k,v in merged.items() if v is not None}
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = raw if raw is not None else json.dumps(payload or request('ping')).encode()
        try:
            conn.request(method, path, body=body, headers=merged)
            result = conn.getresponse()
            status, data = result.status, result.read()
            return status, json.loads(data) if data else None
        finally:
            conn.close()

    def test_http_roundtrip(self):
        status, result = self.send(request('initialize', {'protocolVersion':'2025-11-25'}))
        self.assertEqual(status, 200)
        self.assertIn('serverInfo', result['result'])
        status, result = self.send(request('tools/call', {'name':'fetch', 'arguments': {'id': self.rid+':request'}}))
        self.assertEqual(status, 200)
        self.assertEqual(result['result']['structuredContent']['metadata']['bundle_sha256'], self.sha)
        status, result = self.send(request('tools/call', {'name':'submit_review', 'arguments': {'request_id':self.rid, 'bundle_sha256':self.sha, 'markdown':REVIEW}}))
        self.assertEqual(status, 200)
        self.assertEqual(result['result']['structuredContent']['status'], 'completed')

    def test_auth_host_origin_and_protocol(self):
        for headers, expected in [({'Authorization':None},401), ({'Authorization':'Bearer wrong'},401),
                                  ({'Host':'evil.invalid'},403), ({'Origin':'https://evil.invalid'},403),
                                  ({'MCP-Protocol-Version':'fake'},400)]:
            with self.subTest(headers=headers):
                self.assertEqual(self.send(headers=headers)[0], expected)
        self.assertEqual(self.send(headers={'Origin':f'http://localhost:{self.server.server_port}'})[0],200)

    def test_bad_content_accept_length_and_json(self):
        self.assertEqual(self.send(headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.send(headers={'Accept':'application/json'})[0],406)
        self.assertEqual(self.send(headers={'Content-Length':'1048577'})[0],413)
        self.assertEqual(self.send(raw=b'{"a":1,"a":2}')[0],400)
        self.assertEqual(self.send(path='/other')[0],404)

    def test_no_get_or_delete_side_effects(self):
        self.assertEqual(self.send(method='GET')[0],405)
        self.assertEqual(self.send(method='DELETE')[0],405)
        self.assertEqual(self.store.status(self.rid)['status'], 'waiting_for_chatgpt')

    def test_notification_accepted_without_reply_or_write(self):
        req = request('tools/call', {'name':'submit_review', 'arguments':{'request_id':self.rid, 'bundle_sha256':self.sha, 'markdown':REVIEW}})
        del req['id']
        self.assertEqual(self.send(req), (202, None))
        self.assertEqual(self.store.status(self.rid)['status'], 'waiting_for_chatgpt')

    def test_unicode_auth_is_rejected_safely(self):
        self.assertEqual(self.send(headers={'Authorization':'Bearer \u00e9'})[0],401)
