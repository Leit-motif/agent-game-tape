#!/usr/bin/env python3
"""Narration hill-climb harness (references/narration-climb.md): variant sources and focus, run folders, scoring.

Offline except `score`, which runs local whisper and check-narration (claude CLI). Generation itself goes
through scripts/notebooklm.py, one start per run folder. Runtime outputs belong outside this repository."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'examples'))
import make_demo  # noqa: E402
from game_tape import build_focus, load, narration, save, validate  # noqa: E402

FORMAT, LENGTH, LANGUAGE, MAX_SECONDS = 'brief', 'short', 'en', 150.0
CASE_C = ROOT / 'tests' / 'fixtures' / 'narration-climb' / 'case-c.json'


def cases():
    found = {name: (bundle, review) for name, bundle, review in make_demo.cases()}
    data = load(CASE_C)
    found['case-c'] = (data['evidence'], data['review'])
    return found


# v1 (H1): the spoken source keeps only affirmative content. Sentences of the outcome that deny a claim or
# state an interval, the causal_basis audit line, and clock times are left to the local report.
NEGATION = re.compile(r"\b(?:no|not|never|neither|nor|cannot|without|none)\b|n't\b", re.I)
NUMBER = (r'(?:\d+(?:\.\d+)?|a few|several|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|'
          r'fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?')
INTERVAL = re.compile(rf'\b{NUMBER}\s+(?:minutes?|hours?|days?)\b', re.I)
CLOCK = re.compile(r'\s*\b(?:at|by|until|from|to) \d{1,2}:\d{2}\b')
SENTENCE = re.compile(r'(?<=[.!?])\s+')


def affirmative(text):
    kept = [s for s in SENTENCE.split(text.strip()) if s and not NEGATION.search(s) and not INTERVAL.search(s)]
    return ' '.join(kept)


def narration_affirmative(bundle, review):
    parts = ['# Game tape', '']
    verdicts = {'good call': 'This was a good call.', 'costly call': 'This was a costly call.', 'mixed': 'The outcome was mixed.',
                'agent failure': 'This was an agent execution failure.', 'system failure': 'This was a system failure.',
                'unclear': 'The outcome remains unclear.'}
    for m in review['moments']:
        parts += [f"## {m['title']}", '', f"You said, “{m['human_quote']}” {CLOCK.sub('', m['action'])}", '']
        outcome = affirmative(CLOCK.sub('', m['outcome']))
        if outcome:
            parts += [outcome, '']
        parts += [verdicts[m['verdict']], '', f"{bundle['rules'][m['rule_id']]} {m['lesson']}", '']
    if review.get('experiment'):
        parts += ['## One experiment for next time', '', review['experiment']['change'], '', review['experiment']['next_check'], '']
    else:
        parts += ['## Keep the useful move', '', review['no_experiment_reason'], '']
    return '\n'.join(parts)


# v2 (H2): the focus names the literal first sentence instead of "Begin with the first decision".
BEGIN = 'Begin with the first decision in Game tape and cover the selected decisions in that order.'


def focus_first_sentence(review):
    base = build_focus(review, FORMAT)
    if BEGIN not in base:
        raise ValueError('bundled Brief focus changed; v2 is defined against the frozen sentence')
    first = f"Open with this first sentence, word for word: You said, “{review['moments'][0]['human_quote']}” Then cover the selected decisions in that order."
    return base.replace(BEGIN, first)


SOURCES = {'main': lambda b, r: narration(b, r, 'prose'), 'affirmative': narration_affirmative}
FOCUSES = {'bundled': lambda r: build_focus(r, FORMAT), 'first-sentence': focus_first_sentence}


def prepare(args):
    out = Path(args.out).expanduser().resolve()
    if out.is_relative_to(ROOT):
        raise SystemExit('runtime outputs stay outside the repository')
    for name, (bundle, review) in sorted(cases().items()):
        if args.case and name not in args.case:
            continue
        problems = validate(bundle, review)
        if problems:
            raise SystemExit(f'{name}: {problems}')
        variant = out / name / 'variant'
        variant.mkdir(parents=True, exist_ok=True, mode=0o700)
        source, focus = SOURCES[args.source](bundle, review), FOCUSES[args.focus](review)
        (variant / 'game-tape.md').write_text(source, encoding='utf-8')
        (variant / 'focus.txt').write_text(focus + '\n', encoding='utf-8')
        for rep in range(1, args.reps + 1):
            run = out / name / f'rep-{rep}'
            if run.exists():
                raise SystemExit(f'refusing to overwrite {run}')
            save(run / 'evidence.json', bundle)
            save(run / 'review.json', review)
            command = [sys.executable, str(ROOT / 'scripts' / 'game_tape.py'), 'render', str(run), '--format', FORMAT,
                       '--length', LENGTH, '--language', LANGUAGE, '--source', str(variant / 'game-tape.md'),
                       '--focus-file', str(variant / 'focus.txt')]
            subprocess.run(command, check=True, capture_output=True, text=True)
            print(run)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score(args):
    run = Path(args.run).expanduser().resolve()
    audio = run / 'audio.m4a'
    seconds = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                                    'default=noprint_wrappers=1:nokey=1', str(audio)], check=True, capture_output=True, text=True).stdout)
    asr = run / 'asr'
    if not (asr / 'audio.json').exists():
        subprocess.run([args.whisper, str(audio), '--model', 'small', '--language', 'en', '--output_format', 'json',
                        '--output_dir', str(asr), '--fp16', 'False'], check=True, capture_output=True, text=True)
    transcript = asr / 'audio.json'
    receipt_path = run / 'narration-check.json'
    if not receipt_path.exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts' / 'game_tape.py'), 'check-narration', '--run', str(run),
                        '--transcript', str(transcript), '--out', str(receipt_path)], capture_output=True, text=True)
    receipt = load(receipt_path)
    review = load(run / 'review.json')
    failures = []
    for claim in receipt['claims']:
        if claim['label'].startswith('strengthened'):
            failures.append(claim['label'])
        elif claim['label'] == 'unsupported':
            failures.append('unsupported')
    opening_ok = bool((receipt.get('opening') or {}).get('ok'))
    if not opening_ok:
        failures.append('opening')
    if receipt['decision'] == 'unverified':
        failures.append('unverified')
    if seconds > MAX_SECONDS:
        failures.append('duration')
    roles = set((receipt.get('roles') or {}).values())
    covered = all(f'moment:{n}' in roles for n in range(1, len(review['moments']) + 1)) and (
        'experiment' in roles or not review.get('experiment'))
    segments = load(transcript)['segments']
    result = {'run': str(run), 'audio_sha256': digest(audio), 'transcript_sha256': digest(transcript),
              'source_sha256': load(run / 'manifest.json')['sources'][0]['sha256'],
              'focus_sha256': load(run / 'manifest.json')['focus_sha256'], 'seconds': seconds,
              'asr_segments': len(segments), 'asr_last_end': max(s['end'] for s in segments),
              'decision': receipt['decision'], 'opening_ok': opening_ok, 'reasons': receipt['reasons'],
              'failures': sorted(set(failures)), 'flagged_claims': sum(f != 'opening' and f != 'duration' for f in failures),
              'coverage_ok': covered, 'checker_model': receipt.get('backend', {}).get('model'),
              'accepted': receipt['decision'] == 'accepted' and opening_ok and seconds <= MAX_SECONDS}
    save(run / 'score.json', result)
    print(json.dumps(result, indent=2))


def table(args):
    rows = []
    for path in sorted(Path(args.root).expanduser().glob('v*/case-*/rep-*/score.json')):
        s = load(path)
        rows.append({'round': path.parts[-4], 'case': path.parts[-3], 'rep': path.parts[-2], **{k: s[k] for k in (
            'accepted', 'seconds', 'decision', 'opening_ok', 'failures', 'flagged_claims', 'coverage_ok')}})
    for row in rows:
        print(json.dumps(row))
    totals = {}
    for row in rows:
        t = totals.setdefault(row['round'], {'episodes': 0, 'accepted': 0, 'opening_ok': 0, 'coverage_ok': 0, 'failure_types': set()})
        t['episodes'] += 1
        t['accepted'] += row['accepted']
        t['opening_ok'] += row['opening_ok']
        t['coverage_ok'] += row['coverage_ok']
        t['failure_types'] |= set(row['failures'])
    for name, t in sorted(totals.items()):
        print(json.dumps({'round': name, **t, 'failure_types': sorted(t['failure_types'])}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('prepare', help='write run folders for one variant')
    q.add_argument('--out', required=True, help='round folder, e.g. .../climb-20261021/v0')
    q.add_argument('--source', choices=sorted(SOURCES), required=True)
    q.add_argument('--focus', choices=sorted(FOCUSES), required=True)
    q.add_argument('--reps', type=int, default=2)
    q.add_argument('--case', action='append', help='limit to these cases')
    q.set_defaults(fn=prepare)
    q = sub.add_parser('score', help='measure, transcribe and check one downloaded episode')
    q.add_argument('run')
    q.add_argument('--whisper', default='whisper')
    q.set_defaults(fn=score)
    q = sub.add_parser('table', help='aggregate score.json files under a climb root')
    q.add_argument('root')
    q.set_defaults(fn=table)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
