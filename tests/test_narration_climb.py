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

    def test_affirmative_source_drops_negations_and_intervals(self):
        self.assertEqual(climb.affirmative('It passed. It did not rerun. Eight minutes elapsed.'), 'It passed.')


if __name__ == '__main__':
    unittest.main()
