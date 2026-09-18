import json
import subprocess
from support import Fixture, REVIEW

class CLITests(Fixture):
    def run_cli(self, *args, data=None):
        return subprocess.run(self.command + list(args), input=data, text=True,
                              capture_output=True, env=self.env, timeout=10)

    def test_cli_prepare_publish_import_wait(self):
        prep = self.run_cli('prepare', '--policy', str(self.policy), '--plan', 'PLAN.md', '--file', 'code.py', '--goal', 'Review')
        self.assertEqual(prep.returncode, 0, prep.stderr)
        task = json.loads(prep.stdout)
        rid = task['request_id']
        self.assertEqual(self.run_cli('publish', rid, '--approve').returncode,0)
        self.assertIn(rid, self.run_cli('prompt', rid).stdout)
        wait = self.run_cli('wait', rid, '--timeout', '0')
        self.assertEqual(wait.returncode,3)
        self.assertTrue(json.loads(wait.stdout)['wait_timed_out'])
        result_file = self.base/'result.md'
        result_file.write_text(REVIEW)
        imp = self.run_cli('import', rid, '--file', str(result_file), '--bundle-sha256', task['bundle_sha256'])
        self.assertEqual(imp.returncode,0,imp.stderr)
        result = self.run_cli('wait', rid, '--timeout','0')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['receipt']['source'], 'manual_import')

    def test_draft_from_stdin_and_blocked_autopublish_recovers_id(self):
        result = self.run_cli('prepare', '--policy', str(self.policy), '--draft-stdin', '--file','code.py', '--goal','Review', '--publish', data='Draft\nPreserve APIs\nAdd tests\n')
        self.assertEqual(result.returncode,2)
        payload=json.loads(result.stdout)
        self.assertEqual(payload['error'], 'APPROVAL_REQUIRED')
        self.assertEqual(payload['status'], 'prepared')
        self.assertTrue(payload['request_id'].startswith('pr_'))

    def test_doctor_does_not_claim_live_verification(self):
        p = self.run_cli('doctor')
        result=json.loads(p.stdout)
        self.assertFalse(result['model_api_backend'])
        self.assertFalse(result['browser_automation'])
        self.assertFalse(result['chatgpt_live_connection_verified'])

    def test_policy_init_no_overwrite(self):
        args = ['policy-init','--repo',str(self.repo),'--output',str(self.base/'config'/'new.toml'),'--allow','*.md']
        first=self.run_cli(*args)
        self.assertEqual(first.returncode,0,first.stderr)
        second=self.run_cli(*args)
        self.assertEqual(second.returncode,2)
        self.assertEqual(json.loads(second.stderr)['error'],'POLICY_EXISTS')

    def test_local_http_token_not_printed(self):
        target=self.base/'http'/'token'
        p=self.run_cli('http-token','--output',str(target))
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn(target.read_text().strip(),p.stdout+p.stderr)
        self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_local_error_no_secret_leak(self):
        p=self.run_cli('prepare','--policy',str(self.policy),'--plan','PLAN.md','--goal','password=not-for-logging')
        self.assertEqual(p.returncode,2)
        self.assertNotIn('not-for-logging',p.stdout+p.stderr)
        self.assertNotIn(str(self.repo),p.stderr)

    def test_misplaced_state_rejected_before_any_source_write(self):
        target=self.repo/'must-not-exist'
        import sys
        p=subprocess.run([sys.executable,'-m','chatgpt_linker','--state',str(target),
                          'prepare','--policy',str(self.policy),'--plan','PLAN.md','--goal','Review'],
                         capture_output=True,text=True,env=self.env,timeout=10)
        self.assertEqual(p.returncode,2)
        self.assertEqual(json.loads(p.stderr)['error'],'STATE_IN_PROJECT')
        self.assertFalse(target.exists())
