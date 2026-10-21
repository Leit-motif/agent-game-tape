#!/usr/bin/env python3
"""Evidence-backed game tape: collect locally, validate a review, render narration, audit audio."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from collect import collect

ROOT = Path(__file__).resolve().parent.parent


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextlib.contextmanager
def run_lock(folder):
    path = Path(folder).expanduser().resolve() / '.publisher.lock'
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError('another publisher or renderer holds this run (or a crashed lock remains). Check the recorded PID before removing the lock.') from None
    try:
        (path / 'pid').write_text(str(os.getpid()))
        yield
    finally:
        (path / 'pid').unlink(missing_ok=True)
        path.rmdir()


def day_window(day, timezone_name, hour=0):
    zone = ZoneInfo(timezone_name)
    chosen = datetime.now(zone).date() - timedelta(days=1) if day == "yesterday" else date.fromisoformat(day)
    return (datetime.combine(chosen, time(hour), zone), datetime.combine(chosen + timedelta(days=1), time(hour), zone))


def prepare(args):
    start, end = day_window(args.day, args.timezone, args.day_start_hour)
    inputs = []
    if args.claude is not None:
        inputs += [("claude-code", Path(p)) for p in args.claude]
    if args.codex is not None:
        inputs += [("codex", Path(p)) for p in args.codex]
    inputs += [("openclaw", Path(p)) for p in args.openclaw]
    if not inputs:
        inputs = [("claude-code", Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "projects"),
                  ("codex", Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions")]
    limits = load(args.scan_limits) if args.scan_limits else None
    events, coverage = collect(inputs, start - timedelta(hours=args.lookback_hours), end, limits=limits)
    for event in events:
        event['in_window'] = start <= datetime.fromisoformat(event['timestamp']) < end
    folder = Path(args.out).expanduser().resolve()
    if folder.exists():
        raise ValueError("output folder already exists; choose a new folder (no silent overwrite)")
    rules = load(args.rules)
    if not isinstance(rules, dict) or not rules or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in rules.items()):
        raise ValueError("rules must be a nonempty JSON object mapping stable ids to rule text")
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    bundle = {"schema": "agent-game-tape/evidence-v1", "window": [start.isoformat(), end.isoformat()],
              "timezone": args.timezone, "rules": rules, "rules_sha256": fingerprint(rules),
              "rule_source": str(Path(args.rules).expanduser().resolve()),
              "rules_snapshot_at": datetime.now(timezone.utc).isoformat(),
              "previous_review": load(args.previous_review) if args.previous_review else None,
              "coverage": coverage, "events": events,
              "limits": ["Only the explicitly selected local files are visible; absence is not proof nothing happened.",
                         "Recognizable tokens are redacted, but arbitrary private data and unknown credentials may remain.",
                         "Human attribution is inferred from harness records after known system/delegation exclusions.",
                         "Tool outputs and assistant claims need semantic review; timestamps measure elapsed time, not time wasted."]}
    save(folder / "evidence.json", bundle)
    lines = ["# Local evidence — not for upload", "", f"Window: {start.isoformat()} to {end.isoformat()} (end excluded)", "", "## Coverage", "", "```json", json.dumps(coverage, indent=2), "```", "", "## Rules", ""]
    lines += [f"- **{key}**: {value}" for key, value in rules.items()]
    for event in events:
        lines += ["", f"## {event['id']}", f"{event['timestamp']} | {event['role']} | {event['source']}:{event['line']}", "", event['text']]
    write(folder / "evidence.md", "\n".join(lines) + "\n")
    print(json.dumps({"out": str(folder), "events": len(events), "human_events": sum(e['role'] == 'human' for e in events), "coverage": coverage, "next": "Read evidence.md, then write review.json using references/review-contract.md"}))


def validate(bundle, review):
    problems = []
    events = {e['id']: e for e in bundle['events']}
    positions = {e['id']: i for i, e in enumerate(bundle['events'])}
    if len(events) != len(bundle['events']):
        return ['evidence event ids must be unique']
    if not isinstance(review, dict):
        return ["review must be an object"]
    moments = review.get('moments')
    if not isinstance(moments, list):
        return ["moments must be an array"]
    if review.get('status') in ('quiet', 'insufficient_evidence'):
        if moments or not isinstance(review.get('reason'), str) or not review['reason'].strip():
            return ["abstention needs a reason and no moments"]
        if review['status'] == 'quiet' and not any(c.get('available') and c.get('events', 0) for c in bundle['coverage']):
            return ["missing collection is insufficient_evidence, not a quiet day"]
        return []
    if review.get('status') != 'reviewed':
        problems.append("status must be reviewed, quiet, or insufficient_evidence")
    if not 1 <= len(moments) <= 5:
        problems.append("select 1–5 consequential moments; quiet is valid, padding is not")
    used = set()
    streams = {}
    for n, moment in enumerate(moments, 1):
        prefix = f"moment {n}"
        if not isinstance(moment, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        for field in ('title', 'workstream', 'human_event', 'human_quote', 'action', 'outcome', 'lesson', 'rule_id'):
            if not isinstance(moment.get(field), str) or not moment[field].strip():
                problems.append(f"{prefix}: missing nonempty {field}")
        human = events.get(moment.get('human_event'))
        quote = moment.get('human_quote', '')
        if not human or human['role'] != 'human':
            problems.append(f"{prefix}: human_event must identify a human event")
        elif human.get('in_window') is False:
            problems.append(f"{prefix}: context-only human event is outside the review window")
        elif not isinstance(quote, str) or not quote or quote not in human['text']:
            problems.append(f"{prefix}: human_quote is not verbatim in the cited human event")
        elif len(quote.split()) > 40:
            problems.append(f"{prefix}: use at most 40 quoted words")
        if moment.get('human_event') in used:
            problems.append(f"{prefix}: duplicate steering event")
        used.add(moment.get('human_event'))
        streams[moment.get('workstream', '')] = streams.get(moment.get('workstream', ''), 0) + 1
        if moment.get('rule_id') not in bundle['rules']:
            problems.append(f"{prefix}: unknown rule_id")
        if moment.get('verdict') not in ('good call', 'costly call', 'mixed', 'agent failure', 'system failure', 'unclear'):
            problems.append(f"{prefix}: invalid verdict")
        if moment.get('responsibility') not in ('human', 'agent', 'system', 'shared', 'unknown'):
            problems.append(f"{prefix}: responsibility must separate human steering from agent/system execution")
        if not isinstance(moment.get('causal_basis'), str) or not moment['causal_basis'].strip():
            problems.append(f"{prefix}: causal_basis must state evidence or that attribution is unknown")
        if moment.get('assurance') not in ('verified', 'agent_report', 'unknown'):
            problems.append(f"{prefix}: invalid assurance")
        refs = moment.get('evidence')
        if not isinstance(refs, list) or not refs:
            problems.append(f"{prefix}: evidence needs event/quote objects")
            refs = []
        tool_evidence = False
        for ref in refs:
            if not isinstance(ref, dict):
                problems.append(f"{prefix}: evidence must be an object")
                continue
            event = events.get(ref.get('event'))
            span = ref.get('quote')
            if not event or not isinstance(span, str) or not span or span not in event['text']:
                problems.append(f"{prefix}: evidence quote missing from original event")
                continue
            if human and (event['session'] != human['session'] or positions[event['id']] <= positions[human['id']] or datetime.fromisoformat(event['timestamp']) < datetime.fromisoformat(human['timestamp'])):
                problems.append(f"{prefix}: use subsequent same-session evidence (cross-session claims require manual reconciliation)")
            tool_evidence |= event['role'] == 'tool'
        if moment.get('assurance') == 'verified' and not tool_evidence:
            problems.append(f"{prefix}: verified needs an actual tool-result quote, not a command or assistant claim")
    if any(count > 2 for count in streams.values()):
        problems.append("at most two moments per workstream")
    experiment = review.get('experiment')
    if experiment is None:
        if not isinstance(review.get('no_experiment_reason'), str) or not review['no_experiment_reason'].strip():
            problems.append("provide one experiment or a no_experiment_reason; never manufacture a correction")
    elif not isinstance(experiment, dict):
        problems.append("experiment must be one object or null")
    else:
        for key in ('change', 'next_check'):
            if not isinstance(experiment.get(key), str) or not experiment[key].strip():
                problems.append(f"experiment needs {key}")
        linked = experiment.get('moment_numbers')
        if not isinstance(linked, list) or not linked or any(type(n) is not int or not 1 <= n <= len(moments) for n in linked):
            problems.append("experiment must link to valid moment_numbers")
    if not isinstance(review.get('blind_spots'), list) or not review['blind_spots'] or any(not isinstance(x, str) or not x.strip() for x in review.get('blind_spots', [])):
        problems.append("blind_spots must be a nonempty array of coverage limitations")
    if bundle.get('previous_review') is not None:
        followup = review.get('previous_followup')
        if not isinstance(followup, dict) or followup.get('status') not in ('applied', 'not_applied', 'inconclusive', 'not_visible'):
            problems.append('previous_review requires a previous_followup status')
        else:
            refs = followup.get('evidence')
            if not isinstance(refs, list) or any(ref not in events for ref in refs):
                problems.append('previous_followup evidence must reference collected event ids')
            elif followup['status'] in ('applied', 'not_applied') and not refs:
                problems.append('an applied/not_applied conclusion needs evidence; absence is not_visible')
            if not isinstance(followup.get('summary'), str) or not followup['summary'].strip():
                problems.append('previous_followup needs a summary')
    return problems


def narration(bundle, review, style='prose'):
    parts = ['# Game tape', '']
    for n, m in enumerate(review['moments'], 1):
        event = next(e for e in bundle['events'] if e['id'] == m['human_event'])
        when = datetime.fromisoformat(event['timestamp']).astimezone(ZoneInfo(bundle['timezone'])).strftime('%H:%M')
        parts += [f"## {m['title']}", '']
        if style == 'fielded':
            parts += [f"When: {when}", f"Your call: “{m['human_quote']}”", f"What happened: {m['action']}", f"Cost or win: {m['outcome']}", f"The rule: {bundle['rules'][m['rule_id']]}", f"Verdict: {m['verdict']}", f"Causal basis: {m['causal_basis']}", f"The lesson: {m['lesson']}", '']
        else:
            verdict = {'good call': 'This was a good call.', 'costly call': 'This was a costly call.', 'mixed': 'The outcome was mixed.', 'agent failure': 'This was an agent execution failure.', 'system failure': 'This was a system failure.', 'unclear': 'The outcome remains unclear.'}[m['verdict']]
            parts += [f"At {when}, you said, “{m['human_quote']}” {m['action']}", '', m['outcome'], '', f"{verdict} {m['causal_basis']}", '', f"{bundle['rules'][m['rule_id']]} {m['lesson']}", '']
    if review.get('experiment'):
        parts += ['## One experiment for next time', '', review['experiment']['change'], '', review['experiment']['next_check'], '']
    else:
        parts += ['## Keep the useful move', '', review['no_experiment_reason'], '']
    return '\n'.join(parts)


def build_focus(review, audio_format='deep_dive'):
    name = 'audio-focus-brief.txt' if audio_format == 'brief' else 'audio-focus.txt'
    template = (ROOT / 'references' / name).read_text().strip()
    if '{{closing}}' not in template:
        raise ValueError('audio focus template must contain {{closing}}')
    closing = ('Close with the single experiment for next time and its observable check.' if review.get('experiment')
               else 'Close by reinforcing the supplied useful move to keep.')
    return template.replace('{{closing}}', closing)


def render(args):
    with run_lock(args.run):
        return _render(args)


def _render(args):
    folder = Path(args.run).expanduser().resolve()
    bundle, review = load(folder / 'evidence.json'), load(folder / 'review.json')
    problems = validate(bundle, review)
    if problems:
        print(json.dumps({'ok': False, 'problems': problems}, indent=2))
        return 1
    if review['status'] in ('quiet', 'insufficient_evidence'):
        print(json.dumps({'ok': True, 'status': review['status'], 'reason': review['reason'], 'upload': None}))
        return 0
    if args.format == 'brief' and len(review['moments']) > 2:
        raise ValueError('Brief accepts at most two selected moments; revise the review rather than truncate it')
    text = narration(bundle, review, args.style)
    if len(text.split()) > args.max_words:
        raise ValueError(f"narration has {len(text.split())} words; maximum {args.max_words}. Select less, do not truncate facts.")
    source = folder / 'upload' / 'game-tape.md'
    if (folder / 'notebooklm-state.json').exists():
        raise ValueError('run already has NotebookLM state; use a new run folder to change sources')
    write(source, text)
    focus = build_focus(review, args.format)
    write(folder / 'upload' / 'focus.txt', focus + '\n')
    manifest = {'schema': 'agent-game-tape/upload-v1', 'title': f"Game tape {bundle['window'][0][:10]}",
                'source': 'upload/game-tape.md', 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'focus': 'upload/focus.txt', 'focus_sha256': hashlib.sha256((focus + '\n').encode()).hexdigest(),
                'evidence_sha256': fingerprint(bundle), 'review_sha256': fingerprint(review), 'style': args.style,
                'format': args.format, 'length': args.length, 'language': args.language,
                'semantic_review': 'required', 'audio_quality': 'unverified'}
    save(folder / 'manifest.json', manifest)
    report = text + '\n## Local-only evidence and limits\n\n' + '\n'.join('- ' + item for item in review['blind_spots']) + '\n\n'
    for i, moment in enumerate(review['moments'], 1):
        report += f"- Moment {i}: {moment['human_event']} → " + ', '.join(ref['event'] for ref in moment['evidence']) + f"; {moment['rule_id']}; {moment['assurance']}\n"
    write(folder / 'report.md', report)
    print(json.dumps({'ok': True, 'manifest': str(folder / 'manifest.json'), 'words': len(text.split()), 'next': 'Semantically review evidence support, source privacy, and narration before upload.'}))
    return 0


QA_PATTERNS = {
    'source_recital': r'(?i)according to the (?:sources|documents)|stack of sources|the documents say|we (?:collected|filtered|gathered) your',
    'field_readout': r'(?i)the (?:verdict|lesson|rule|cost or win) (?:field|line)|your call colon|what happened colon',
    'listener_third_person': r'(?i)\bthe user\b|our (?:listener|subject)',
    'motive': r'(?i)\b(?:lied|lying|lazy|dishonest|pretended)\b',
    'instruction_recital': r'(?i)ground rules|we (?:do not|don.t|are not going to) (?:guess|speculate)|never mention goals',
}


def audit_audio(args):
    path = Path(args.transcript).resolve()
    raw = path.read_text(encoding='utf-8')
    transcript = json.loads(raw) if path.suffix == '.json' else None
    segments = transcript.get('segments', []) if isinstance(transcript, dict) else []
    text = transcript.get('text', '') if isinstance(transcript, dict) else raw
    flags = {name: [match.group(0) for match in re.finditer(pattern, text)] for name, pattern in QA_PATTERNS.items()}
    flags = {k: v for k, v in flags.items() if v}
    if segments:
        duration = max(float(s.get('end', 0)) for s in segments)
    else:
        duration = None
    result = {'schema': 'agent-game-tape/audio-audit-v1', 'transcript_sha256': hashlib.sha256(raw.encode()).hexdigest(),
              'transcript_words': len(text.split()), 'last_transcript_second': duration,
              'declared_audio_seconds': args.duration, 'flags': flags,
              'coverage_plausible': bool(duration and args.duration and duration >= 0.95 * args.duration),
              'editorial_acceptance': 'pending_semantic_review',
              'limits': 'Pattern hits are triage, not semantic verdicts. A clean scan does not prove accuracy, completeness, or usable coaching.'}
    save(args.out, result)
    print(json.dumps(result, indent=2))
    return 0


def check_narration(args):
    import claim_check  # lazy: claim_check imports this module
    if args.run:
        folder = Path(args.run).expanduser().resolve()
        evidence, review = folder / 'evidence.json', folder / 'review.json'
    elif args.evidence and args.review:
        evidence, review = Path(args.evidence), Path(args.review)
    else:
        raise ValueError('give --run, or both --evidence and --review')
    bundle, review = load(evidence), load(review)
    problems = validate(bundle, review)
    if problems or review['status'] != 'reviewed':
        raise ValueError('check-narration needs a valid reviewed review.json: ' + '; '.join(problems or [review['status']]))
    receipt = claim_check.check(args.transcript, bundle, review, claim_check.ClaudeCLIBackend(model=args.model))
    save(args.out, receipt)
    counts = {}
    for claim in receipt['claims']:
        counts[claim['label']] = counts.get(claim['label'], 0) + 1
    print(json.dumps({'decision': receipt['decision'], 'reasons': receipt['reasons'], 'labels': counts,
                      'opening_ok': (receipt['opening'] or {}).get('ok'), 'out': str(Path(args.out).resolve())}, indent=2))
    return 0 if receipt['decision'] == 'accepted' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='read selected local transcripts; no network')
    p.add_argument('--day', default='yesterday')
    p.add_argument('--timezone', default='UTC')
    p.add_argument('--day-start-hour', type=int, choices=range(24), default=0)
    p.add_argument('--claude', action='append', help='Claude projects folder or JSONL; repeatable. Explicit roots disable auto-discovery.')
    p.add_argument('--codex', action='append', help='Codex sessions folder or JSONL; repeatable')
    p.add_argument('--openclaw', action='append', default=[], help='explicit exported JSONL folder/file; no live-store assumption')
    p.add_argument('--rules', default=str(ROOT / 'references' / 'rules.json'))
    p.add_argument('--lookback-hours', type=int, choices=range(0, 169), default=24, help='prior context, never eligible as a new moment')
    p.add_argument('--scan-limits', help='optional JSON file of positive max_* collector limits; effective budgets are retained in coverage')
    p.add_argument('--previous-review', help='optional prior review.json to check whether its experiment was actually tried')
    p.add_argument('--out', required=True)
    p.set_defaults(fn=prepare)
    p = sub.add_parser('render', help='validate structured review and prepare one narration source')
    p.add_argument('run')
    p.add_argument('--style', choices=['prose', 'fielded'], default='prose', help='fielded is the legacy comparison arm')
    p.add_argument('--max-words', type=int, default=1600)
    p.add_argument('--format', choices=['deep_dive', 'brief', 'critique', 'debate'], default='deep_dive')
    p.add_argument('--length', choices=['short', 'default', 'long'], default='default')
    p.add_argument('--language', default='en')
    p.set_defaults(fn=render)
    p = sub.add_parser('audit-audio', help='triage a complete local ASR transcript, never auto-accept')
    p.add_argument('--transcript', required=True)
    p.add_argument('--duration', type=float, required=True, help='actual duration from ffprobe, seconds')
    p.add_argument('--out', required=True)
    p.set_defaults(fn=audit_audio)
    p = sub.add_parser('check-narration', help='claim-level check of an ASR transcript against evidence and review; never listens')
    p.add_argument('--run', help='run folder with evidence.json and review.json')
    p.add_argument('--evidence')
    p.add_argument('--review')
    p.add_argument('--transcript', required=True, help='whisper JSON with segments')
    p.add_argument('--out', required=True)
    p.add_argument('--model', default='claude-opus-5-5')
    p.set_defaults(fn=check_narration)
    args = parser.parse_args()
    try:
        return args.fn(args) or 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
