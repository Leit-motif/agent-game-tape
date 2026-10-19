import argparse
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'examples')]
import game_tape as tape
import notebooklm as nlm
from make_demo import cases


class ReviewChecks(unittest.TestCase):
    def setUp(self):
        _, self.bundle, self.review = next(cases())

    def test_fictional_cases_pass(self):
        for _, bundle, review in cases():
            self.assertEqual(tape.validate(bundle, review), [])

    def test_fake_rule_rejected(self):
        self.review['moments'][0]['rule_id'] = 'R999'
        self.assertIn('unknown rule_id', ' '.join(tape.validate(self.bundle, self.review)))

    def test_false_human_and_invented_quote_rejected(self):
        self.review['moments'][0]['human_event'] = 'a-2'
        self.assertIn('human event', ' '.join(tape.validate(self.bundle, self.review)))
        self.review['moments'][0]['human_event'] = 'a-1'
        self.review['moments'][0]['human_quote'] = 'words not in the record'
        self.assertIn('not verbatim', ' '.join(tape.validate(self.bundle, self.review)))

    def test_agent_claim_is_not_tool_verification(self):
        self.review['moments'][0]['evidence'] = [{'event': 'a-2', 'quote': 'I will run the small regression first'}]
        self.assertIn('actual tool-result', ' '.join(tape.validate(self.bundle, self.review)))

    def test_subsequent_evidence_uses_order_even_when_timestamps_tie(self):
        moment = self.review['moments'][0]
        moment['assurance'] = 'unknown'
        moment['evidence'] = [{'event': 'a-1', 'quote': moment['human_quote']}]
        self.assertIn('subsequent', ' '.join(tape.validate(self.bundle, self.review)))
        earlier = copy.deepcopy(self.bundle['events'][2])
        earlier['id'] = 'a-before'
        earlier['timestamp'] = self.bundle['events'][0]['timestamp']
        self.bundle['events'].insert(0, earlier)
        moment['evidence'] = [{'event': 'a-before', 'quote': earlier['text']}]
        self.assertIn('subsequent', ' '.join(tape.validate(self.bundle, self.review)))
        self.bundle['events'][3]['timestamp'] = earlier['timestamp']
        moment['evidence'] = [{'event': 'a-3', 'quote': self.bundle['events'][3]['text']}]
        moment['assurance'] = 'verified'
        self.assertEqual(tape.validate(self.bundle, self.review), [])

    def test_collected_tied_timestamps_accept_only_subsequent_evidence(self):
        # Public seam: actual JSONL -> collect() -> validate(), not a preordered bundle.
        moment = self.review['moments'][0]
        human = {'type': 'response_item', 'timestamp': '2030-04-10T09:00:00Z',
                 'payload': {'type': 'message', 'role': 'user', 'content': moment['human_quote']}}
        result = {'type': 'response_item', 'timestamp': '2030-04-10T09:00:00Z',
                  'payload': {'type': 'function_call_output', 'output': moment['evidence'][0]['quote']}}
        metadata = {'type': 'session_meta', 'payload': {'source': 'cli'}}
        for human_first in (True, False):
            with self.subTest(human_first=human_first), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'synthetic.jsonl'
                records = [metadata] * 8 + ([human, result] if human_first else [result, human])
                path.write_text(''.join(json.dumps(row) + '\n' for row in records))
                bundle, review = copy.deepcopy(self.bundle), copy.deepcopy(self.review)
                bundle['events'], bundle['coverage'] = tape.collect(
                    [('codex', path)], *(datetime.fromisoformat(t) for t in bundle['window']))
                human_event = next(e for e in bundle['events'] if e['role'] == 'human')
                tool_event = next(e for e in bundle['events'] if e['role'] == 'tool')
                review['moments'] = review['moments'][:1]
                review['moments'][0]['human_event'] = human_event['id']
                review['moments'][0]['evidence'][0]['event'] = tool_event['id']
                review['experiment']['moment_numbers'] = [1]
                errors = tape.validate(bundle, review)
                if human_first:
                    self.assertEqual(errors, [])
                else:
                    self.assertTrue(any('subsequent' in error for error in errors), errors)
                self.assertEqual([e['line'] for e in bundle['events']], [9, 10])

    def test_context_only_call_is_not_new_moment(self):
        self.bundle['events'][0]['in_window'] = False
        self.assertIn('outside the review window', ' '.join(tape.validate(self.bundle, self.review)))

    def test_duplicate_and_missing_evidence_rejected(self):
        self.review['moments'].append(copy.deepcopy(self.review['moments'][0]))
        self.review['moments'][1]['evidence'] = []
        errors = ' '.join(tape.validate(self.bundle, self.review))
        self.assertIn('duplicate', errors)
        self.assertIn('evidence needs', errors)

    def test_causality_must_be_explicit(self):
        del self.review['moments'][0]['responsibility']
        del self.review['moments'][1]['causal_basis']
        errors = ' '.join(tape.validate(self.bundle, self.review))
        self.assertIn('responsibility', errors)
        self.assertIn('causal_basis', errors)

    def test_no_forced_experiment_on_good_day(self):
        self.review['experiment'] = None
        self.review['no_experiment_reason'] = 'Repeat the specific regression-first move; no new correction is supported.'
        self.assertEqual(tape.validate(self.bundle, self.review), [])
        self.assertIn('Keep the useful move', tape.narration(self.bundle, self.review))
        self.assertNotIn('single experiment', tape.build_focus(self.review))
        self.assertIn('supplied useful move', tape.build_focus(self.review))

    def test_absent_collection_not_quiet(self):
        self.bundle['coverage'] = [{'available': False, 'events': 0}]
        quiet = {'status': 'quiet', 'moments': [], 'reason': 'nothing collected'}
        self.assertIn('insufficient_evidence', ' '.join(tape.validate(self.bundle, quiet)))
        quiet['status'] = 'insufficient_evidence'
        self.assertEqual(tape.validate(self.bundle, quiet), [])

    def test_render_prose_keeps_facts_without_fields(self):
        prose = tape.narration(self.bundle, self.review)
        fielded = tape.narration(self.bundle, self.review, 'fielded')
        self.assertNotIn('Your call:', prose)
        for moment in self.review['moments']:
            for field in ('human_quote', 'action', 'outcome', 'lesson', 'causal_basis'):
                self.assertIn(moment[field], prose)
                self.assertIn(moment[field], fielded)
        ratio = len(prose.split()) / len(fielded.split())
        self.assertLess(abs(1 - ratio), .1)

    def test_brief_focus_does_not_force_a_moment_count_or_experiment(self):
        self.review['moments'] = self.review['moments'][:1]
        self.review['experiment'] = None
        self.review['no_experiment_reason'] = 'Repeat the demonstrated checkpoint; no new experiment is supported.'
        focus = tape.build_focus(self.review, 'brief')
        self.assertIn('selected decisions', focus)
        self.assertNotIn('two decisions', focus)
        self.assertNotIn('single experiment', focus)
        self.assertIn('supplied useful move', focus)
        self.assertEqual(tape.validate(self.bundle, self.review), [])

    def test_previous_experiment_needs_observed_followup(self):
        self.bundle['previous_review'] = {'experiment': {'change': 'check first'}}
        self.assertIn('previous_followup', ' '.join(tape.validate(self.bundle, self.review)))
        self.review['previous_followup'] = {'status': 'applied', 'evidence': [], 'summary': 'No visible evidence.'}
        self.assertIn('absence is not_visible', ' '.join(tape.validate(self.bundle, self.review)))
        self.review['previous_followup']['status'] = 'not_visible'
        self.assertEqual(tape.validate(self.bundle, self.review), [])

    def test_dst_windows_are_calendar_days(self):
        start, end = tape.day_window('2030-03-10', 'America/Chicago')
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 23)
        start, end = tape.day_window('2030-11-03', 'America/Chicago')
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 25)


class PublisherChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        _, bundle, review = next(cases())
        tape.save(self.folder / 'evidence.json', bundle)
        tape.save(self.folder / 'review.json', review)
        args = argparse.Namespace(run=str(self.folder), max_words=1600, style='prose', format='deep_dive', length='default', language='en')
        with patch('builtins.print'):
            self.assertEqual(tape.render(args), 0)

    def tearDown(self):
        self.temp.cleanup()

    def publisher(self):
        return nlm.Publisher(self.folder, sys.executable)

    def test_changed_source_blocks_resume(self):
        (self.folder / 'upload/game-tape.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.publisher()

    def test_changed_review_blocks_resume(self):
        review = tape.load(self.folder / 'review.json')
        review['moments'][0]['outcome'] += ' Extra claim.'
        tape.save(self.folder / 'review.json', review)
        with self.assertRaisesRegex(ValueError, 'review.json changed'):
            self.publisher()

    def test_symlink_cannot_turn_allowlisted_source_into_evidence(self):
        source = self.folder / 'upload/game-tape.md'
        content = source.read_bytes()
        other = self.folder / 'private.md'
        other.write_bytes(content)
        source.unlink()
        source.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'inside the run'):
            self.publisher()

    def test_upload_requires_explicit_gate(self):
        pub = self.publisher()
        with self.assertRaisesRegex(ValueError, 'allow-upload'):
            pub.start(False)

    def test_uncertain_remote_write_not_retried(self):
        pub = self.publisher()
        with patch.object(pub, 'call', side_effect=ValueError('transport lost')) as call:
            with self.assertRaises(ValueError):
                pub.mutation('audio_create', ['audio', 'create'])
            with self.assertRaisesRegex(ValueError, 'uncertain outcome'):
                pub.mutation('audio_create', ['audio', 'create'])
            self.assertEqual(call.call_count, 1)
        self.assertEqual(tape.load(pub.state_path)['pending_mutation'], 'audio_create')

    def test_start_resume_no_duplicate_generation(self):
        pub = self.publisher()
        responses = [{'single_send': True}, 'valid', 'nlm version test', {'notebook_id': 'nb1'}, {'source_id': 'src1'}, [], {'artifact_id': 'audio1'}]
        with patch.object(pub, 'call', side_effect=responses) as call:
            state = pub.start(True)
            self.assertEqual(state['artifact_id'], 'audio1')
            self.assertEqual(call.call_count, 7)
            pub.start(True)
            self.assertEqual(call.call_count, 7)
        self.assertEqual(state['audio_quality'], 'unverified')

    def test_upload_uses_sealed_verified_bytes_not_later_path_contents(self):
        pub = self.publisher()
        expected = pub.payloads['source']
        calls = []
        def remote(args, **kwargs):
            calls.append(args)
            if args == ['__single_send_check__']:
                return {'single_send': True}
            if args[:2] == ['login', '--check']:
                (self.folder / 'upload/game-tape.md').write_text('externally modified after verification')
                return 'valid'
            if args == ['--version']:
                return 'test-version'
            if args[:2] == ['notebook', 'create']:
                return {'notebook_id': 'nb1'}
            if args[:2] == ['source', 'add']:
                self.assertEqual(Path(args[args.index('--file') + 1]).read_bytes(), expected)
                return {'source_id': 'src1'}
            if args[:2] == ['studio', 'status']:
                return []
            if args[0] == '__single_send_audio__':
                request = tape.load(args[1])
                self.assertEqual(request['source_ids'], ['src1'])
                self.assertEqual(request['focus_prompt'], pub.payloads['focus'].decode().strip())
                return {'artifact_id': 'audio1'}
            raise AssertionError(args)
        with patch.object(pub, 'call', side_effect=remote):
            with nlm.lock(self.folder):
                pub.start(True)
        self.assertEqual(pub.state['artifact_id'], 'audio1')

    def test_malformed_remote_id_keeps_uncertain_mutation(self):
        pub = self.publisher()
        responses = [{'single_send': True}, 'valid', 'test-version', {'notebook_id': 123}]
        with patch.object(pub, 'call', side_effect=responses):
            with self.assertRaisesRegex(ValueError, 'valid string id'):
                pub.start(True)
        self.assertEqual(pub.state['pending_mutation'], 'notebook_create')
        self.assertNotIn('notebook_id', pub.state)

    def test_exact_artifact_required(self):
        pub = self.publisher()
        pub.update(notebook_id='nb1', artifact_id='audio1')
        with patch.object(pub, 'call', return_value=[{'id': 'other', 'status': 'completed'}]):
            with self.assertRaisesRegex(ValueError, 'tracked artifact absent'):
                pub.status()

    def test_generated_never_means_quality_accepted(self):
        pub = self.publisher()
        pub.update(notebook_id='nb1', artifact_id='audio1')
        with patch.object(pub, 'call', return_value=[{'id': 'audio1', 'status': 'completed'}]):
            state = pub.status()
        self.assertEqual(state['generation_state'], 'generated')
        self.assertEqual(state['audio_quality'], 'unverified')

    def test_lock_excludes_concurrent_publishers(self):
        with nlm.lock(self.folder):
            with self.assertRaisesRegex(ValueError, 'another publisher'):
                with nlm.lock(self.folder):
                    pass
        self.assertFalse((self.folder / '.publisher.lock').exists())
        with nlm.lock(self.folder):
            with self.assertRaisesRegex(ValueError, 'another publisher'):
                tape.render(argparse.Namespace(run=str(self.folder)))

    def test_full_audio_scan_never_auto_accepts(self):
        transcript = {'text': 'A clean opening. Later the agent lied.', 'segments': [{'start': 0, 'end': 600, 'text': 'text'}]}
        path = self.folder / 'transcript.json'
        tape.save(path, transcript)
        out = self.folder / 'qa.json'
        with patch('builtins.print'):
            tape.audit_audio(argparse.Namespace(transcript=str(path), out=str(out), duration=600))
        result = tape.load(out)
        self.assertTrue(result['coverage_plausible'])
        self.assertIn('motive', result['flags'])
        self.assertEqual(result['editorial_acceptance'], 'pending_semantic_review')


if __name__ == '__main__':
    unittest.main()
