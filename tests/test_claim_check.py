import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'examples')]
import claim_check as cc
import game_tape as tape
import narration_eval as ev
from models import TESTED_MODEL
from make_demo import cases

SEGMENTS = [
    {'start': 0.0, 'end': 2.0, 'text': " Here's your game tape."},
    {'start': 2.0, 'end': 6.5, 'text': ' At nine you asked for the regression first. It ran'},
    {'start': 6.5, 'end': 9.0, 'text': ' and kept the failing example.  The phone took 4.2 seconds.'},
    {'start': 9.0, 'end': 12.0, 'text': ' Next time, block publication on the preview.'},
]
ROLES = {'s1': ('greeting', None), 's2': ('moment', 1), 's3': ('moment', 1), 's4': ('moment', 1), 's5': ('experiment', None)}


def reply(roles=ROLES, labels=None):
    """Valid backend output: one claim per non-greeting sentence, supported unless overridden."""
    labels = labels or {}
    claims = []
    for sid, (role, moment) in roles.items():
        if role == 'greeting':
            continue
        label, slug = labels.get(sid, ('non-factual', None) if role == 'experiment' else ('supported', None))
        claims.append({'sentences': [sid], 'text': f'claim in {sid}', 'label': label, 'strength_change': slug,
                       'evidence': ['a-3'] if label != 'non-factual' else [], 'moment': moment, 'rationale': 'r'})
    return {'sentences': [{'id': k, 'role': r, 'moment': m} for k, (r, m) in roles.items()], 'claims': claims}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        _, self.bundle, self.review = next(cases())
        self.transcript = self.folder / 'audio.json'
        tape.save(self.transcript, {'text': 'x', 'segments': SEGMENTS})

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self, response):
        return cc.check(self.transcript, self.bundle, self.review, cc.FakeBackend(response))


class Sentences(unittest.TestCase):
    def test_split_and_timestamps(self):
        sents = cc.sentences(SEGMENTS)
        self.assertEqual([s['text'] for s in sents], ["Here's your game tape.", 'At nine you asked for the regression first.',
                                                      'It ran and kept the failing example.', 'The phone took 4.2 seconds.',
                                                      'Next time, block publication on the preview.'])
        self.assertEqual([s['id'] for s in sents], ['s1', 's2', 's3', 's4', 's5'])
        self.assertEqual((sents[2]['start'], sents[2]['end']), (2.0, 9.0))  # spans two segments
        self.assertEqual((sents[3]['start'], sents[3]['end']), (6.5, 9.0))

    def test_locate(self):
        sents = cc.sentences(SEGMENTS)
        self.assertEqual(cc.locate(sents, SEGMENTS, 'took 4.2   SECONDS'), ['s4'])
        self.assertEqual(cc.locate(sents, SEGMENTS, 'regression first. It ran'), ['s2', 's3'])
        with self.assertRaises(ValueError):
            cc.locate(sents, SEGMENTS, 'not said')

    def test_bad_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 't.json'
            for value in ({'segments': []}, {'text': 'only'}, [1]):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    cc.load_transcript(path)

    def test_packet_and_prompt(self):
        _, bundle, review = next(cases())
        packet = cc.evidence_packet(bundle, review)
        self.assertEqual(packet['evidence_ids'][-4:], ['review:m1', 'review:m2', 'review:experiment', 'review:blind_spots'])
        self.assertEqual(packet['events'][-1]['timestamp'], '2030-04-10T09:18:00+00:00')
        prompt = cc.build_prompt(cc.sentences(SEGMENTS), packet)
        for text in ('s4 [6.5s–9.0s] The phone took 4.2 seconds.', '| interval_as_labor |', '"review:m2"'):
            self.assertIn(text, prompt)


class Decisions(Base):
    def test_accepted(self):
        receipt = self.run_check(reply())
        self.assertEqual((receipt['decision'], receipt['reasons']), ('accepted', []))
        self.assertTrue(receipt['opening']['ok'])
        self.assertEqual(receipt['roles']['s2'], 'moment:1')
        self.assertEqual((receipt['claims'][1]['start'], receipt['claims'][1]['end']), (2.0, 9.0))
        hashes = receipt['hashes']
        self.assertEqual(hashes['transcript_sha256'], hashlib.sha256(self.transcript.read_bytes()).hexdigest())
        self.assertEqual(hashes['evidence_sha256'], tape.fingerprint(self.bundle))
        self.assertTrue(all(hashes[k] for k in ('review_sha256', 'prompt_sha256', 'response_sha256')))

    def test_rejected_on_flagged_claims(self):
        receipt = self.run_check(reply(labels={'s4': ('strengthened', 'interval_as_labor')}))
        self.assertEqual(receipt['decision'], 'rejected')
        self.assertIn('strengthened:interval_as_labor', receipt['reasons'][0])
        self.assertEqual(self.run_check(reply(labels={'s3': ('unsupported', None)}))['decision'], 'rejected')

    def test_opening(self):
        roles = dict(ROLES, s2=('methodology', None))
        receipt = self.run_check(reply(roles))
        self.assertEqual(receipt['decision'], 'rejected')
        self.assertEqual(receipt['opening'], {'ok': False, 'first_substantive_sentence': 's2', 'role': 'methodology', 'preamble': ['s2']})
        roles = {k: ('moment', 2) if r == 'moment' else (r, m) for k, (r, m) in ROLES.items()}
        self.assertFalse(self.run_check(reply(roles))['opening']['ok'])  # no moment:1 at all
        greeting_first = self.run_check(reply())
        self.assertEqual((greeting_first['opening']['first_substantive_sentence'], greeting_first['opening']['preamble']), ('s2', []))

    def test_unverified_on_invalid_output(self):
        bad = reply()
        bad['claims'][0]['evidence'] = ['a-99']
        missing = reply()
        del missing['claims'][2]
        noslug = reply(labels={'s4': ('strengthened', None)})
        slug_on_supported = reply(labels={'s4': ('supported', 'other')})
        uncited = reply()
        uncited['claims'][0]['evidence'] = []
        norole = reply()
        norole['sentences'].pop()
        late_greeting = reply(roles={**ROLES, 's4': ('greeting', None)})  # a mid-narration 'greeting' cannot skip coverage
        cases_ = [(bad, 'unknown evidence id'), (missing, 's4: not covered'), (noslug, 'needs a taxonomy slug'),
                  (slug_on_supported, 'on a supported claim'), (uncited, 'cites no evidence'), (norole, 'no role for s5'),
                  ({'claims': 'x'}, 'must be an object'), ('nonsense', 'must be an object'),
                  ({'sentences': [{'id': ['s1']}], 'claims': []}, 'unknown sentence'),
                  (late_greeting, 's4: not covered')]
        for response, reason in cases_:
            with self.subTest(reason=reason):
                receipt = self.run_check(response)
                self.assertEqual(receipt['decision'], 'unverified')
                self.assertIn(reason, ' '.join(receipt['reasons']))
        self.assertEqual(len(self.run_check(bad)['claims']), 4)  # recorded as returned

    def test_title_line_after_the_opening_quote_needs_no_claim(self):
        # Brief speaks its title right after the quoted first sentence; that must not make the episode unverified.
        tape.save(self.transcript, {'segments': [
            {'start': 0.0, 'end': 3.0, 'text': ' You said, run the regression first.'},
            {'start': 3.0, 'end': 5.0, 'text': ' This is the brief on your human AI teamwork.'},
            {'start': 5.0, 'end': 8.0, 'text': ' It ran and kept the failing example.'},
            {'start': 8.0, 'end': 11.0, 'text': ' Next time, block publication on the preview.'}]})
        roles = {'s1': ('moment', 1), 's2': ('greeting', None), 's3': ('moment', 1), 's4': ('experiment', None)}
        receipt = self.run_check(reply(roles))
        self.assertEqual((receipt['decision'], receipt['reasons']), ('accepted', []))
        self.assertTrue(receipt['opening']['ok'])
        # A content sentence the model calls a greeting is still not excused.
        receipt = self.run_check(reply({**roles, 's3': ('greeting', None)}))
        self.assertEqual(receipt['decision'], 'unverified')
        self.assertIn('s3: not covered', ' '.join(receipt['reasons']))
        self.assertTrue(cc.title_line('Welcome back.'))
        for text in ('This is the brief on your 8 minute rollback.', 'The assistant skipped the check.',
                     'This is the brief on why the assistant skipped the preview check and published the broken page anyway.',
                     'This is the brief on your eight-minute rollback.', 'This is your debrief on the rollback that saved an hour.',
                     'Welcome back, you protected the real data.', 'Hey, the assistant deleted the contacts table.',
                     "Let's dive into how the assistant fixed all three rows."):
            self.assertFalse(cc.title_line(text), text)
        # Only near the start: a title line as the sixth sentence still needs a claim.
        tape.save(self.transcript, {'segments': [{'start': float(i), 'end': i + 1.0, 'text': f' {t}'} for i, t in enumerate([
            'You said, run the regression first.', 'It ran.', 'It kept the failing example.', 'It passed.', 'It published.',
            'This is the brief on your human AI teamwork.', 'Next time, block publication on the preview.'])]})
        late = {f's{i}': ('moment', 1) for i in range(1, 6)} | {'s6': ('greeting', None), 's7': ('experiment', None)}
        receipt = self.run_check(reply(late))
        self.assertEqual(receipt['decision'], 'unverified')
        self.assertIn('s6: not covered', ' '.join(receipt['reasons']))

    def test_coverage_gap_cannot_hide_established_failure(self):
        flagged_gap = reply(labels={'s5': ('unsupported', None)})
        del flagged_gap['claims'][2]  # s4 uncovered, but s5 is an established failure
        receipt = self.run_check(flagged_gap)
        self.assertEqual(receipt['decision'], 'rejected')
        self.assertIn('s4: not covered', ' '.join(receipt['reasons']))
        bad_ids = reply(labels={'s5': ('unsupported', None)})
        bad_ids['claims'][0]['evidence'] = ['a-99']  # non-coverage problem keeps the output unverified
        self.assertEqual(self.run_check(bad_ids)['decision'], 'unverified')

    def test_backend_exception(self):
        def boom(prompt, schema):
            raise RuntimeError('quota')
        receipt = self.run_check(boom)
        self.assertEqual(receipt['decision'], 'unverified')
        self.assertIn('quota', receipt['reasons'][0])

    def test_empty_transcript_is_input_error(self):
        tape.save(self.transcript, {'segments': [{'start': 0, 'end': 1, 'text': '  '}]})
        with self.assertRaises(ValueError):
            self.run_check(reply())


class Backend(unittest.TestCase):
    def test_cli_argv_and_environment(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            return type('Done', (), {'returncode': 0, 'stderr': '', 'stdout': json.dumps({'is_error': False, 'structured_output': {'ok': 1}})})()
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'k', 'ANTHROPIC_AUTH_TOKEN': 't', 'KEEP': '1'}), \
                patch('claim_check.subprocess.run', fake_run):
            backend = cc.ClaudeCLIBackend()
            self.assertEqual(backend.complete('PROMPT', {'type': 'object'}), {'ok': 1})
        self.assertEqual(seen['argv'], ['claude', '-p', '--safe-mode', '--model', TESTED_MODEL, '--system-prompt', cc.SYSTEM,
                                        '--output-format', 'json', '--no-session-persistence', '--tools', '',
                                        '--strict-mcp-config', '--setting-sources', '', '--json-schema', '{"type": "object"}'])
        self.assertEqual(seen['input'], 'PROMPT')
        self.assertNotIn('ANTHROPIC_API_KEY', seen['env'])
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', seen['env'])
        self.assertEqual(seen['env']['KEEP'], '1')
        self.assertFalse(Path(seen['cwd']).exists())  # fresh temporary directory, removed afterwards
        self.assertIn('structured_output', backend.last_raw)

    def test_failed_call_clears_previous_raw(self):
        backend = cc.ClaudeCLIBackend()
        backend.last_raw = 'previous response'
        with patch('claim_check.subprocess.run', side_effect=OSError('no claude')), self.assertRaises(OSError):
            backend.complete('PROMPT', {})
        self.assertIsNone(backend.last_raw)

    def test_model_status_in_receipt(self):
        self.assertEqual(cc.ClaudeCLIBackend().model, TESTED_MODEL)
        _, bundle, review = next(cases())
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder) / 't.json'
            transcript.write_text(json.dumps({'segments': SEGMENTS}))
            for model, status in [(TESTED_MODEL, 'tested'), ('other-model', 'unvalidated')]:
                backend = cc.FakeBackend({'bad': 1})
                backend.model = model
                receipt = cc.check(transcript, bundle, review, backend)
                self.assertEqual(receipt['backend'], {'name': 'fake', 'model': model, 'model_status': status})

    def test_cli_error_result(self):
        done = type('Done', (), {'returncode': 0, 'stderr': '', 'stdout': json.dumps({'is_error': True})})()
        with patch('claim_check.subprocess.run', return_value=done):
            with self.assertRaises(ValueError):
                cc.ClaudeCLIBackend().complete('p', {})


class Command(Base):
    def test_check_narration_exit_codes(self):
        tape.save(self.folder / 'evidence.json', self.bundle)
        tape.save(self.folder / 'review.json', self.review)
        for response, code, decision in [(reply(), 0, 'accepted'), (reply(labels={'s3': ('unsupported', None)}), 1, 'rejected')]:
            out = self.folder / f'{decision}.json'
            argv = ['game_tape.py', 'check-narration', '--run', str(self.folder), '--transcript', str(self.transcript), '--out', str(out)]
            with self.subTest(decision=decision), patch.object(sys, 'argv', argv), \
                    patch('claim_check.ClaudeCLIBackend', lambda model: cc.FakeBackend(response)), patch('builtins.print'):
                self.assertEqual(tape.main(), code)
                self.assertEqual(tape.load(out)['decision'], decision)
        argv = ['game_tape.py', 'check-narration', '--transcript', str(self.transcript), '--out', str(out)]
        with patch.object(sys, 'argv', argv), patch('builtins.print'):
            self.assertEqual(tape.main(), 2)


class Evaluation(unittest.TestCase):
    CASE = {'id': 'tiny', 'kind': 'synthetic-perturbation', 'demo_case': 'case-a', 'transcript': {'segments': SEGMENTS},
            'expected': {'decision': 'rejected', 'opening_ok': True},
            'failures': [{'id': 'F1', 'quote': 'took 4.2 seconds', 'expected_type': 'interval_as_labor', 'note': ''}],
            'supported': [{'id': 'S1', 'quote': 'asked for the regression first', 'note': ''}]}

    def evaluate(self, responses, runs=3, case=None):
        """responses: one per run in submission order (single job keeps the order)."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cases.json'
            path.write_text(json.dumps([case or self.CASE]))
            queue = list(responses)
            with patch('builtins.print'):
                summary = ev.evaluate([path], Path(folder) / 'out', lambda: cc.FakeBackend(queue.pop(0)), runs=runs, jobs=1)
            rows = [json.loads(line) for line in (Path(folder) / 'out' / 'rows.jsonl').read_text().splitlines()]
            self.assertTrue((Path(folder) / 'out' / 'receipts' / 'tiny' / 'run-1.json').exists())
        return summary, rows

    def test_caught_and_bar_pass(self):
        flagged = reply(labels={'s4': ('strengthened', 'interval_as_labor')})
        summary, rows = self.evaluate([flagged] * 3)
        self.assertTrue(summary['bar_pass'])
        self.assertEqual((summary['model'], summary['model_status']), (None, 'unvalidated'))
        self.assertEqual(rows[0]['failures'][0], {'id': 'F1', 'sentences': ['s4'], 'caught': True,
                                                   'labels': ['strengthened:interval_as_labor'], 'type_match': True})
        self.assertEqual(summary['aggregate']['failures_caught'], 3)
        self.assertEqual(summary['aggregate']['supported_total'], 6)  # S1 plus the expected-valid opening

    def test_false_flag_unlabeled_and_instability(self):
        both = reply(labels={'s4': ('strengthened', 'other'), 's2': ('unsupported', None), 's5': ('unsupported', None)})
        summary, rows = self.evaluate([both, reply(), both])
        self.assertFalse(summary['bar_pass'])
        self.assertEqual(rows[0]['supported'][0]['flagged'], True)
        self.assertEqual(rows[0]['failures'][0]['type_match'], False)
        self.assertEqual([f['sentences'] for f in rows[0]['unlabeled_flags']], [['s5']])
        self.assertEqual(rows[1]['failures'][0]['caught'], False)
        self.assertFalse(summary['cases']['tiny']['stable'])

    def test_opening_and_unverified(self):
        methodology = reply(dict(ROLES, s2=('methodology', None)), labels={'s4': ('strengthened', 'interval_as_labor')})
        summary, rows = self.evaluate([methodology], runs=1)
        self.assertEqual(rows[0]['supported'][-1], {'id': 'opening', 'sentences': [], 'labels': [], 'flagged': True})
        case = dict(self.CASE, expected={'decision': 'rejected', 'opening_ok': False})
        summary, rows = self.evaluate([methodology], runs=1, case=case)
        self.assertTrue(rows[0]['failures'][-1]['caught'])
        summary, rows = self.evaluate([{'bad': 1}], runs=1, case=case)
        self.assertEqual(rows[0]['decision'], 'unverified')
        self.assertFalse(any(f['caught'] for f in rows[0]['failures']))
        self.assertFalse(summary['cases']['tiny']['stable'])
        self.assertFalse(summary['bar_pass'])

    def test_missing_external(self):
        case = {k: v for k, v in self.CASE.items() if k != 'transcript'}
        case['external_transcript'] = 'brief'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cases.json'
            path.write_text(json.dumps([case]))
            summary = ev.evaluate([path], Path(folder) / 'out', lambda: cc.FakeBackend(reply()), runs=1, jobs=1)
            row = json.loads((Path(folder) / 'out' / 'rows.jsonl').read_text())
        self.assertEqual(row['error'], 'missing external transcript')
        self.assertFalse(summary['bar_pass'])

    def test_external_needs_matching_hash(self):
        case = {k: v for k, v in self.CASE.items() if k != 'transcript'}
        case['external_transcript'] = 'brief'
        with tempfile.TemporaryDirectory() as folder:
            transcript, path = Path(folder) / 't.json', Path(folder) / 'cases.json'
            transcript.write_text(json.dumps(self.CASE['transcript']))
            path.write_text(json.dumps([case]))  # no external_sha256 recorded
            ev.evaluate([path], Path(folder) / 'out', lambda: cc.FakeBackend(reply()), runs=1, jobs=1, externals={'brief': transcript})
            row = json.loads((Path(folder) / 'out' / 'rows.jsonl').read_text())
        self.assertIn('sha256', row['error'])


if __name__ == '__main__':
    unittest.main()
