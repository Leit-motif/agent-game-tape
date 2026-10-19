import argparse
import copy
import json
import sys
import tempfile
import unittest
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
        responses = ['valid', {'notebook_id': 'nb1'}, {'source_id': 'src1'}, [], {'artifact_id': 'audio1'}]
        with patch.object(pub, 'call', side_effect=responses) as call:
            state = pub.start(True)
            self.assertEqual(state['artifact_id'], 'audio1')
            self.assertEqual(call.call_count, 5)
            pub.start(True)
            self.assertEqual(call.call_count, 5)
        self.assertEqual(state['audio_quality'], 'unverified')

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
