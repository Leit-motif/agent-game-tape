"""Offline adapter contract tests; no authenticated client or network is used."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import nlm_single_send as safe


class Response:
    text = 'synthetic response'

    def __init__(self, failure=None):
        self.failure = failure

    def raise_for_status(self):
        if self.failure:
            raise self.failure


class HTTP:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.status_failure = None
        self.commits = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.commits.append('synthetic server-side commit')
        if self.failure:
            raise self.failure
        return Response(self.status_failure)


class Client:
    RPC_CREATE_STUDIO = 'R7cb6c'
    STUDIO_TYPE_AUDIO = 1

    def __init__(self):
        self.http = HTTP()
        self.normal_reads = 0
        self.parse_failure = None
        self.rpc_failure = None
        self.artifact_id = 'audio-fixture'
        self.repeat = False
        self.mutate_sources = False
        self.bad_payload = False
        self.wrong_notebook = False
        self.wrong_path = False

    def _call_rpc(self, rpc_id, params, path='/', timeout=None):
        if rpc_id == 'READ':
            self.normal_reads += 1
            return 'normal read'
        raise AssertionError('the replay-capable studio transport must not run')

    def _build_request_body(self, rpc_id, params):
        return json.dumps([rpc_id, params])

    def _build_url(self, rpc_id, path):
        return 'https://example.invalid/rpc'

    def _get_client(self):
        return self.http

    def _parse_response(self, text):
        if self.parse_failure:
            raise self.parse_failure
        return text

    def _extract_rpc_result(self, parsed, rpc_id):
        if self.rpc_failure:
            raise self.rpc_failure
        return [[self.artifact_id, None, 1, None, 1]]

    def create_audio_overview(self, notebook_id, source_ids, format_code,
                              length_code, language, focus_prompt):
        self._call_rpc('READ', [])
        if self.mutate_sources:
            source_ids.append('unrequested-source')
        params = [[2], notebook_id, [None, None, 1,
                  [[[source]] for source in source_ids], None, None,
                  [None, [focus_prompt, length_code, None,
                          [[source] for source in source_ids], language, None, format_code]]]]
        if self.bad_payload:
            params[2][2] = 2  # Not audio.
        if self.wrong_notebook:
            params[1] = 'unrequested-notebook'
        path = '/notebook/' + ('unrequested-notebook' if self.wrong_path else notebook_id)
        raw = self._call_rpc(self.RPC_CREATE_STUDIO, params, path)
        if self.repeat:
            try:
                self._call_rpc(self.RPC_CREATE_STUDIO, params, '/notebook/' + notebook_id)
            except ValueError:
                pass  # A swallowed replay must still invalidate the overall operation.
        return {'artifact_id': raw[0][0], 'notebook_id': notebook_id,
                'type': 'audio', 'status': 'in_progress', 'format': 'deep_dive',
                'length': 'default', 'language': language}


class SingleSendTests(unittest.TestCase):
    def test_one_post_preserves_payload_normal_reads_and_bound_method(self):
        client = Client()
        original = client._call_rpc
        # The installed-package boundary is substituted only in offline fake tests.
        with patch.object(safe, '_verify_client'), patch.object(safe, '_verify_http_transport'):
            result = safe.create_audio_once(client, 'nb-fixture', ['source-a', 'source-b'],
                                            1, 2, 'en', 'synthetic focus')
        self.assertEqual(result['artifact_id'], 'audio-fixture')
        self.assertEqual(client._call_rpc, original)
        self.assertNotIn('_call_rpc', vars(client))
        self.assertEqual(client.normal_reads, 1)
        self.assertEqual(len(client.http.calls), 1)
        url, request = client.http.calls[0]
        self.assertFalse(request['follow_redirects'])
        self.assertEqual(json.loads(request['content']), ['R7cb6c', [[2], 'nb-fixture',
                         [None, None, 1, [[['source-a']], [['source-b']]], None, None,
                          [None, ['synthetic focus', 2, None, [['source-a'], ['source-b']],
                                  'en', None, 1]]]]])

    def invoke(self, client):
        with patch.object(safe, '_verify_client'), patch.object(safe, '_verify_http_transport'):
            return safe.create_audio_once(client, 'nb-fixture', ['source-a', 'source-b'],
                                          1, 2, 'en', 'synthetic focus')

    def test_failures_never_resend_or_leak_response_details(self):
        for location, label in [('status_failure', '503'), ('status_failure', '429'),
                                ('status_failure', '400'), ('status_failure', '401'),
                                ('status_failure', '403'), ('failure', 'ConnectError'),
                                ('failure', 'ConnectTimeout'), ('failure', 'ReadTimeout'),
                                ('failure', 'WriteTimeout'), ('failure', 'ReadError'),
                                ('failure', 'WriteError'), ('parse_failure', 'malformed'),
                                ('rpc_failure', 'RPC8'), ('rpc_failure', 'RPC16')]:
            with self.subTest(location=location, label=label):
                client = Client()
                target = client.http if location in ('failure', 'status_failure') else client
                setattr(target, location, RuntimeError(label + ' secret synthetic response'))
                original = client._call_rpc
                with self.assertRaises(safe.AudioOutcomeUnknownError) as caught:
                    self.invoke(client)
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(len(client.http.calls), 1)
                self.assertEqual(len(client.http.commits), 1)
                self.assertEqual(client._call_rpc, original)
                self.assertNotIn('_call_rpc', vars(client))

    def test_missing_artifact_id_is_unknown_not_retry(self):
        client = Client()
        client.artifact_id = None
        with self.assertRaises(safe.AudioOutcomeUnknownError):
            self.invoke(client)
        self.assertEqual(len(client.http.calls), 1)

    def test_second_studio_attempt_invalidates_even_if_caller_swallows_error(self):
        client = Client()
        client.repeat = True
        with self.assertRaises(safe.AudioOutcomeUnknownError):
            self.invoke(client)
        self.assertEqual(len(client.http.calls), 1)

    def test_unrequested_sources_and_non_audio_payload_fail_before_dispatch(self):
        for attribute in ('mutate_sources', 'bad_payload', 'wrong_notebook', 'wrong_path'):
            with self.subTest(attribute=attribute):
                client = Client()
                setattr(client, attribute, True)
                with self.assertRaises(safe.UnsupportedClientError):
                    self.invoke(client)
                self.assertEqual(client.http.calls, [])
                self.assertNotIn('_call_rpc', vars(client))

    def test_invalid_ids_and_codes_fail_before_client_verification(self):
        for args in [('', ['source-a'], 1, 2, 'en', ''),
                     ('nb-fixture', [], 1, 2, 'en', ''),
                     ('nb-fixture', [''], 1, 2, 'en', ''),
                     ('nb-fixture', ['source-a', 'source-a'], 1, 2, 'en', ''),
                     ('nb-fixture', ['source-a'], True, 2, 'en', ''),
                     ('nb-fixture', ['source-a'], 1, 9, 'en', '')]:
            with self.subTest(args=args), patch.object(safe, '_verify_client') as verify:
                with self.assertRaises(safe.InvalidAudioRequest):
                    safe.create_audio_once(Client(), *args)
                verify.assert_not_called()

    def test_instance_bound_method_and_active_guard_are_restored(self):
        client = Client()
        client._call_rpc = client._call_rpc
        original = vars(client)['_call_rpc']
        self.invoke(client)
        self.assertIs(vars(client)['_call_rpc'], original)
        client.http.failure = RuntimeError('response lost')
        with self.assertRaises(safe.AudioOutcomeUnknownError):
            self.invoke(client)
        self.assertIs(vars(client)['_call_rpc'], original)
        client.http.failure = None
        # This API does not replace the publisher's durable pending-intent gate.
        self.invoke(client)
        self.assertEqual(len(client.http.calls), 3)

    def test_same_client_concurrent_audio_invocation_is_rejected(self):
        client = Client()
        started, release = threading.Event(), threading.Event()
        original_post = client.http.post
        result = []
        def post(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise RuntimeError('test synchronization timeout')
            return original_post(*args, **kwargs)
        client.http.post = post
        def first():
            try:
                result.append(safe.create_audio_once(client, 'nb-fixture', ['source-a'], 1, 2, 'en', ''))
            except Exception as exc:
                result.append(exc)
        with patch.object(safe, '_verify_client'), patch.object(safe, '_verify_http_transport'):
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaises(safe.UnsupportedClientError):
                    safe.create_audio_once(client, 'nb-fixture', ['source-a'], 1, 2, 'en', '')
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(result[0], dict)
        self.assertEqual(len(client.http.calls), 1)


class CLITests(unittest.TestCase):
    def test_check_does_not_initialize_auth(self):
        output = io.StringIO()
        with patch.object(safe, '_check_report', return_value={'ok': True, 'client_version': '0.15.1'}), \
                patch.object(safe, '_load_client') as load, contextlib.redirect_stdout(output):
            self.assertEqual(safe.main(['--check']), 0)
        load.assert_not_called()
        self.assertTrue(json.loads(output.getvalue())['ok'])

    def test_import_uses_standard_library_only(self):
        script = Path(safe.__file__).resolve()
        code = """import importlib.util, sys
class Block:
    def find_spec(self, name, *args):
        if name.split('.')[0] in ('httpx', 'notebooklm_tools'):
            raise AssertionError('optional dependency imported')
sys.meta_path.insert(0, Block())
spec = importlib.util.spec_from_file_location('offline_adapter', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.create_audio_once)
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code, str(script)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_version_fails_before_upstream_import(self):
        class Distribution:
            version = '99.0'
        with patch.object(safe.importlib.metadata, 'distribution', return_value=Distribution()):
            with self.assertRaises(safe.UnsupportedClientError):
                safe._verify_package()

    def test_request_environment_runs_before_client_and_stdout_is_allowlisted(self):
        request = {'notebook_id': 'nb-fixture', 'source_ids': ['source-a'],
                   'format': 'brief', 'length': 'short', 'language': 'en',
                   'focus_prompt': 'private focus', 'profile': None}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'request.json'
            path.write_text(json.dumps(request))
            environment = Path(folder) / 'environment.py'
            environment.write_text("import builtins\nassert __name__ == 'game_tape_environment'\n"
                                   "builtins._single_send_test_environment = True\n"
                                   "print('private bootstrap diagnostic')\n")
            def load(profile):
                import builtins
                self.assertTrue(builtins._single_send_test_environment)
                self.assertIsNone(profile)
                print('private auth diagnostic')
                return contextlib.nullcontext(Client())
            result = {'artifact_id': 'audio-fixture', 'notebook_id': 'nb-fixture', 'type': 'audio',
                      'status': 'in_progress', 'format': 'brief', 'length': 'short', 'language': 'en',
                      'cookies': 'secret synthetic cookies'}
            stdout, stderr = io.StringIO(), io.StringIO()
            try:
                with patch.object(safe, '_verify_package'), \
                        patch.object(safe, '_enum_codes', return_value=(2, 1)) as enums, \
                        patch.object(safe, '_load_client', side_effect=load), \
                        patch.object(safe, 'create_audio_once', return_value=result) as create, \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = safe.main(['--request', str(path), '--environment-entrypoint', str(environment)])
                self.assertEqual(code, 0)
                self.assertEqual(stderr.getvalue(), '')
                enums.assert_called_once_with('brief', 'short')
                self.assertEqual(create.call_args.args[1:], ('nb-fixture', ['source-a'], 2, 1, 'en', 'private focus'))
                output = json.loads(stdout.getvalue())
                self.assertNotIn('cookies', output)
                self.assertNotIn('private', stdout.getvalue())
                self.assertNotIn('secret', stdout.getvalue())
            finally:
                import builtins
                if hasattr(builtins, '_single_send_test_environment'):
                    del builtins._single_send_test_environment

    def test_invalid_request_never_initializes_environment_or_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / 'request.json'
            request.write_text('{"notebook_id":""}')
            stderr = io.StringIO()
            with patch.object(safe.runpy, 'run_path') as run, patch.object(safe, '_load_client') as load, \
                    contextlib.redirect_stderr(stderr):
                self.assertEqual(safe.main(['--request', str(request), '--environment-entrypoint', 'unused.py']), 2)
            run.assert_not_called()
            load.assert_not_called()
            self.assertFalse(json.loads(stderr.getvalue())['ok'])

    def test_auth_error_details_do_not_escape_cli(self):
        request = {'notebook_id': 'nb-fixture', 'source_ids': ['source-a'], 'format': 'deep_dive',
                   'length': 'default', 'language': 'en', 'focus_prompt': '', 'profile': None}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'request.json'
            path.write_text(json.dumps(request))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(safe, '_verify_package'), patch.object(safe, '_enum_codes', return_value=(1, 2)), \
                    patch.object(safe, '_load_client', side_effect=RuntimeError('secret cookie')), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(safe.main(['--request', str(path)]), 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn('secret', stderr.getvalue())
            self.assertTrue(json.loads(stderr.getvalue())['reconcile_before_resend'])


@unittest.skipUnless(os.environ.get('NLM_EXACT_UPSTREAM_TESTS') == '1',
                     'opt in under the separately installed NotebookLM venv')
class ExactUpstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import httpx
            from notebooklm_tools.core.base import BaseClient
            from notebooklm_tools.core.studio import StudioMixin
        except ImportError:
            raise unittest.SkipTest('optional NotebookLM/HTTPX dependencies unavailable')
        cls.httpx, cls.Base, cls.Studio = httpx, BaseClient, StudioMixin
        safe._verify_package()

    def client(self, handler):
        client = self.Studio.__new__(self.Studio)  # No constructor/auth/profile access.
        client.csrf_token = 'synthetic'
        client._session_id = ''
        client._bl = ''
        client._base_host = 'notebook.google.com'
        client._state_lock = threading.Lock()
        client._client = self.httpx.Client(transport=self.httpx.MockTransport(handler), trust_env=False)
        self.addCleanup(client._client.close)
        return client

    def payload(self, result=None, code=None):
        body = json.dumps([['wrb.fr', 'R7cb6c', json.dumps(result) if code is None else None,
                           None, None, [code] if code is not None else None, 'generic']])
        return ")]}'\n" + body

    def invoke(self, client):
        return safe.create_audio_once(client, 'nb-fixture', ['source-a', 'source-b'], 1, 2, 'en', 'synthetic focus')

    def test_exact_upstream_failures_dispatch_once_and_never_recover(self):
        failures = [500, 502, 503, 504, 429, 400, 401, 403, 301, 302, 303, 307, 308, 'rpc8', 'rpc16',
                    'malformed', 'missing_id', 'ConnectError', 'ConnectTimeout',
                    'ReadTimeout', 'WriteTimeout', 'ReadError', 'WriteError']
        for failure in failures:
            with self.subTest(failure=failure):
                requests = []
                def handler(request):
                    requests.append(request)  # Server commit simulated before any response failure.
                    if isinstance(failure, int):
                        return self.httpx.Response(failure, text='synthetic response',
                                                   headers={'Location': 'https://example.invalid/redirect'})
                    if failure.startswith('rpc'):
                        return self.httpx.Response(200, text=self.payload(code=int(failure[3:])))
                    if failure == 'malformed':
                        return self.httpx.Response(200, text='not a response')
                    if failure == 'missing_id':
                        return self.httpx.Response(200, text=self.payload([[None, None, 1, None, 1]]))
                    raise getattr(self.httpx, failure)('synthetic response lost', request=request)
                client = self.client(handler)
                original = client._call_rpc
                with patch.object(self.Base, '_refresh_auth_tokens', side_effect=AssertionError('auth recovery')) as refresh, \
                        patch.object(self.Base, '_try_reload_or_headless_auth', side_effect=AssertionError('headless recovery')) as recover, \
                        patch.object(self.Base, '_cdp_rpc_transport_enabled', side_effect=AssertionError('CDP transport')) as cdp:
                    with self.assertRaises(safe.AudioOutcomeUnknownError):
                        self.invoke(client)
                refresh.assert_not_called()
                recover.assert_not_called()
                cdp.assert_not_called()
                self.assertEqual(len(requests), 1)
                self.assertEqual(client._call_rpc, original)
                self.assertNotIn('_call_rpc', vars(client))

    def test_exact_upstream_encoding_success_and_enum_mapping(self):
        requests = []
        def handler(request):
            requests.append(request)
            return self.httpx.Response(200, text=self.payload([['audio-fixture', None, 1, None, 1]]))
        client = self.client(handler)
        result = self.invoke(client)
        self.assertEqual(result['artifact_id'], 'audio-fixture')
        self.assertEqual(len(requests), 1)
        form = urllib.parse.parse_qs(requests[0].content.decode())
        params = json.loads(json.loads(form['f.req'][0])[0][0][1])
        self.assertEqual(params, [[2], 'nb-fixture', [None, None, 1,
                        [[['source-a']], [['source-b']]], None, None,
                        [None, ['synthetic focus', 2, None, [['source-a'], ['source-b']], 'en', None, 1]]]])
        self.assertEqual(safe._enum_codes('brief', 'short'), (2, 1))
        self.assertEqual(safe._enum_codes('debate', 'long'), (4, 3))

    def test_tampered_package_and_replaced_methods_fail_before_network(self):
        client = self.client(lambda request: self.fail('network forbidden'))
        client._build_request_body = lambda *_: 'tampered'
        with self.assertRaises(safe.UnsupportedClientError):
            self.invoke(client)
        with patch.object(safe.Path, 'read_bytes', return_value=b'tampered source'):
            with self.assertRaises(safe.UnsupportedClientError):
                safe._verify_package()

    def test_unrelated_read_retry_behavior_remains_upstream_default(self):
        requests = []
        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return self.httpx.Response(200, text=self.payload([['audio-fixture', None, 1, None, 1]]))
            if len(requests) == 2:
                return self.httpx.Response(503, text='transient synthetic read failure')
            return self.httpx.Response(200, text=json.dumps([
                ['wrb.fr', 'wXbhsf', '[1]', None, None, None, 'generic']]))
        client = self.client(handler)
        self.invoke(client)
        with patch('time.sleep'), patch.object(self.Base, '_cdp_rpc_transport_enabled', return_value=False):
            self.assertEqual(client._call_rpc('wXbhsf', []), [1])
        self.assertEqual(len(requests), 3)

    def test_retrying_http_post_wrapper_is_rejected_before_dispatch(self):
        requests = []
        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return self.httpx.Response(503, text='synthetic lost commit response')
            return self.httpx.Response(200, text=self.payload([['audio-fixture', None, 1, None, 1]]))
        client = self.client(handler)
        post = client._client.post
        def retrying_post(*args, **kwargs):
            response = post(*args, **kwargs)
            try:
                response.raise_for_status()
                return response
            except self.httpx.HTTPStatusError:
                return post(*args, **kwargs)
        client._client.post = retrying_post
        with self.assertRaises(safe.UnsupportedClientError):
            self.invoke(client)
        self.assertEqual(requests, [])
        self.assertNotIn('_call_rpc', vars(client))

    def test_replaced_http_dispatch_and_transport_methods_are_rejected(self):
        for name in ('post', 'request', 'send', '_send_handling_auth',
                     '_send_handling_redirects', '_send_single_request', '_transport_for_url'):
            with self.subTest(method=name):
                client = self.client(lambda request: self.fail('network forbidden'))
                setattr(client._client, name, lambda *args, **kwargs: self.fail('wrapper invoked'))
                with self.assertRaises(safe.UnsupportedClientError):
                    self.invoke(client)
        client = self.client(lambda request: self.fail('network forbidden'))
        client._client._transport.handle_request = lambda *args: self.fail('transport wrapper invoked')
        with self.assertRaises(safe.UnsupportedClientError):
            self.invoke(client)

    def test_retrying_transport_auth_and_hooks_are_rejected(self):
        for options in ({'transport': self.httpx.HTTPTransport(retries=1)},
                        {'auth': ('synthetic-user', 'synthetic-password')},
                        {'event_hooks': {'request': [lambda request: None]}}):
            with self.subTest(option=next(iter(options))), self.httpx.Client(trust_env=False, **options) as http:
                with self.assertRaises(safe.UnsupportedClientError):
                    safe._verify_http_transport(http)


if __name__ == '__main__':
    unittest.main()
