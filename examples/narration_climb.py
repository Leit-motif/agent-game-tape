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
from game_tape import load, narration, save, validate  # noqa: E402

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
# The bundled Brief focus as the study froze it (v0). The shipped default now carries v2's opening, so the
# baseline is kept here to keep every earlier round reproducible byte for byte.
V0_BRIEF = ('A short coaching debrief spoken directly to the person reviewing their human–AI teamwork, using “you” for that '
            'person and “the assistant” for the agent. ' + BEGIN + ' State each recorded call, the supported result with its '
            'uncertainty, and its practical lesson; keep the distinction between what the assistant reported and what the '
            'record confirmed. {{closing}} Keep the debrief on those decisions and that supplied closing.')


def build_focus(review, audio_format=FORMAT):
    closing = ('Close with the single experiment for next time and its observable check.' if review.get('experiment')
               else 'Close by reinforcing the supplied useful move to keep.')
    return V0_BRIEF.replace('{{closing}}', closing)


def focus_first_sentence(review):
    base = build_focus(review, FORMAT)
    if BEGIN not in base:
        raise ValueError('bundled Brief focus changed; v2 is defined against the frozen sentence')
    first = f"Open with this first sentence, word for word: You said, “{review['moments'][0]['human_quote']}” Then cover the selected decisions in that order."
    return base.replace(BEGIN, first)


# v3 (H3, chosen from v0–v2 failures): every v0/v1 episode opened with a title line and a methodology overview
# (opening failure); in v2 the same overview, pushed after the quote, left the checker unable to verify. The focus
# asks for no overview of the session or description of the review before the first decision.
NO_OVERVIEW = ('Do not give an overview of the session or describe the review; after at most a one-line title, '
               'begin directly with the first decision in Game tape and cover the selected decisions in that order.')


def focus_no_overview(review):
    base = build_focus(review, FORMAT)
    if BEGIN not in base:
        raise ValueError('bundled Brief focus changed; v3 is defined against the frozen sentence')
    return base.replace(BEGIN, NO_OVERVIEW)


# Amended round 1 (r1): on top of v2's opening, one focus sentence aimed at the commonest remaining failure in the
# main-source lineage (v0, v2): invented time savings, prevented damage and intervals re-voiced as durations.
CONFIRMED = "keep the distinction between what the assistant reported and what the record confirmed."
NO_DURATIONS = ('Do not mention durations, elapsed minutes, or any time, damage or effort saved; '
                'those stay in the written report.')


def focus_no_durations(review):
    base = focus_first_sentence(review)
    if CONFIRMED not in base:
        raise ValueError('bundled Brief focus changed; r1 is defined against the frozen sentence')
    return base.replace(CONFIRMED, f'{CONFIRMED} {NO_DURATIONS}')


SOURCES = {'main': lambda b, r: narration(b, r, 'prose'), 'affirmative': narration_affirmative}
FOCUSES = {'bundled': lambda r: build_focus(r, FORMAT), 'first-sentence': focus_first_sentence,
           'no-overview': focus_no_overview, 'first-sentence-no-durations': focus_no_durations}


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
    asr = run / 'asr'
    if not (asr / 'audio.json').exists():
        subprocess.run([args.whisper, str(audio), '--model', 'small', '--language', 'en', '--output_format', 'json',
                        '--output_dir', str(asr), '--fp16', 'False'], check=True, capture_output=True, text=True)
    receipt_path = run / 'narration-check.json'
    if not receipt_path.exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts' / 'game_tape.py'), 'check-narration', '--run', str(run),
                        '--transcript', str(asr / 'audio.json'), '--out', str(receipt_path)], capture_output=True, text=True)
    summarize(run, receipt_path, run / 'score.json')


def recorded_response(receipt):
    """The backend output a receipt recorded (roles and claims), in the backend's own shape."""
    sentences = []
    for sid, role in receipt['roles'].items():
        kind, _, n = role.partition(':')
        sentences.append({'id': sid, 'role': kind, 'moment': int(n) if n else None})
    claims = []
    for c in receipt['claims']:
        label, _, slug = (c['label'] or '').partition(':')
        claims.append({'sentences': c['sentences'], 'text': c['text'], 'label': label or None, 'strength_change': slug or None,
                       'evidence': c['evidence'], 'moment': c['moment'], 'rationale': c['rationale']})
    return {'sentences': sentences, 'claims': claims}


def rescore(args):
    """Re-validate a recorded receipt with the current checker code; no model call. Writes new files, keeps the old."""
    import claim_check
    run = Path(args.run).expanduser().resolve()
    old = load(run / 'narration-check.json')
    receipt = claim_check.check(run / 'asr' / 'audio.json', load(run / 'evidence.json'), load(run / 'review.json'),
                                claim_check.FakeBackend(recorded_response(old)))
    receipt['backend'] = {**old['backend'], 'rescored_from': 'narration-check.json',
                          'rescored_with': 'recorded roles and claims, current validation; no new model call'}
    receipt_path = run / 'narration-check.rescore.json'
    for path in (receipt_path, run / 'score.rescore.json'):
        if path.exists():
            raise SystemExit(f'refusing to overwrite {path}')
    save(receipt_path, receipt)
    summarize(run, receipt_path, run / 'score.rescore.json', previous=load(run / 'score.json'))


def summarize(run, receipt_path, out, previous=None):
    audio, transcript = run / 'audio.m4a', run / 'asr' / 'audio.json'
    seconds = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                                    'default=noprint_wrappers=1:nokey=1', str(audio)], check=True, capture_output=True, text=True).stdout)
    receipt = load(receipt_path)
    review = load(run / 'review.json')
    failures = []
    for claim in receipt['claims']:
        if (claim['label'] or '').startswith('strengthened'):
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
    if previous:
        result['previous'] = {k: previous[k] for k in ('decision', 'failures', 'accepted')}
    save(out, result)
    print(json.dumps(result, indent=2))


def table(args):
    rows = []
    root = Path(args.root).expanduser()
    for path in sorted([*root.glob('v*/case-*/rep-*/score.json'), *root.glob('r*/case-*/rep-*/score.json')]):
        rescored = path.with_name('score.rescore.json')
        s = load(rescored if rescored.exists() else path)
        rows.append({'round': path.parts[-4], 'case': path.parts[-3], 'rep': path.parts[-2], 'rescored': rescored.exists(), **{k: s[k] for k in (
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
    q = sub.add_parser('rescore', help='re-validate a recorded receipt with the current checker; writes *.rescore.json')
    q.add_argument('run')
    q.set_defaults(fn=rescore)
    q = sub.add_parser('table', help='aggregate score.json files under a climb root')
    q.add_argument('root')
    q.set_defaults(fn=table)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
