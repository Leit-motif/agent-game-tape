#!/usr/bin/env python3
"""Single-dispatch AUDIO kickoff adapter; never retry an uncertain mutation.

Importing this module requires only the standard library. The caller owns a
persistent pending intent and reconciliation; this is not server idempotency.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import inspect
import io
import json
import re
import runpy
import sys
import threading
from pathlib import Path
from types import MethodType


_COMMON = {
    'studio': '369b05ad6c0c31723f47e02d73de63ab87c201c94edffcded91d48435020e653',
    'retry': 'fa7f643e8ca79a775954ff1538c9224ae4c181057d7c37611ac1e68c6d7f5efe',
}
# v0.15.6 tag d6d427cd0ef8519843a46c447e3572b4c08c7081, matching PyPI sdist.
# 0.15.1 is the separately fingerprinted installed distribution, not a version range.
_PINS = {
    '0.15.1': dict(_COMMON, base='3201a38af7590fa8f72adff534040961abd266e1b7db90fe4cd73c43a5b8d34d'),
    '0.15.6': dict(_COMMON, base='ceb514b20f63fbcaa01a026f46dc5f87a29ee7390afc3d98222178cf0b6290e7'),
}
_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()
_ABSENT = object()
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


class SingleSendError(ValueError):
    """A sanitized error safe for the CLI's JSON error field."""


class UnsupportedClientError(SingleSendError):
    """No dispatch is allowed with an unaudited client or transport."""


class InvalidAudioRequest(SingleSendError):
    """Request rejected before dispatch."""


class AudioOutcomeUnknownError(SingleSendError):
    """A dispatch was attempted; reconcile, never automatically resend."""


def _verify_package():
    """Check both distribution provenance and the modules actually imported."""
    try:
        distribution = importlib.metadata.distribution('notebooklm-mcp-cli')
        expected = _PINS.get(distribution.version)
        if expected is None:
            raise UnsupportedClientError('Unsupported NotebookLM client version; no audio was sent.')
        from notebooklm_tools.core import base, retry, studio
        for name, module in (('base', base), ('retry', retry), ('studio', studio)):
            path = Path(module.__file__).resolve()
            installed = Path(distribution.locate_file('notebooklm_tools/core/' + name + '.py')).resolve()
            if path != installed or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
                raise UnsupportedClientError('NotebookLM source fingerprint mismatch; no audio was sent.')
        return distribution.version, base, studio
    except SingleSendError:
        raise
    except Exception:
        raise UnsupportedClientError('Pinned NotebookLM client is unavailable; no audio was sent.') from None


def _verify_client(client):
    _, base, studio = _verify_package()
    if not isinstance(client, studio.StudioMixin):
        raise UnsupportedClientError('Unsupported NotebookLM client instance; no audio was sent.')
    methods = {name: getattr(base.BaseClient, name) for name in (
        '_call_rpc', '_build_request_body', '_build_url', '_get_client',
        '_parse_response', '_extract_rpc_result',
    )}
    methods['create_audio_overview'] = studio.StudioMixin.create_audio_overview
    for name, expected in methods.items():
        actual = getattr(client, name, None)
        if (not isinstance(actual, MethodType) or actual.__self__ is not client
                or actual.__func__ is not expected):
            raise UnsupportedClientError('NotebookLM client methods were replaced; no audio was sent.')
        module = base if name != 'create_audio_overview' else studio
        if Path(inspect.getsourcefile(expected) or '').resolve() != Path(module.__file__).resolve():
            raise UnsupportedClientError('NotebookLM method provenance mismatch; no audio was sent.')
    if client.RPC_CREATE_STUDIO != 'R7cb6c' or client.STUDIO_TYPE_AUDIO != 1:
        raise UnsupportedClientError('Unsupported NotebookLM audio RPC; no audio was sent.')


def _verify_http_transport(http):
    # No custom retrying transports, subclasses, or redirect-following send loop.
    # MockTransport is explicitly accepted for network-free exact-upstream tests.
    import httpx
    if type(http) is not httpx.Client:
        raise UnsupportedClientError('Unsupported HTTP client; no audio was sent.')
    transports = [http._transport, *http._mounts.values()]
    for transport in transports:
        if transport is None or type(transport) is httpx.MockTransport:
            continue
        if (type(transport) is not httpx.HTTPTransport
                or getattr(getattr(transport, '_pool', None), '_retries', None) != 0):
            raise UnsupportedClientError('HTTP transport may replay requests; no audio was sent.')
    if http.auth is not None:
        raise UnsupportedClientError('HTTP authentication flow may replay requests; no audio was sent.')
    if any(http.event_hooks.values()):
        raise UnsupportedClientError('HTTP event hooks are unsupported; no audio was sent.')


def _identifier(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _validate_request(notebook_id, source_ids, format_code, length_code, language, focus_prompt):
    if not _identifier(notebook_id):
        raise InvalidAudioRequest('A nonempty notebook ID is required.')
    if (type(source_ids) is not list or not source_ids
            or any(not _identifier(source) for source in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise InvalidAudioRequest('A nonempty list of distinct source IDs is required.')
    if type(format_code) is not int or format_code not in (1, 2, 3, 4):
        raise InvalidAudioRequest('Unsupported audio format code.')
    if type(length_code) is not int or length_code not in (1, 2, 3):
        raise InvalidAudioRequest('Unsupported audio length code.')
    if (type(language) is not str or not language or len(language) > 64
            or any(char.isspace() for char in language) or type(focus_prompt) is not str):
        raise InvalidAudioRequest('A language code and string focus prompt are required.')


def _validate_payload(params, path, notebook_id, source_ids, format_code,
                      length_code, language, focus_prompt):
    """Validate the audited schema; upstream, not this function, builds the body."""
    try:
        payload = params[2]
        options = payload[6]
        inner = options[1]
        valid = (type(params) is list and len(params) == 3 and params[0] == [2]
                 and params[1] == notebook_id and path == '/notebook/' + notebook_id
                 and type(payload) is list and len(payload) == 7
                 and payload[:3] == [None, None, 1] and payload[4:6] == [None, None]
                 and payload[3] == [[[source]] for source in source_ids]
                 and type(options) is list and len(options) == 2 and options[0] is None
                 and type(inner) is list and len(inner) == 7
                 and inner == [focus_prompt, length_code, None,
                               [[source] for source in source_ids], language, None, format_code])
    except (IndexError, KeyError, TypeError):
        valid = False
    if not valid:
        raise UnsupportedClientError('Unexpected audio RPC payload; no audio was sent.')


def create_audio_once(client, notebook_id, source_ids, format_code, length_code,
                      language, focus_prompt):
    """Use upstream audio construction, but dispatch at most one HTTP POST.

    No auth recovery/CDP/retry wrapper runs for audio. Unrelated RPCs retain the
    original transport. Any failure after post() begins is outcome-unknown.
    The supplied client must not be shared for concurrent studio operations.
    """
    _validate_request(notebook_id, source_ids, format_code, length_code, language, focus_prompt)
    source_ids = tuple(source_ids)  # Independent of the list passed to upstream.
    with _ACTIVE_LOCK:
        if id(client) in _ACTIVE:
            raise UnsupportedClientError('This client already has an active audio kickoff.')
        _ACTIVE.add(id(client))
    try:
        _verify_client(client)
        original = client._call_rpc
        previous = vars(client).get('_call_rpc', _ABSENT)
        studio_seen = 0
        attempted = False

        def intercept(instance, rpc_id, params, path='/', timeout=None, *extra, **kwargs):
            nonlocal studio_seen, attempted
            if rpc_id != instance.RPC_CREATE_STUDIO:
                return original(rpc_id, params, path, timeout, *extra, **kwargs)
            studio_seen += 1
            if studio_seen != 1:
                raise UnsupportedClientError('A second studio dispatch was blocked.')
            if timeout is not None or extra or kwargs:
                raise UnsupportedClientError('Unexpected audio RPC call signature; no audio was sent.')
            _validate_payload(params, path, notebook_id, source_ids, format_code,
                              length_code, language, focus_prompt)
            body = instance._build_request_body(rpc_id, params)
            url = instance._build_url(rpc_id, path)
            http = instance._get_client()
            _verify_http_transport(http)
            attempted = True  # Never fall back/retry after entering the transport.
            response = http.post(url, content=body, follow_redirects=False)
            response.raise_for_status()
            return instance._extract_rpc_result(instance._parse_response(response.text), rpc_id)

        client._call_rpc = MethodType(intercept, client)
        try:
            result = client.create_audio_overview(
                notebook_id, source_ids=list(source_ids), format_code=format_code,
                length_code=length_code, language=language, focus_prompt=focus_prompt)
            if (not attempted or studio_seen != 1 or type(result) is not dict
                    or not _identifier(result.get('artifact_id'))
                    or result.get('notebook_id') != notebook_id or result.get('type') != 'audio'):
                raise UnsupportedClientError('Audio response did not confirm the expected artifact.')
            return result
        except Exception:
            if attempted:
                raise AudioOutcomeUnknownError(
                    'Audio kickoff outcome is unknown; reconcile existing artifacts before any resend.') from None
            raise
        finally:
            if previous is _ABSENT:
                del client._call_rpc
            else:
                client._call_rpc = previous
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(id(client))


def _check_report():
    version, _, _ = _verify_package()
    import httpx
    if ('follow_redirects' not in inspect.signature(httpx.Client.post).parameters
            or inspect.signature(httpx.HTTPTransport).parameters['retries'].default != 0):
        raise UnsupportedClientError('Unsupported HTTPX single-send capability.')
    return {'ok': True, 'client_version': version, 'source_fingerprints': _PINS[version],
            'safe_driver': 'audio_only_single_post', 'auth_loaded': False,
            'guarantee': 'at_most_one_adapter_dispatch'}


def _enum_codes(audio_format, audio_length):
    from notebooklm_tools.core import constants
    return constants.AUDIO_FORMATS.get_code(audio_format), constants.AUDIO_LENGTHS.get_code(audio_length)


def _load_client(profile):
    from notebooklm_tools.cli.utils import get_client
    return get_client(profile)


def _read_request(path):
    try:
        path = Path(path)
        if path.stat().st_size > 1024 * 1024:
            raise InvalidAudioRequest('Audio request JSON is too large.')
        request = json.loads(path.read_text(encoding='utf-8'))
        required = {'notebook_id', 'source_ids', 'format', 'length', 'language', 'focus_prompt'}
        if type(request) is not dict or not required <= request.keys() or request.keys() - required - {'profile'}:
            raise InvalidAudioRequest('Audio request JSON has missing or unsupported fields.')
        if request['format'] not in ('deep_dive', 'brief', 'critique', 'debate'):
            raise InvalidAudioRequest('Unsupported audio format name.')
        if request['length'] not in ('short', 'default', 'long'):
            raise InvalidAudioRequest('Unsupported audio length name.')
        profile = request.get('profile')
        if profile is not None and (type(profile) is not str or not profile.strip()):
            raise InvalidAudioRequest('Profile must be null or a nonempty string.')
        # Validate IDs and string fields before any environment/auth initialization.
        _validate_request(request['notebook_id'], request['source_ids'], 1, 2,
                          request['language'], request['focus_prompt'])
        return request
    except SingleSendError:
        raise
    except Exception:
        raise InvalidAudioRequest('Cannot read a valid audio request JSON file.') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--request', metavar='FILE', help='audio request JSON; caller must persist pending intent first')
    mode.add_argument('--check', action='store_true', help='check pinned runtime without loading auth or sending requests')
    parser.add_argument('--environment-entrypoint', metavar='FILE', help='existing trusted Python CLI environment wrapper')
    args = parser.parse_args(argv)
    try:
        request = None if args.check else _read_request(args.request)
        # Suppress bootstrap/auth/provider diagnostics, which may contain private data.
        # Only the allowlisted result or a fixed sanitized error reaches the CLI.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if args.environment_entrypoint:
                entrypoint = Path(args.environment_entrypoint)
                if not entrypoint.is_file() or entrypoint.suffix != '.py':
                    raise InvalidAudioRequest('Environment entrypoint must be an existing Python script.')
                runpy.run_path(str(entrypoint), run_name='game_tape_environment')
            if args.check:
                output = _check_report()
            else:
                _verify_package()  # Fail unsupported versions before loading auth.
                format_code, length_code = _enum_codes(request['format'], request['length'])
                with _load_client(request.get('profile')) as client:
                    result = create_audio_once(
                        client, request['notebook_id'], request['source_ids'], format_code,
                        length_code, request['language'], request['focus_prompt'])
                output = {name: result[name] for name in (
                    'artifact_id', 'notebook_id', 'type', 'status', 'format', 'length', 'language')
                    if name in result}
        print(json.dumps(output, ensure_ascii=True))
        return 0
    except SingleSendError as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'reconcile_before_resend': True}), file=sys.stderr)
        return 2
    except (Exception, SystemExit):
        print(json.dumps({'ok': False, 'error': 'Audio helper failed without a confirmed result; reconcile before any resend.',
                          'reconcile_before_resend': True}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
