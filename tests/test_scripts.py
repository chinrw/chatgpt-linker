import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support import Fixture, ROOT

class ScriptTests(Fixture):
    def test_skill_install_and_refuse_overwrite(self):
        destination = self.base/'skills'/'rethink-plan'
        command = [sys.executable, str(ROOT/'scripts/install_skill.py'), '--destination',str(destination)]
        result = subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((destination/'SKILL.md').is_file())
        self.assertIn('allow_implicit_invocation: false',(destination/'agents/openai.yaml').read_text())
        second = subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(second.returncode,0)

    def test_source_snapshot_excludes_state_and_caches(self):
        spec=importlib.util.spec_from_file_location('release_snapshot',ROOT/'scripts/snapshot_source.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dest=self.base/'snapshot'
        dest.mkdir()
        module.snapshot(ROOT,dest)
        self.assertTrue((dest/'README.md').is_file())
        self.assertTrue((dest/'skills/rethink-plan/SKILL.md').is_file())
        self.assertTrue((dest/'.github/workflows/ci.yml').is_file())
        self.assertFalse((dest/'.venv').exists())
        self.assertFalse(list(dest.rglob('*.pyc')))
        self.assertFalse(list(dest.rglob('*.egg-info')))
        with self.assertRaises(ValueError):
            module.snapshot(ROOT,dest)

    def setup_publish_mocks(self):
        if not shutil.which('git') or not shutil.which('bash'):
            self.skipTest('Git and Bash are needed to test the publish helper')
        self.bin=self.base/'bin'
        self.bin.mkdir()
        self.log=self.base/'mock-gh.log'
        gh=self.bin/'gh'
        gh.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$MOCK_LOG"
case "$1 $2" in
 'auth status') [ "$MOCK_MODE" != auth-fail ]; exit $? ;;
 'api user')
  if [ "$4" = .login ]; then echo chinrw; else echo 16910912; fi
  exit 0 ;;
 'api repos/chinrw/plan-review-bridge')
  case "$MOCK_MODE" in
    exists) echo '{}'; exit 0 ;;
    network) echo 'connection failed' >&2; exit 1 ;;
    *) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
  esac ;;
 'repo create') echo 'synthetic creation only'; exit 0 ;;
 'repo view') echo '{"url":"mock://not-a-real-created-repository","private":true}'; exit 0 ;;
esac
exit 9
''')
        gh.chmod(0o700)
        wrapper=self.bin/'python-wrapper'
        # Avoid recursively running this publish test from the publish helper.
        wrapper.write_text(f'''#!/bin/sh
if [ "$1" = -m ] && [ "$2" = unittest ]; then exit 0; fi
exec "{sys.executable}" "$@"
''')
        wrapper.chmod(0o700)
        return {**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                'MOCK_LOG':str(self.log),'PYTHON':str(wrapper)}

    def publish_mock(self,mode,target='chinrw/plan-review-bridge'):
        env=self.setup_publish_mocks()
        return subprocess.run(['bash',str(ROOT/'scripts/publish-github.sh'),target],
                     capture_output=True,text=True,env={**env,'MOCK_MODE':mode},timeout=20)

    def test_publish_stops_on_auth_failure(self):
        result=self.publish_mock('auth-fail')
        self.assertEqual(result.returncode,2)
        self.assertNotIn('repo create',self.log.read_text())

    def test_publish_stops_on_wrong_owner(self):
        result=self.publish_mock('normal','other-owner/project')
        self.assertEqual(result.returncode,2)
        self.assertNotIn('repo create',self.log.read_text())

    def test_publish_stops_on_existing_repository(self):
        result=self.publish_mock('exists')
        self.assertEqual(result.returncode,2)
        self.assertNotIn('repo create',self.log.read_text())

    def test_publish_does_not_treat_network_failure_as_missing(self):
        result=self.publish_mock('network')
        self.assertEqual(result.returncode,2)
        self.assertNotIn('repo create',self.log.read_text())

    def test_publish_mock_success_is_private_and_no_force_push(self):
        result=self.publish_mock('normal')
        self.assertEqual(result.returncode,0,result.stderr)
        log=self.log.read_text()
        self.assertIn('repo create chinrw/plan-review-bridge --private',log)
        self.assertNotIn('--public',log)
        self.assertNotIn('--force',log)
        self.assertIn('mock://not-a-real-created-repository',result.stdout)
