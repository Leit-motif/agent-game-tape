import argparse
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'examples')]
import game_tape as tape
import nlm_single_send as safe
import notebooklm as nlm
from make_demo import cases
from models import TESTED_MODEL


def doctor_stub():
    """scripts/doctor.py may be absent while it is being written; main() only needs its two hooks."""
    try:
        import doctor  # noqa: F401
        return contextlib.nullcontext()
    except ImportError:
        stub = types.ModuleType('doctor')
        stub.add_arguments = lambda parser: None
        stub.run = lambda args: 0
        return patch.dict(sys.modules, {'doctor': stub})


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RenderControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.folder = self.base / 'run'
        _, self.bundle, self.review = next(cases())
        tape.save(self.folder / 'evidence.json', self.bundle)
        tape.save(self.folder / 'review.json', self.review)
        (self.folder / 'evidence.md').write_text('# Local evidence')
        self.notes = self.base / 'team notes.md'
        self.notes.write_text('# Team notes\n\nSynthetic context for the hosts.\n')

    def tearDown(self):
        self.temp.cleanup()

    def render(self, **controls):
        args = dict(run=str(self.folder), max_words=1600, style='prose', format='deep_dive', length='default',
                    language='en', source=None, focus=None, focus_file=None)
        args.update(controls)
        with patch('builtins.print'):
            return tape.render(argparse.Namespace(**args))

    def test_default_is_narration_only_with_bundled_focus(self):
        self.assertEqual(self.render(), 0)
        manifest = tape.load(self.folder / 'manifest.json')
        narration = (self.folder / 'upload/game-tape.md').read_bytes()
        self.assertEqual(manifest['schema'], 'agent-game-tape/upload-v2')
        self.assertEqual(manifest['sources'], [{'path': 'upload/game-tape.md', 'sha256': sha(narration)}])
        self.assertEqual(manifest['focus_origin'], 'bundled')
        self.assertEqual(manifest['web_research'], 'off')
        self.assertEqual(manifest['focus_sha256'], sha((self.folder / 'upload/focus.txt').read_bytes()))

    def test_multiple_sources_are_copied_hashed_and_private(self):
        self.assertEqual(self.render(source=['narration', str(self.notes)]), 0)
        manifest = tape.load(self.folder / 'manifest.json')
        self.assertEqual([s['path'] for s in manifest['sources']], ['upload/game-tape.md', 'upload/sources/02-team_notes.md'])
        copy = self.folder / manifest['sources'][1]['path']
        self.assertEqual(copy.read_bytes(), self.notes.read_bytes())
        self.assertEqual(manifest['sources'][1]['sha256'], sha(self.notes.read_bytes()))
        self.assertEqual(copy.stat().st_mode & 0o777, 0o600)

    def test_caller_focus_text_and_file(self):
        self.assertEqual(self.render(focus='  Talk only about the first decision.  '), 0)
        manifest = tape.load(self.folder / 'manifest.json')
        self.assertEqual(manifest['focus_origin'], 'caller')
        self.assertEqual((self.folder / 'upload/focus.txt').read_text(), 'Talk only about the first decision.\n')
        focus = self.base / 'focus.txt'
        focus.write_text('Coach me on checkpoints.\n')
        self.assertEqual(self.render(focus_file=str(focus)), 0)
        self.assertEqual((self.folder / 'upload/focus.txt').read_text(), 'Coach me on checkpoints.\n')
        with self.assertRaisesRegex(ValueError, 'not both'):
            self.render(focus='x', focus_file=str(focus))
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.render(focus='   ')

    def test_private_run_files_links_folders_and_empty_files_are_refused(self):
        rules = self.base / 'rules.json'
        rules.write_text(json.dumps(self.bundle['rules']))
        self.bundle['rule_source'] = str(rules)
        tape.save(self.folder / 'evidence.json', self.bundle)
        (self.folder / 'report.md').write_text('local report')
        evidence_copy = self.base / 'innocent.json'
        evidence_copy.write_bytes((self.folder / 'evidence.json').read_bytes())
        link = self.base / 'link.md'
        link.symlink_to(self.notes)
        empty = self.base / 'empty.md'
        empty.write_text('  \n')
        refused = {'evidence.json': 'raw evidence', 'evidence.md': 'raw evidence', 'review.json': 'raw evidence',
                   'report.md': 'inside the run folder', str(rules): 'raw evidence', str(evidence_copy): 'copy of the run',
                   str(link): 'symlink', str(self.base): 'not a regular file', str(empty): 'empty'}
        for name, message in refused.items():
            path = name if name.startswith('/') else str(self.folder / name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                self.render(source=['narration', path])
            with self.subTest(focus_file=name), self.assertRaisesRegex(ValueError, message):
                self.render(focus_file=path)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.render(source=['narration', 'narration'])
        with self.assertRaisesRegex(ValueError, 'copy of the run'):
            self.render(focus=(self.folder / 'review.json').read_text())

    def test_rules_copy_elsewhere_is_refused(self):
        copy = self.base / 'my-rules.json'
        copy.write_text(json.dumps(self.bundle['rules'], indent=2, ensure_ascii=False) + '\n')
        with self.assertRaisesRegex(ValueError, 'copy of the run'):
            self.render(source=['narration', str(copy)])

    def test_refused_render_leaves_previous_upload_intact(self):
        self.assertEqual(self.render(source=['narration', str(self.notes)], focus='Keep this focus.'), 0)
        before = {p: p.read_bytes() for p in [self.folder / 'manifest.json', *sorted((self.folder / 'upload').rglob('*'))] if p.is_file()}
        failures = [dict(source=['narration', str(self.folder / 'evidence.json')]),
                    dict(source=['narration', 'narration']),
                    dict(focus_file=str(self.folder / 'evidence.md')),
                    dict(focus='   '),
                    dict(source=[str(self.base / 'missing.md')])]
        for controls in failures:
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                self.render(**controls)
            after = {p: p.read_bytes() for p in [self.folder / 'manifest.json', *sorted((self.folder / 'upload').rglob('*'))] if p.is_file()}
            self.assertEqual(after, before)

    def test_brief_and_word_limits_still_apply(self):
        self.review['moments'] *= 2
        tape.save(self.folder / 'review.json', self.review)
        with patch.object(tape, 'validate', return_value=[]), self.assertRaisesRegex(ValueError, 'at most two'):
            self.render(format='brief', source=[str(self.notes)])
        self.review['moments'] = self.review['moments'][:len(self.review['moments']) // 2]
        tape.save(self.folder / 'review.json', self.review)
        with self.assertRaisesRegex(ValueError, 'maximum 10'):
            self.render(max_words=10)

    def test_publisher_uploads_every_manifest_source(self):
        self.assertEqual(self.render(source=['narration', str(self.notes)]), 0)
        pub = nlm.Publisher(self.folder, sys.executable)
        uploaded, requests = [], []

        def remote(args, **kwargs):
            if args == ['__single_send_check__']:
                return {'single_send': True}
            if args[:2] == ['login', '--check'] or args == ['--version']:
                return 'ok'
            if args[:2] == ['notebook', 'create']:
                return {'notebook_id': 'nb1'}
            if args[:2] == ['source', 'add']:
                path = Path(args[args.index('--file') + 1])
                self.assertTrue(path.resolve().is_relative_to(self.folder / 'sealed'))
                uploaded.append(path.read_bytes())
                if len(uploaded) == 2 and not requests and not getattr(self, 'failed', False):
                    self.failed = True
                    raise ValueError('transport lost')
                return {'source_id': f'src{len(uploaded)}'}
            if args[:2] == ['studio', 'status']:
                return []
            if args[0] == '__single_send_audio__':
                requests.append(tape.load(args[1]))
                return {'artifact_id': 'audio1'}
            raise AssertionError(args)

        with patch.object(pub, 'call', side_effect=remote):
            with self.assertRaisesRegex(ValueError, 'transport lost'):
                pub.start(True)
        state = tape.load(pub.state_path)
        self.assertEqual(state['pending_mutation'], 'source_add')
        self.assertEqual(state['pending_source_sha256'], sha(self.notes.read_bytes()))
        self.assertEqual(state['source_id'], 'src1')
        # Simulate operator reconciliation of the uncertain second add, then resume without re-adding the first.
        state['source_ids'][state['pending_source_sha256']] = 'src2'
        state.update(pending_mutation=None, pending_source_sha256=None)
        tape.save(pub.state_path, state)
        pub = nlm.Publisher(self.folder, sys.executable)
        with patch.object(pub, 'call', side_effect=remote):
            pub.start(True)
        self.assertEqual(len(uploaded), 2)
        self.assertEqual(requests[0]['source_ids'], ['src1', 'src2'])
        with patch.object(pub, 'call', return_value=[{'id': 'audio1', 'status': 'completed', 'source_ids': ['src2', 'src1']}]):
            self.assertTrue(pub.status()['source_selection_recorded_match'])
        with patch.object(pub, 'call', return_value=[{'id': 'audio1', 'status': 'completed', 'source_ids': ['src1']}]):
            self.assertFalse(pub.status()['source_selection_recorded_match'])

    def test_publisher_refuses_tampered_or_escaping_sources(self):
        self.assertEqual(self.render(source=['narration', str(self.notes)]), 0)
        manifest = tape.load(self.folder / 'manifest.json')
        copy = self.folder / manifest['sources'][1]['path']
        copy.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            nlm.Publisher(self.folder, sys.executable)
        for path in ('evidence.json', '../team notes.md', 'upload/../review.json'):
            manifest['sources'][1] = {'path': path, 'sha256': 'x'}
            tape.save(self.folder / 'manifest.json', manifest)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'upload folder'):
                nlm.Publisher(self.folder, sys.executable)
        copy.unlink()
        copy.symlink_to(self.notes)
        manifest['sources'][1] = {'path': 'upload/sources/02-team_notes.md', 'sha256': sha(self.notes.read_bytes())}
        tape.save(self.folder / 'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'upload folder'):
            nlm.Publisher(self.folder, sys.executable)

    def test_v1_manifest_and_state_still_work(self):
        self.assertEqual(self.render(), 0)
        manifest = tape.load(self.folder / 'manifest.json')
        source = manifest.pop('sources')[0]
        for key in ('focus_origin', 'web_research'):
            manifest.pop(key)
        manifest.update(schema='agent-game-tape/upload-v1', source=source['path'], source_sha256=source['sha256'])
        tape.save(self.folder / 'manifest.json', manifest)
        pub = nlm.Publisher(self.folder, sys.executable)
        pub.update(notebook_id='nb1', source_id='old-src')
        requests = []

        def remote(args, **kwargs):
            if args[0] == '__single_send_audio__':
                requests.append(tape.load(args[1]))
                return {'artifact_id': 'audio1'}
            if args[:2] == ['source', 'add']:
                raise AssertionError('v1 source re-added')
            return [] if args[:2] == ['studio', 'status'] else {'single_send': True} if args[0].startswith('__') else 'ok'

        with patch.object(pub, 'call', side_effect=remote):
            pub.start(True)
        self.assertEqual(requests[0]['source_ids'], ['old-src'])
        with patch.object(pub, 'call', return_value=[{'id': 'audio1', 'status': 'completed', 'source_ids': ['old-src']}]):
            self.assertTrue(pub.status()['source_selection_recorded_match'])


class CommandLine(unittest.TestCase):
    def help_text(self, main, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(argv)
        return out.getvalue()

    def test_environment_entrypoint_hidden_but_parses(self):
        self.assertNotIn('environment-entrypoint', self.help_text(nlm.main, ['--help']))
        self.assertNotIn('environment-entrypoint', self.help_text(safe.main, ['--help']))
        with tempfile.TemporaryDirectory() as folder, patch.object(nlm, 'Publisher', side_effect=ValueError('stop')) as publisher:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(nlm.main(['status', folder, '--environment-entrypoint', '/tmp/env.py']), 2)
            self.assertEqual(publisher.call_args.args[3], '/tmp/env.py')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(safe.main(['--request', '/nonexistent.json', '--environment-entrypoint', 'x.py']), 2)
        self.assertNotIn('unrecognized', err.getvalue())

    def test_render_help_is_plain_language(self):
        with doctor_stub():
            text = self.help_text(tape.main, ['render', '--help'])
        for flag in ('--source', '--focus', '--focus-file', '--format', '--length', '--language'):
            self.assertIn(flag, text)
        self.assertNotIn('arm', text.split())
        self.assertIn('kept for comparison', text)

    def check(self, model):
        _, bundle, review = next(cases())
        receipt = {'decision': 'accepted', 'reasons': [], 'claims': [{'label': 'supported'}], 'opening': {'ok': True}}
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            tape.save(run / 'evidence.json', bundle)
            tape.save(run / 'review.json', review)
            argv = ['check-narration', '--run', folder, '--transcript', str(run / 't.json'), '--out', str(run / 'r.json')]
            argv += ['--model', model] if model else []
            out, err = io.StringIO(), io.StringIO()
            with doctor_stub(), patch('claim_check.check', return_value=receipt) as check, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(tape.main(argv), 0)
            return json.loads(out.getvalue()), err.getvalue(), check.call_args.args[3].model

    def test_check_narration_reports_model_status(self):
        printed, warning, used = self.check(None)
        self.assertEqual((printed['model'], printed['model_status'], used), (TESTED_MODEL, 'tested', TESTED_MODEL))
        self.assertEqual(warning, '')
        printed, warning, used = self.check('some-other-model')
        self.assertEqual((printed['model'], printed['model_status'], used), ('some-other-model', 'unvalidated', 'some-other-model'))
        self.assertIn(f'validated only with {TESTED_MODEL}', warning)


if __name__ == '__main__':
    unittest.main()
