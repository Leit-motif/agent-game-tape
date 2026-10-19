#!/usr/bin/env python3
"""Optional nlm adapter. Explicit upload, resumable remote ids, no automatic editorial acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from game_tape import fingerprint, load, run_lock as lock, save, validate


def rows(value, key):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if isinstance(value.get(key), list):
            return value[key]
        if value.get('id') or value.get('artifact_id'):
            return [value]
    return []


def python_for_cli(executable):
    resolved = Path(executable).resolve()
    for name in ('python', 'python3'):
        candidate = resolved.parent / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    try:
        with resolved.open('rb') as handle:
            first = handle.readline(4096).decode('utf-8', errors='replace').strip()
        interpreter = first[2:] if first.startswith('#!') else ''
        if interpreter.startswith('/') and 'python' in Path(interpreter).name.lower() and Path(interpreter).is_file():
            return interpreter
    except OSError:
        pass
    return None


class Publisher:
    def __init__(self, folder, executable, client_python=None, environment_entrypoint=None):
        self.folder = Path(folder).expanduser().resolve()
        self.manifest = load(self.folder / 'manifest.json')
        self.state_path = self.folder / 'notebooklm-state.json'
        self.state = load(self.state_path) if self.state_path.exists() else {}
        self.executable = executable or shutil.which('nlm')
        if not self.executable or not Path(self.executable).is_file():
            raise ValueError('nlm not found; install notebooklm-mcp-cli separately or pass --nlm /absolute/path')
        self.client_python = client_python or python_for_cli(self.executable)
        self.environment_entrypoint = environment_entrypoint
        self.payloads = {}
        for field, expected in [('source', 'upload/game-tape.md'), ('focus', 'upload/focus.txt')]:
            if self.manifest.get(field) != expected:
                raise ValueError('only the fixed narration and focus allowlist can be uploaded')
            original = self.folder / expected
            path = original.resolve()
            if not path.is_relative_to(self.folder) or original.is_symlink() or original.parent.is_symlink():
                raise ValueError('upload paths must stay inside the run')
            self.payloads[field] = path.read_bytes()
            digest = hashlib.sha256(self.payloads[field]).hexdigest()
            if digest != self.manifest.get(field + '_sha256'):
                raise ValueError(f'{field} changed after rendering; use a new run')
        for filename, key in [('evidence.json', 'evidence_sha256'), ('review.json', 'review_sha256')]:
            if fingerprint(load(self.folder / filename)) != self.manifest[key]:
                raise ValueError(f'{filename} changed after rendering')
        problems = validate(load(self.folder / 'evidence.json'), load(self.folder / 'review.json'))
        if problems:
            raise ValueError('; '.join(problems))
        self.digest = fingerprint(self.manifest)
        if self.state and self.state.get('manifest_sha256') != self.digest:
            raise ValueError('state belongs to different content; use a new run')

    def update(self, **fields):
        self.state.update(fields)
        self.state['manifest_sha256'] = self.digest
        save(self.state_path, self.state)

    def call(self, args, timeout=180, json_output=True):
        if args[0] in ('__single_send_check__', '__single_send_audio__'):
            if not self.client_python:
                raise ValueError('cannot locate the client Python; pass --client-python from the nlm environment. Stock CLI audio creation is not used because it may replay writes.')
            command = [self.client_python, str(Path(__file__).with_name('nlm_single_send.py'))]
            command += ['--check'] if args[0] == '__single_send_check__' else ['--request', args[1]]
            if self.environment_entrypoint:
                command += ['--environment-entrypoint', self.environment_entrypoint]
        else:
            command = [self.executable, *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            # Do not persist arbitrary CLI output: it may contain credentials or account data.
            raise ValueError(f'nlm failed (exit {result.returncode}) during {args[0]} {args[1] if len(args) > 1 else ""}. Raw output was not logged. Check the CLI directly; a transport/TLS failure is not necessarily expired login.')
        if not json_output:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise ValueError('nlm returned non-JSON output; remote effect may be uncertain. Reconcile before retrying.') from None

    def mutation(self, stage, args):
        if self.state.get('pending_mutation'):
            raise ValueError('an earlier remote write has an uncertain outcome. Inspect the notebook/CLI and reconcile recorded ids; do not clear pending_mutation and blindly retry.')
        self.update(pending_mutation=stage, generation_state='pending_remote_write')
        result = self.call(args, timeout=360)
        return result  # caller records returned id and clears pending only after checking it

    def start(self, allow_upload):
        if not allow_upload:
            raise ValueError('upload requires --allow-upload after privacy and semantic review; local prepare/render send nothing')
        if self.state.get('pending_mutation'):
            raise ValueError('uncertain remote write: reconcile before starting again')
        if self.state.get('artifact_id'):
            return self.state
        driver = self.call(['__single_send_check__'])
        self.call(['login', '--check'], json_output=False)
        self.update(client_version=self.call(['--version'], json_output=False).strip(), audio_driver=driver)
        if not self.state.get('notebook_id'):
            made = self.mutation('notebook_create', ['notebook', 'create', self.manifest['title'], '--json'])
            nb = made.get('notebook_id') or made.get('id') if isinstance(made, dict) else None
            if not isinstance(nb, str) or not nb.strip():
                raise ValueError('notebook response had no valid string id; reconcile remote result')
            self.update(notebook_id=nb, notebook_url=f'https://notebooklm.google.com/notebook/{nb}', pending_mutation=None)
        nb = self.state['notebook_id']
        if not self.state.get('source_id'):
            # CLI --file reads later. Seal the verified bytes, not the mutable renderer path.
            sealed = self.folder / 'sealed' / self.manifest['source_sha256'] / 'game-tape.md'
            sealed.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not sealed.resolve().is_relative_to(self.folder) or sealed.is_symlink() or sealed.parent.is_symlink():
                raise ValueError('sealed source must stay inside the run')
            try:
                with sealed.open('xb') as handle:
                    handle.write(self.payloads['source'])
                sealed.chmod(0o400)
            except FileExistsError:
                if sealed.read_bytes() != self.payloads['source']:
                    raise ValueError('sealed source differs from verified bytes')
            made = self.mutation('source_add', ['source', 'add', nb, '--file', str(sealed), '--wait', '--json'])
            source = made.get('source_id') or made.get('id') if isinstance(made, dict) else None
            if not isinstance(source, str) or not source.strip():
                raise ValueError('source response had no valid string id; reconcile remote result')
            self.update(source_id=source, pending_mutation=None)
        # Never adopt an unrelated artifact merely because it is audio. A reused notebook must be clean.
        artifacts = rows(self.call(['studio', 'status', nb, '--json']), 'artifacts')
        if any(str(a.get('type', '')).lower() == 'audio' for a in artifacts):
            raise ValueError('notebook already contains untracked audio; reconcile instead of adopting or duplicating it')
        focus = self.payloads['focus'].decode('utf-8').strip()
        request = {'notebook_id': nb, 'source_ids': [self.state['source_id']], 'format': self.manifest['format'],
                   'length': self.manifest['length'], 'language': self.manifest['language'], 'focus_prompt': focus, 'profile': None}
        request_path = self.folder / 'kickoff-request.json'
        save(request_path, request)
        self.update(kickoff_request_sha256=fingerprint(request))
        made = self.mutation('audio_create', ['__single_send_audio__', str(request_path)])
        aid = made.get('artifact_id') or made.get('id') if isinstance(made, dict) else None
        if not isinstance(aid, str) or not aid.strip():
            raise ValueError('audio response had no valid artifact id; reconcile remote result')
        self.update(artifact_id=aid, generation_state='generating', audio_quality='unverified', pending_mutation=None)
        return self.state

    def status(self, download=False):
        if not self.state.get('artifact_id'):
            raise ValueError('no tracked artifact; start or reconcile first')
        values = rows(self.call(['studio', 'status', self.state['notebook_id'], '--artifact-id', self.state['artifact_id'], '--json']), 'artifacts')
        artifact = next((a for a in values if str(a.get('id') or a.get('artifact_id')) == self.state['artifact_id']), None)
        if artifact is None:
            raise ValueError('tracked artifact absent from status; do not substitute another artifact')
        state = str(artifact.get('status', 'unknown')).lower()
        normalized = {'completed': 'generated', 'failed': 'failed', 'error': 'failed', 'cancelled': 'failed', 'canceled': 'failed'}.get(state, 'generating')
        submitted_focus = self.payloads['focus'].decode('utf-8').strip()
        recorded_focus = artifact.get('custom_instructions')
        focus_match = ' '.join(recorded_focus.split()) == ' '.join(submitted_focus.split()) if isinstance(recorded_focus, str) else None
        recorded_sources = artifact.get('source_ids')
        sources_match = set(recorded_sources) == {self.state.get('source_id')} if isinstance(recorded_sources, list) and all(isinstance(x, str) for x in recorded_sources) else None
        self.update(generation_state=normalized, remote_status=state, audio_quality='unverified',
                    focus_recorded_match=focus_match, source_selection_recorded_match=sources_match)
        if normalized == 'generated' and download:
            dest = self.folder / 'audio.m4a'
            self.call(['download', 'audio', self.state['notebook_id'], '--id', self.state['artifact_id'], '--output', str(dest)], timeout=360, json_output=False)
            if not dest.exists() or dest.stat().st_size < 1024:
                raise ValueError('download missing or implausibly small; generated is not downloaded')
            dest.chmod(0o600)
            self.update(download=str(dest), audio_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
        return self.state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'status', 'wait'])
    p.add_argument('run')
    p.add_argument('--nlm', help='absolute path to an nlm-compatible executable, not a shell command')
    p.add_argument('--client-python', help='Python executable in the pinned notebooklm-mcp-cli environment; auto-detected when possible')
    p.add_argument('--environment-entrypoint', help='optional existing guarded Python CLI wrapper to load host TLS/environment setup without running its main')
    p.add_argument('--allow-upload', action='store_true')
    p.add_argument('--download', action='store_true')
    p.add_argument('--max-minutes', type=float, default=25)
    a = p.parse_args()
    try:
        with lock(a.run):
            pub = Publisher(a.run, a.nlm, a.client_python, a.environment_entrypoint)
            if a.action == 'start':
                state = pub.start(a.allow_upload)
            else:
                deadline = time.monotonic() + max(0, a.max_minutes) * 60
                while True:
                    state = pub.status(a.download)
                    if a.action == 'status' or state['generation_state'] in ('generated', 'failed') or time.monotonic() >= deadline:
                        break
                    time.sleep(30)  # artifact job polling, not a reminder or follow-up timer
            print(json.dumps(state, indent=2))
            return 2 if state.get('generation_state') == 'failed' else 3 if a.action == 'wait' and state.get('generation_state') != 'generated' else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
