#!/usr/bin/env python3
"""Score check-narration against labelled cases over repeated runs (references/checker-eval.md)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'examples')]
import claim_check
from models import TESTED_MODEL, model_status
from game_tape import save
from make_demo import cases as demo_cases


def load_cases(paths):
    found, seen = [], set()
    for path in paths:
        for case in json.loads(Path(path).read_text(encoding='utf-8')):
            if not re.fullmatch(r'[A-Za-z0-9._-]+', str(case.get('id', ''))) or case['id'] in seen:
                raise ValueError(f"case id must be unique and path-safe: {case.get('id')!r}")
            seen.add(case['id'])
            found.append(case)
    return found


def score(case, run, receipt=None, segments=None, error=None):
    """One raw row. Opening is scored as a labelled failure or supported item."""
    decision = receipt['decision'] if receipt else None
    live = decision in ('accepted', 'rejected')
    claims = receipt['claims'] if receipt and live else []
    opening_ok = (receipt.get('opening') or {}).get('ok') if receipt else None
    expected = case['expected']
    row = {'case': case['id'], 'kind': case['kind'], 'run': run, 'decision': decision,
           'expected_decision': expected['decision'], 'opening_ok': opening_ok,
           'expected_opening_ok': expected['opening_ok'], 'failures': [], 'supported': [], 'unlabeled_flags': [],
           'error': error}
    labelled = set()

    def covering(ids):
        return [c for c in claims if set(map(str, c.get('sentences') or [])) & set(ids)]

    for item in case.get('failures', []):
        ids = []
        if receipt and not error:
            try:
                ids = claim_check.locate(receipt['sentences'], segments, item['quote'])
            except ValueError as exc:
                row['error'] = row['error'] or f"{item['id']}: {exc}"
        labelled.update(ids)
        hits = covering(ids)
        kind = item.get('expected_type')
        row['failures'].append({'id': item['id'], 'sentences': ids, 'caught': any(claim_check.flagged(c['label']) for c in hits),
                                'labels': [c['label'] for c in hits],
                                'type_match': None if kind is None else any(c['label'] in (kind, f'strengthened:{kind}') for c in hits)})
    for item in case.get('supported', []):
        ids = []
        if receipt and not error:
            try:
                ids = claim_check.locate(receipt['sentences'], segments, item['quote'])
            except ValueError as exc:
                row['error'] = row['error'] or f"{item['id']}: {exc}"
        labelled.update(ids)
        hits = covering(ids)
        row['supported'].append({'id': item['id'], 'sentences': ids, 'flagged': any(claim_check.flagged(c['label']) for c in hits),
                                 'labels': [c['label'] for c in hits]})
    opening = {'id': 'opening', 'sentences': [], 'labels': []}
    if expected['opening_ok']:
        row['supported'].append({**opening, 'flagged': live and opening_ok is False})
    else:
        row['failures'].append({**opening, 'caught': live and opening_ok is False, 'type_match': None})
    row['unlabeled_flags'] = [{'claim': c['id'], 'sentences': c.get('sentences'), 'label': c['label'], 'text': c.get('text')}
                              for c in claims if claim_check.flagged(c['label']) and not set(map(str, c.get('sentences') or [])) & labelled]
    return row


def git_state():
    """HEAD and whether the tree differs from it, so a result can be tied to the committed checker."""
    try:
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, timeout=10)
    except OSError:
        return {'commit': None, 'dirty': None}
    return {'commit': head.stdout.strip() or None if head.returncode == 0 else None,
            'dirty': bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


def evaluate(case_paths, out, backend_factory, runs=3, jobs=4, externals=None, model=None):
    started = datetime.now(timezone.utc).isoformat()
    out = Path(out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError(f'{out} is not empty; use a new folder (results are never overwritten)')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.chmod(0o700)
    cases = load_cases(case_paths)
    demo = {name: (bundle, review) for name, bundle, review in demo_cases()}
    externals = externals or {}
    transcripts = {}
    for case in cases:
        if 'transcript' in case:
            transcripts[case['id']] = (out / 'transcripts' / f"{case['id']}.json", None)
            save(transcripts[case['id']][0], case['transcript'])
            continue
        path = externals.get(case.get('external_transcript'))
        if path is None or not Path(path).is_file():
            transcripts[case['id']] = (None, 'missing external transcript')
        elif case.get('external_sha256') != hashlib.sha256(Path(path).read_bytes()).hexdigest():
            transcripts[case['id']] = (None, 'external transcript sha256 differs from the labelled file')
        else:
            transcripts[case['id']] = (path, None)
    lock, rows = threading.Lock(), []

    def task(case, run):
        path, error = transcripts[case['id']]
        if error:
            row = score(case, run, error=error)
        else:
            try:
                bundle, review = demo[case['demo_case']]
                receipt = claim_check.check(path, bundle, review, backend_factory())
                save(out / 'receipts' / case['id'] / f'run-{run}.json', receipt)
                row = score(case, run, receipt, claim_check.load_transcript(path)[1])
            except Exception as exc:  # recorded as an error row; the bar fails
                row = score(case, run, error=f'{type(exc).__name__}: {exc}')
        with lock:
            rows.append(row)
            with (out / 'rows.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for future in [pool.submit(task, case, run) for case in cases for run in range(1, runs + 1)]:
            future.result()
    summary = summarize(cases, rows, runs)
    summary.update(started_at=started, finished_at=datetime.now(timezone.utc).isoformat(), model=model,
                   model_status=model_status(model),
                   git=git_state(), case_files=[{'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in case_paths],
                   externals={k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in externals.items() if Path(v).exists()})
    save(out / 'summary.json', summary)
    return summary


def _tally(rows):
    failures = [f for r in rows for f in r['failures']]
    supported = [s for r in rows for s in r['supported']]
    typed = [f for f in failures if f['type_match'] is not None]
    return {'failures_caught': sum(f['caught'] for f in failures), 'failures_total': len(failures),
            'supported_flagged': sum(s['flagged'] for s in supported), 'supported_total': len(supported),
            'type_match': sum(bool(f['type_match']) for f in typed), 'type_total': len(typed),
            'unlabeled_flags': sum(len(r['unlabeled_flags']) for r in rows), 'errors': sum(bool(r['error']) for r in rows)}


def summarize(cases, rows, runs):
    rows = sorted(rows, key=lambda r: ([c['id'] for c in cases].index(r['case']), r['run']))
    per_case = {}
    for case in cases:
        mine = [r for r in rows if r['case'] == case['id']]
        decisions = [r['decision'] for r in mine]
        per_case[case['id']] = {'kind': case['kind'], 'expected_decision': case['expected']['decision'], 'decisions': decisions,
                                'stable': len(mine) == runs and len(set(decisions)) == 1 and decisions[0] in ('accepted', 'rejected'),
                                'decision_correct': sum(d == case['expected']['decision'] for d in decisions),
                                'opening_ok': [r['opening_ok'] for r in mine], **_tally(mine)}
    per_run = [{'run': k, **_tally([r for r in rows if r['run'] == k])} for k in range(1, runs + 1)]
    total = _tally(rows)
    total.update(decision_correct=sum(c['decision_correct'] for c in per_case.values()), decision_total=len(rows))
    bar = (all(r['failures_caught'] == r['failures_total'] and r['supported_flagged'] == 0 for r in per_run)
           and all(c['stable'] for c in per_case.values()) and total['errors'] == 0 and len(rows) == len(cases) * runs)
    return {'schema': 'agent-game-tape/narration-eval-v1', 'runs': runs, 'per_run': per_run, 'aggregate': total,
            'cases': per_case, 'bar_pass': bar}


def table(summary):
    lines = [f"{'case':28} {'kind':24} {'expect':9} {'decisions':30} {'caught':>7} {'false':>6} {'unlab':>6} stable"]
    for name, c in summary['cases'].items():
        lines.append(f"{name:28} {c['kind']:24} {c['expected_decision']:9} {','.join(str(d) for d in c['decisions']):30} "
                     f"{c['failures_caught']:>3}/{c['failures_total']:<3} {c['supported_flagged']:>2}/{c['supported_total']:<3} {c['unlabeled_flags']:>6} {c['stable']}")
    a = summary['aggregate']
    lines.append(f"failures caught {a['failures_caught']}/{a['failures_total']}; false flags {a['supported_flagged']}/{a['supported_total']}; "
                 f"decisions correct {a['decision_correct']}/{a['decision_total']}; errors {a['errors']}; bar_pass {summary['bar_pass']}")
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', action='append', required=True, help='case JSON file; repeatable')
    p.add_argument('--external', action='append', default=[], help='NAME=PATH for a transcript kept outside git; repeatable')
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--out', required=True)
    p.add_argument('--model', default=TESTED_MODEL)
    a = p.parse_args()
    if any('=' not in item for item in a.external):
        p.error('--external takes NAME=PATH')
    externals = dict(item.split('=', 1) for item in a.external)
    summary = evaluate(a.cases, a.out, lambda: claim_check.ClaudeCLIBackend(model=a.model), a.runs, a.jobs, externals, a.model)
    print(table(summary))
    print(f"model {a.model} ({summary['model_status']})")
    if summary['model_status'] == 'unvalidated':
        print(f'warning: checker results were validated only with {TESTED_MODEL}; treat these results as unvalidated', file=sys.stderr)
    return 0 if summary['bar_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
