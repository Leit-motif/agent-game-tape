import argparse
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts')]
import doctor
from models import TESTED_MODEL


class Doctor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'home'
        self.root = Path(self.temp.name) / 'root'
        (self.home / '.claude' / 'projects' / 'p').mkdir(parents=True)
        (self.home / '.claude' / 'projects' / 'p' / 'a.jsonl').write_text('not read')
        self.calls = []
        self.logged_in = True
        self.which = {'claude': '/bin/claude'}
        env = {k: v for k, v in os.environ.items()
               if k not in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GAME_TAPE_HOME', 'NOTEBOOKLM_MCP_CLI_PATH')}
        env['HOME'] = str(self.home)
        for patcher in [patch.dict(os.environ, env, clear=True), patch('doctor.shutil.which', self.which.get),
                        patch('doctor.subprocess.run', self.fake_run)]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def fake_run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:] == ['--version']:
            out = '2.0.0 (Claude Code)' if argv[0] == '/bin/claude' else 'nlm 0.15.6'
        elif argv[1:3] == ['auth', 'status']:
            self.assertEqual((kwargs['env']['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'], kwargs['env']['DISABLE_TELEMETRY']), ('1', '1'))
            out = json.dumps({'loggedIn': self.logged_in, 'authMethod': 'claude.ai' if self.logged_in else 'none'})
        elif argv[1] == '-p':
            self.assertNotIn('ANTHROPIC_API_KEY', kwargs['env'])
            self.assertEqual(kwargs['env']['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'], '1')
            out = json.dumps({'is_error': False, 'result': 'OK'})
        else:
            raise AssertionError(argv)
        return subprocess.CompletedProcess(argv, 0, out, '')

    def run_doctor(self, *argv):
        parser = argparse.ArgumentParser()
        doctor.add_arguments(parser)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.run(parser.parse_args(['--root', str(self.root), *argv]))
        return code, out.getvalue()

    def report(self, *argv):
        code, out = self.run_doctor('--json', *argv)
        report = json.loads(out)
        return code, report, {c['id']: c for c in report['checks']}

    def test_pass_and_json_shape(self):
        code, report, checks = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(set(report), {'schema', 'ok', 'root', 'tested_model', 'checks', 'next_steps', 'marker'})
        self.assertEqual((report['ok'], report['root'], report['tested_model'], report['marker']), (True, str(self.root), TESTED_MODEL, None))
        self.assertEqual(list(checks), ['python', 'claude_cli', 'claude_login', 'model_probe', 'transcripts', 'skill', 'nlm', 'nlm_login'])
        self.assertEqual({k: c['status'] for k, c in checks.items()},
                         {'python': 'pass', 'claude_cli': 'pass', 'claude_login': 'pass', 'model_probe': 'skipped',
                          'transcripts': 'pass', 'skill': 'missing', 'nlm': 'missing', 'nlm_login': 'missing'})
        self.assertIn('Claude Code: 1 files', checks['transcripts']['detail'])
        self.assertIn("pipx install 'notebooklm-mcp-cli==0.15.6', then nlm login", report['next_steps'])
        self.assertNotIn('nlm login', report['next_steps'])
        self.assertEqual(checks['claude_login']['kind'], 'audio check')
        self.assertTrue(report['next_steps'][-1].endswith('doctor --write-marker'))
        self.assertFalse(self.root.exists())  # read-only by default

    def test_table_output(self):
        code, out = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn('✓ claude CLI', out)
        self.assertIn('Next steps:\n  1. ', out)

    def test_missing_claude(self):
        del self.which['claude']
        self.logged_in = False
        code, report, checks = self.report()
        self.assertEqual(code, 1)
        self.assertEqual((checks['claude_cli']['status'], checks['claude_login']['status']), ('fail', 'unknown'))
        self.assertIn('Install Claude Code: https://docs.claude.com/en/docs/claude-code', report['next_steps'])
        self.assertEqual(self.calls, [])

    def test_logged_out_is_reported_but_not_required(self):
        self.logged_in = False
        code, report, checks = self.report()
        self.assertEqual((code, checks['claude_login']['status']), (0, 'fail'))
        self.assertIn('Run `claude`, then type /login', report['next_steps'])

    def test_no_stores(self):
        (self.home / '.claude' / 'projects' / 'p' / 'a.jsonl').unlink()
        code, report, checks = self.report()
        self.assertEqual((code, checks['transcripts']['status']), (1, 'fail'))
        codex = Path(self.temp.name) / 'codex'
        (codex / 'sessions').mkdir(parents=True)
        (codex / 'sessions' / 'b.jsonl').write_text('')
        with patch.dict(os.environ, {'CODEX_HOME': str(codex)}):
            code, report, checks = self.report()
        self.assertEqual(code, 0)
        self.assertIn('Codex: 1 files', checks['transcripts']['detail'])

    def test_count_is_bounded_and_never_opens(self):
        with patch('builtins.open', side_effect=AssertionError('opened')):
            self.assertEqual(doctor.count_jsonl(self.home / '.claude'), (1, True))
            self.assertEqual(doctor.count_jsonl(self.home / '.claude', limit=1), (0, False))

    def test_marker_only_when_passing(self):
        del self.which['claude']
        code, report, _ = self.report('--write-marker')
        self.assertEqual((code, report['marker']), (1, None))
        self.assertFalse(self.root.exists())
        self.which['claude'] = '/bin/claude'
        self.root.mkdir(mode=0o755)
        os.chmod(self.root, 0o755)
        code, report, _ = self.report('--write-marker')
        marker = self.root / '.doctor-ok.json'
        self.assertEqual((code, report['marker']), (0, str(marker)))
        body = json.loads(marker.read_text())
        self.assertEqual(set(body), {'schema', 'written_at', 'python', 'claude_version', 'tested_model', 'model_probe'})
        self.assertEqual((body['claude_version'], body['tested_model'], body['model_probe']), ('2.0.0 (Claude Code)', TESTED_MODEL, 'not run'))
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(os.listdir(self.root), ['.doctor-ok.json'])

    def test_probe_only_with_flag(self):
        self.report()
        self.assertFalse(any('-p' in argv for argv in self.calls))
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}):
            code, report, checks = self.report('--probe-model', '--write-marker')
        probe = [argv for argv in self.calls if '-p' in argv]
        self.assertEqual(probe, [['/bin/claude', '-p', '--safe-mode', '--model', TESTED_MODEL, '--output-format', 'json',
                                  '--no-session-persistence', '--tools', '', '--strict-mcp-config', '--setting-sources', '',
                                  'Reply with OK']])
        self.assertEqual(checks['model_probe']['status'], 'pass')
        self.assertEqual(json.loads((self.root / '.doctor-ok.json').read_text())['model_probe'], 'pass')

    def test_skill_link_must_point_here(self):
        skills = self.home / '.claude' / 'skills'
        skills.mkdir(parents=True)
        (skills / 'agent-game-tape').symlink_to(self.home)
        code, report, checks = self.report()
        self.assertEqual((code, checks['skill']['status']), (0, 'unknown'))
        self.assertIn('points elsewhere', checks['skill']['detail'])
        self.assertEqual(checks['skill']['next_step'], f'ln -sfn "{doctor.REPO}" "{skills / "agent-game-tape"}"')
        (skills / 'agent-game-tape').unlink()
        (skills / 'agent-game-tape').symlink_to(doctor.REPO)
        _, _, checks = self.report()
        self.assertEqual(checks['skill']['status'], 'pass')

    def test_nlm_local_login_check(self):
        self.which['nlm'] = '/bin/nlm'
        _, _, checks = self.report()
        self.assertEqual((checks['nlm']['status'], checks['nlm_login']['status']), ('pass', 'missing'))
        profile = self.home / '.notebooklm-mcp-cli' / 'profiles' / 'default'
        profile.mkdir(parents=True)
        _, _, checks = self.report()
        self.assertEqual(checks['nlm_login']['status'], 'unknown')
        (profile / 'cookies.json').write_text('secret')
        with patch('builtins.open', side_effect=AssertionError('opened')):
            _, _, checks = self.report()
        self.assertEqual(checks['nlm_login']['status'], 'pass')


if __name__ == '__main__':
    unittest.main()
