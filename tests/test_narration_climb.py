import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'examples')]
import narration_climb as climb


class ClimbVariants(unittest.TestCase):
    def test_focus_variants_change_only_the_opening_sentence(self):
        for name, (_, review) in climb.cases().items():
            base = climb.FOCUSES['bundled'](review)
            for key, sentence in (('first-sentence', 'Open with this first sentence'), ('no-overview', climb.NO_OVERVIEW)):
                focus = climb.FOCUSES[key](review)
                self.assertIn(sentence, focus, name)
                self.assertNotIn(climb.BEGIN, focus, name)
                head, tail = base.split(climb.BEGIN)
                self.assertTrue(focus.startswith(head) and focus.endswith(tail), name)

    def test_no_durations_adds_one_sentence_to_the_first_sentence_focus(self):
        for name, (_, review) in climb.cases().items():
            v2, r1 = climb.FOCUSES['first-sentence'](review), climb.FOCUSES['first-sentence-no-durations'](review)
            self.assertEqual(r1.replace(' ' + climb.NO_DURATIONS, ''), v2, name)

    def test_shipped_brief_focus_is_the_measured_v2_focus(self):
        from game_tape import build_focus
        for name, (_, review) in climb.cases().items():
            self.assertEqual(build_focus(review, 'brief'), climb.FOCUSES['first-sentence'](review), name)
            self.assertIn(climb.BEGIN, climb.FOCUSES['bundled'](review), name)  # v0 baseline stays frozen

    def test_affirmative_source_drops_negations_and_intervals(self):
        self.assertEqual(climb.affirmative('It passed. It did not rerun. Eight minutes elapsed.'), 'It passed.')


    def test_rescore_replays_the_recorded_response(self):
        import tempfile
        import claim_check as cc
        from game_tape import save
        _, (bundle, review) = sorted(climb.cases().items())[0]
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder) / 'audio.json'
            save(transcript, {'segments': [{'start': 0, 'end': 2, 'text': ' This is the brief on your game tape.'},
                                           {'start': 2, 'end': 5, 'text': ' It rolled back after eight minutes.'},
                                           {'start': 5, 'end': 8, 'text': ' Next time, block publication on the preview.'}]})
            response = {'sentences': [{'id': 's1', 'role': 'greeting', 'moment': None}, {'id': 's2', 'role': 'moment', 'moment': 2},
                                      {'id': 's3', 'role': 'experiment', 'moment': None}],
                        'claims': [{'sentences': ['s2'], 'text': 'eight-minute rollback', 'label': 'strengthened',
                                    'strength_change': 'interval_as_labor', 'evidence': ['review:m2'], 'moment': 2, 'rationale': 'r'},
                                   {'sentences': ['s3'], 'text': 'block publication', 'label': 'non-factual',
                                    'strength_change': None, 'evidence': [], 'moment': None, 'rationale': 'r'}]}
            first = cc.check(transcript, bundle, review, cc.FakeBackend(response))
            again = cc.check(transcript, bundle, review, cc.FakeBackend(climb.recorded_response(first)))
        self.assertEqual(first['decision'], 'rejected')
        for key in ('decision', 'reasons', 'claims', 'roles', 'opening'):
            self.assertEqual(again[key], first[key], key)


if __name__ == '__main__':
    unittest.main()
