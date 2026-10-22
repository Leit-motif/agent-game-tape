#!/usr/bin/env python3
"""Agent Game Tape: review a day of your local agent sessions like game tape and get an evidence-backed
coaching report.

Steps: doctor (check setup), prepare (read local transcripts), render (validate your review, write the local
report and the optional audio upload), then audit-audio and check-narration if you made audio. Collection and
render are offline. check-narration sends the transcript, evidence and review to Anthropic through your Claude
CLI login (claude -p). Audio upload happens only with notebooklm.py start --allow-upload."""
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
from models import TESTED_MODEL, model_status

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
    if audio_format == 'brief' and '{{opening}}' not in template:
        raise ValueError('Brief focus template must contain {{opening}}')
    closing = ('Close with the single experiment for next time and its observable check.' if review.get('experiment')
               else 'Close by reinforcing the supplied useful move to keep.')
    # Naming the literal first sentence cured Brief's generic opening in 5/5 episodes (references/narration-climb.md).
    moments = review.get('moments') or []
    opening = (f"Open with this first sentence, word for word: You said, “{moments[0]['human_quote']}” "
               'Then cover the selected decisions in that order.' if moments
               else 'Begin with the first decision in Game tape and cover the selected decisions in that order.')
    return template.replace('{{opening}}', opening).replace('{{closing}}', closing)


UPLOAD_SCHEMA = 'agent-game-tape/upload-v2'


def source_name(index, path):
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', Path(path).name).lstrip('._') or 'source'
    return f'{index:02d}-{name}'


def private_digests(folder, bundle):
    protected = {folder / name for name in ('evidence.json', 'evidence.md', 'review.json')}
    if bundle.get('rule_source'):
        protected.add(Path(bundle['rule_source']).expanduser().resolve())
    digests = {hashlib.sha256(path.read_bytes()).hexdigest() for path in protected if path.is_file()}
    # Best effort for rules copies: common JSON spellings of the rules object, not every possible reformatting.
    for text in (json.dumps(bundle.get('rules')), json.dumps(bundle.get('rules'), indent=2, ensure_ascii=False)):
        digests |= {hashlib.sha256(t.encode()).hexdigest() for t in (text, text + '\n')}
    return protected, digests


def read_shareable(folder, private, entry, label):
    """Bytes of a caller file that may leave the machine; refuse private run files, links, folders and empty files."""
    protected, digests = private
    original = Path(entry).expanduser()
    if original.is_symlink():
        raise ValueError(f'{label} {entry} is a symlink; pass the real file')
    path = original.resolve()
    if not path.is_file():
        raise ValueError(f'{label} {entry} is not a regular file')
    if path in protected:
        raise ValueError(f'{label} {entry} is the run\'s raw evidence, review or rules; it never leaves this machine')
    if path.is_relative_to(folder) and not path.is_relative_to(folder / 'upload'):
        raise ValueError(f'{label} {entry} is inside the run folder; only files under upload/ may be sent')
    data = path.read_bytes()
    if not data.strip():
        raise ValueError(f'{label} {entry} is empty')
    if hashlib.sha256(data).hexdigest() in digests:
        raise ValueError(f'{label} {entry} is a copy of the run\'s raw evidence, review or rules')
    return path.name, data


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
    if (folder / 'notebooklm-state.json').exists():
        raise ValueError('run already has Gemini Notebook state; use a new run folder to change sources')
    if getattr(args, 'focus', None) is not None and getattr(args, 'focus_file', None):
        raise ValueError('give --focus or --focus-file, not both')
    private = private_digests(folder, bundle)
    if getattr(args, 'focus_file', None):
        focus, origin = read_shareable(folder, private, args.focus_file, 'focus file')[1].decode('utf-8').strip(), 'caller'
    elif getattr(args, 'focus', None) is not None:
        focus, origin = args.focus.strip(), 'caller'
    else:
        focus, origin = build_focus(review, args.format), 'bundled'
    if not focus:
        raise ValueError('focus prompt is empty')
    if any(hashlib.sha256(t.encode()).hexdigest() in private[1] for t in (focus, focus + '\n')):
        raise ValueError('focus is a copy of the run\'s raw evidence, review or rules')
    sources, copies, seen = [], [], set()
    for index, entry in enumerate(getattr(args, 'source', None) or ['narration'], 1):
        if entry == 'narration':
            relative, data = 'upload/game-tape.md', text.encode()
        else:
            name, data = read_shareable(folder, private, entry, 'source')
            relative = f'upload/sources/{source_name(index, name)}'
            copies.append((folder / relative, data))
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            raise ValueError(f'duplicate source content ({relative}); pass each source once')
        seen.add(digest)
        sources.append({'path': relative, 'sha256': digest})
    extra = folder / 'upload' / 'sources'
    if extra.is_symlink() or (extra.exists() and not extra.is_dir()):
        raise ValueError('upload/sources must be a real folder')
    # Everything is validated; only now replace the previous upload.
    write(folder / 'upload' / 'game-tape.md', text)
    write(folder / 'upload' / 'focus.txt', focus + '\n')
    if extra.exists():
        for old in extra.iterdir():
            old.unlink()
    for path, data in copies:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        path.chmod(0o600)
    manifest = {'schema': UPLOAD_SCHEMA, 'title': f"Game tape {bundle['window'][0][:10]}", 'sources': sources,
                'focus': 'upload/focus.txt', 'focus_sha256': hashlib.sha256((focus + '\n').encode()).hexdigest(),
                'focus_origin': origin, 'web_research': 'off',
                'evidence_sha256': fingerprint(bundle), 'review_sha256': fingerprint(review), 'style': args.style,
                'format': args.format, 'length': args.length, 'language': args.language,
                'semantic_review': 'required', 'audio_quality': 'unverified'}
    save(folder / 'manifest.json', manifest)
    report = text + '\n## Local-only evidence and limits\n\n' + '\n'.join('- ' + item for item in review['blind_spots']) + '\n\n'
    for i, moment in enumerate(review['moments'], 1):
        report += f"- Moment {i}: {moment['human_event']} → " + ', '.join(ref['event'] for ref in moment['evidence']) + f"; {moment['rule_id']}; {moment['assurance']}\n"
    write(folder / 'report.md', report)
    print(json.dumps({'ok': True, 'manifest': str(folder / 'manifest.json'), 'words': len(text.split()),
                      'sources': [s['path'] for s in sources], 'focus_origin': origin,
                      'next': 'Semantically review evidence support, source privacy, and narration before upload.'}))
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
    status = model_status(args.model)
    print(json.dumps({'decision': receipt['decision'], 'reasons': receipt['reasons'], 'labels': counts,
                      'opening_ok': (receipt['opening'] or {}).get('ok'), 'model': args.model, 'model_status': status,
                      'out': str(Path(args.out).resolve())}, indent=2))
    if status == 'unvalidated':
        print(f'warning: checker results were validated only with {TESTED_MODEL}; treat this receipt as unvalidated', file=sys.stderr)
    return 0 if receipt['decision'] == 'accepted' else 1


def add_doctor(sub):
    import doctor  # owned by scripts/doctor.py; imported here so the other commands never depend on it
    p = sub.add_parser('doctor', help='check this machine is ready: Python, claude CLI, transcripts, optional nlm. Read-only.',
                       description='Check setup before the first review. Read-only. Makes no network call unless you ask it to probe the model.')
    doctor.add_arguments(p)
    p.set_defaults(fn=doctor.run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')
    add_doctor(sub)
    p = sub.add_parser('prepare', help='read selected local transcripts for one day into a private run folder; no network')
    p.add_argument('--day', default='yesterday', help='YYYY-MM-DD or yesterday (default)')
    p.add_argument('--timezone', default='UTC', help='IANA zone for the day boundaries, e.g. America/Chicago')
    p.add_argument('--day-start-hour', type=int, choices=range(24), default=0, metavar='HOUR', help='hour the day starts (0-23)')
    p.add_argument('--claude', action='append', help='Claude Code projects folder or JSONL file; repeatable. Giving any folder turns off auto-discovery.')
    p.add_argument('--codex', action='append', help='Codex sessions folder or JSONL file; repeatable')
    p.add_argument('--openclaw', action='append', default=[], help='exported OpenClaw JSONL folder or file; repeatable')
    p.add_argument('--rules', default=str(ROOT / 'references' / 'rules.json'), help='JSON object of your working rules (default: bundled rules.json)')
    p.add_argument('--lookback-hours', type=int, choices=range(0, 169), default=24, metavar='HOURS', help='earlier context to include (0-168); never picked as a new moment')
    p.add_argument('--scan-limits', help='optional JSON file of collector limits; the limits used are recorded in coverage')
    p.add_argument('--previous-review', help='earlier review.json, to check whether its experiment was tried')
    p.add_argument('--out', required=True, help='new run folder to create')
    p.set_defaults(fn=prepare)
    p = sub.add_parser('render', help='validate review.json and build the narration, focus prompt and upload manifest',
                       description='Validate review.json and build the upload. These controls mirror the Customize Audio Overview dialog. '
                                   'Web research is always off: outside facts carry no evidence ids, so the narration could no longer be checked against your sessions.')
    p.add_argument('run', help='run folder made by prepare, containing review.json')
    p.add_argument('--style', choices=['prose', 'fielded'], default='prose', help='narration layout; fielded is a field-labelled layout kept for comparison')
    p.add_argument('--max-words', type=int, default=1600, help='refuse narration longer than this (default 1600)')
    p.add_argument('--format', choices=['deep_dive', 'brief', 'critique', 'debate'], default='deep_dive', help='audio format (default deep_dive); brief allows at most two moments')
    p.add_argument('--length', choices=['short', 'default', 'long'], default='default', help='audio length (default: default)')
    p.add_argument('--language', default='en', help='language code, e.g. en, es, ja (default en)')
    p.add_argument('--source', action='append', metavar='PATH', help='file to upload; repeatable. The word narration means the rendered upload/game-tape.md (default: narration only)')
    focus = p.add_mutually_exclusive_group()
    focus.add_argument('--focus', metavar='TEXT', help='your own focus prompt (default: bundled template)')
    focus.add_argument('--focus-file', metavar='PATH', help='read the focus prompt from a file')
    p.set_defaults(fn=render)
    p = sub.add_parser('audit-audio', help='scan a full local transcript of the audio for known problems; never accepts audio on its own')
    p.add_argument('--transcript', required=True, help='whisper JSON or plain-text transcript')
    p.add_argument('--duration', type=float, required=True, help='actual audio duration in seconds, from ffprobe')
    p.add_argument('--out', required=True, help='where to write the audit JSON')
    p.set_defaults(fn=audit_audio)
    p = sub.add_parser('check-narration', help='check each claim in the audio transcript against your evidence and review')
    p.add_argument('--run', help='run folder with evidence.json and review.json')
    p.add_argument('--evidence', help='evidence.json (instead of --run)')
    p.add_argument('--review', help='review.json (instead of --run)')
    p.add_argument('--transcript', required=True, help='whisper JSON with segments')
    p.add_argument('--out', required=True, help='where to write the receipt JSON')
    p.add_argument('--model', default=TESTED_MODEL, help=f'checker model (default: the tested model, {TESTED_MODEL})')
    p.set_defaults(fn=check_narration)
    args = parser.parse_args(argv)
    try:
        return args.fn(args) or 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
