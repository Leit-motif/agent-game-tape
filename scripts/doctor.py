"""Check this machine is ready for Agent Game Tape. Read-only and offline unless --probe-model is given.

Required: Python 3.10+, the claude CLI and at least one transcript store. Everything else is reported but never
fails the check. The only write is ROOT/.doctor-ok.json, and only with --write-marker when required checks pass."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from models import TESTED_MODEL

REPO = Path(__file__).resolve().parent.parent
NLM_PIN = '0.15.6'
WALK_LIMIT = 200_000  # directory entries visited per store before the count is reported as a lower bound
SYMBOL = {'pass': '✓', 'fail': '✗', 'missing': '–', 'unknown': '?', 'skipped': '–'}
SAFE_ENV_DROP = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')  # mirrors claim_check.ClaudeCLIBackend


def add_arguments(parser):
    parser.add_argument('--probe-model', action='store_true',
                        help=f'make one tiny claude -p call to confirm {TESTED_MODEL} is reachable (uses network and a little quota)')
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON instead of the table')
    parser.add_argument('--root', help='private output root (default $GAME_TAPE_HOME or ~/.agent-game-tape)')
    parser.add_argument('--write-marker', action='store_true', help='write ROOT/.doctor-ok.json when the required checks pass')


def _root(args):
    return Path(args.root or os.environ.get('GAME_TAPE_HOME') or Path.home() / '.agent-game-tape').expanduser()


def _run(argv, timeout=15, **kwargs):
    """(returncode, stdout) or None when the command cannot run."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout.strip()


def _safe_env():
    env = {k: v for k, v in os.environ.items() if k not in SAFE_ENV_DROP}
    return dict(env, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', DISABLE_TELEMETRY='1')


def _check(id, label, kind, status, detail, step=None):
    return {'id': id, 'label': label, 'kind': kind, 'status': status, 'detail': detail, 'next_step': step}


def count_jsonl(folder, limit=WALK_LIMIT):
    """(count, complete): *.jsonl names under folder; files are never opened and symlinks are not followed."""
    count = seen = 0
    for _, dirs, files in os.walk(folder):
        seen += len(dirs) + len(files)
        count += sum(name.endswith('.jsonl') for name in files)
        if seen >= limit:
            return count, False
    return count, True


def check_python():
    version = platform.python_version()
    ok = sys.version_info >= (3, 10)
    return _check('python', 'Python 3.10+', 'required', 'pass' if ok else 'fail', version,
                  None if ok else 'Install Python 3.10 or newer: https://www.python.org/downloads/')


def check_claude(claude):
    if not claude:
        return _check('claude_cli', 'claude CLI', 'required', 'fail', 'not found on PATH',
                      'Install Claude Code: https://docs.claude.com/en/docs/claude-code'), None
    done = _run([claude, '--version'])
    version = done[1].splitlines()[0] if done and done[0] == 0 and done[1] else None
    return _check('claude_cli', 'claude CLI', 'required', 'pass', f"{version or 'version unknown'} ({claude})"), version


def check_login(claude):
    """`claude auth status` reads local state only; it prints login state and method, no secrets."""
    label, step = 'claude logged in', 'Run `claude`, then type /login'
    if not claude:
        return _check('claude_login', label, 'audio check', 'unknown', 'claude CLI not found', step)
    done = _run([claude, 'auth', 'status', '--json'], env=_safe_env())
    try:
        state = json.loads(done[1]) if done else None
    except ValueError:
        state = None
    if not isinstance(state, dict) or not isinstance(state.get('loggedIn'), bool):
        return _check('claude_login', label, 'audio check', 'unknown', 'could not read login state locally', step)
    if not state['loggedIn']:
        return _check('claude_login', label, 'audio check', 'fail', 'not logged in', step)
    detail = f"yes ({state.get('authMethod', 'unknown method')})"
    if any(os.environ.get(k) for k in SAFE_ENV_DROP):
        detail += '; ANTHROPIC_API_KEY/AUTH_TOKEN is set but game tape ignores it'
    return _check('claude_login', label, 'audio check', 'pass', detail)


def check_probe(claude, probe):
    label = f'model {TESTED_MODEL} reachable'
    if not probe:
        return _check('model_probe', label, 'audio check', 'skipped', 'not run (add --probe-model; one tiny call)')
    step = f'Check your Claude plan can use {TESTED_MODEL}: run `claude`, then /model'
    if not claude:
        return _check('model_probe', label, 'audio check', 'fail', 'claude CLI not found', step)
    argv = [claude, '-p', '--safe-mode', '--model', TESTED_MODEL, '--output-format', 'json', '--no-session-persistence',
            '--tools', '', '--strict-mcp-config', '--setting-sources', '', 'Reply with OK']
    with tempfile.TemporaryDirectory() as folder:
        done = _run(argv, timeout=90, cwd=folder, env=_safe_env())
    try:
        result = json.loads(done[1]) if done and done[0] == 0 else None
    except ValueError:
        result = None
    if isinstance(result, dict) and not result.get('is_error'):
        return _check('model_probe', label, 'audio check', 'pass', f"replied {str(result.get('result', ''))[:20]!r}")
    reason = 'timed out or could not run' if done is None else f'exit {done[0]}' if done[0] else 'error result'
    return _check('model_probe', label, 'audio check', 'fail', reason, step)


def check_stores():
    home = Path.home()
    stores = [('Claude Code', Path(os.environ.get('CLAUDE_CONFIG_DIR') or home / '.claude') / 'projects'),
              ('Codex', Path(os.environ.get('CODEX_HOME') or home / '.codex') / 'sessions')]
    found, parts = 0, []
    for name, folder in stores:
        if not folder.is_dir():
            parts.append(f'{name}: none')
            continue
        count, complete = count_jsonl(folder)
        found += count > 0
        parts.append(f"{name}: {count}{'' if complete else '+'} files")
    step = ('Use Claude Code or Codex once so a session is saved, or pass --claude/--codex folders to prepare. '
            'Looked in $CLAUDE_CONFIG_DIR or ~/.claude/projects and $CODEX_HOME or ~/.codex/sessions')
    return _check('transcripts', 'transcript store', 'required', 'pass' if found else 'fail', '; '.join(parts), None if found else step)


def check_skill():
    home = Path.home()
    links = [home / '.claude' / 'skills' / 'agent-game-tape', home / '.agents' / 'skills' / 'agent-game-tape']
    mine = [str(p) for p in links if p.exists() and p.resolve() == REPO]
    if mine:
        return _check('skill', 'skill installed', 'optional', 'pass', ', '.join(mine))
    other = [p for p in links if p.exists()]
    if other:
        link = other[0]
        step = (f'ln -sfn "{REPO}" "{link}"' if link.is_symlink() else f'Move {link} aside, then ln -s "{REPO}" "{link}"')
        return _check('skill', 'skill installed', 'optional', 'unknown',
                      f"points elsewhere: {', '.join(f'{p} -> {p.resolve()}' for p in other)}", step)
    return _check('skill', 'skill installed', 'optional', 'missing', 'no ~/.claude/skills or ~/.agents/skills link',
                  f'mkdir -p ~/.claude/skills && ln -s "{REPO}" ~/.claude/skills/agent-game-tape')


def check_nlm():
    nlm = shutil.which('nlm')
    install = f"pipx install 'notebooklm-mcp-cli=={NLM_PIN}', then nlm login"
    if not nlm:
        return [_check('nlm', 'nlm installed', 'optional', 'missing', 'not found (needed only for audio)', install),
                _check('nlm_login', 'nlm logged in', 'optional', 'missing', 'nlm not installed')]
    done = _run([nlm, '--version'])
    version = done[1].splitlines()[-1] if done and done[0] == 0 and done[1] else 'version unknown'
    pinned = NLM_PIN in version
    installed = _check('nlm', 'nlm installed', 'optional', 'pass' if pinned else 'unknown',
                       version if pinned else f'{version}; tested with {NLM_PIN}', None if pinned else install)
    # notebooklm-mcp-cli keeps credentials under $NOTEBOOKLM_MCP_CLI_PATH or ~/.notebooklm-mcp-cli; only names are checked.
    storage = Path(os.environ.get('NOTEBOOKLM_MCP_CLI_PATH') or Path.home() / '.notebooklm-mcp-cli')
    names = ('cookies.json', 'auth.json', 'credentials.enc')
    profiles = storage / 'profiles'
    try:
        saved = (storage / 'auth.json').exists() or (profiles.is_dir() and any(
            (p / n).exists() for p in profiles.iterdir() if p.is_dir() for n in names))
    except OSError:
        saved = None
    if saved:
        login = _check('nlm_login', 'nlm logged in', 'optional', 'pass', 'saved login found (session may expire; nlm login --check)')
    elif saved is None or storage.is_dir():
        login = _check('nlm_login', 'nlm logged in', 'optional', 'unknown', 'unknown; run nlm login --check', 'nlm login')
    else:
        login = _check('nlm_login', 'nlm logged in', 'optional', 'missing', 'no saved login', 'nlm login')
    return [installed, login]


def write_marker(root, claude_version, probe):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    marker = root / '.doctor-ok.json'
    body = {'schema': 'agent-game-tape/doctor-ok-v1', 'written_at': datetime.now(timezone.utc).isoformat(),
            'python': platform.python_version(), 'claude_version': claude_version, 'tested_model': TESTED_MODEL,
            'model_probe': probe}
    temp = marker.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(body, handle, indent=2)
        handle.write('\n')
    os.chmod(temp, 0o600)
    os.replace(temp, marker)
    return marker


def table(report):
    width = max(len(c['label']) for c in report['checks'])
    lines = [f"{SYMBOL[c['status']]} {c['label']:{width}}  {c['kind']:11}  {c['detail']}" for c in report['checks']]
    lines.append('')
    lines.append('Ready: required checks pass.' if report['ok'] else 'Not ready: a required check failed.')
    if report['marker']:
        lines.append(f"Wrote {report['marker']}")
    if report['next_steps']:
        lines += ['', 'Next steps:'] + [f'  {i}. {step}' for i, step in enumerate(report['next_steps'], 1)]
    lines += ['', '✓ ok  ✗ failed  – optional, missing or not run  ? unknown. Only required checks set the exit code;',
              "'audio check' items are needed later to check the finished audio."]
    return '\n'.join(lines)


def run(args) -> int:
    root = _root(args)
    claude = shutil.which('claude')
    cli, claude_version = check_claude(claude)
    checks = [check_python(), cli, check_login(claude), check_probe(claude, args.probe_model), check_stores(),
              check_skill(), *check_nlm()]
    ok = all(c['status'] == 'pass' for c in checks if c['kind'] == 'required')
    steps = [c['next_step'] for c in checks if c['next_step']]
    marker = None
    if args.write_marker and ok:
        probe = next(c['status'] for c in checks if c['id'] == 'model_probe')
        marker = str(write_marker(root, claude_version, 'not run' if probe == 'skipped' else probe))
    elif args.write_marker:
        steps.append('Fix the required items above, then rerun with --write-marker (no marker was written)')
    elif ok and not (root / '.doctor-ok.json').exists():
        steps.append(f'python3 "{REPO / "scripts" / "game_tape.py"}" doctor --write-marker')
    report = {'schema': 'agent-game-tape/doctor-v1', 'ok': ok, 'root': str(root), 'tested_model': TESTED_MODEL,
              'checks': checks, 'next_steps': steps, 'marker': marker}
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else table(report))
    return 0 if ok else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    raise SystemExit(run(parser.parse_args()))
