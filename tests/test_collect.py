"""Synthetic-only regression tests at the public collect() seam."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SPEC = importlib.util.spec_from_file_location(
    "game_tape_collect", Path(__file__).resolve().parents[1] / "scripts" / "collect.py"
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2030, 10, 19, tzinfo=timezone.utc)
END = datetime(2030, 10, 20, tzinfo=timezone.utc)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_records(self, name, records):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
        return path

    def collect_fixture(self, harness, name):
        return collector.collect([(harness, FIXTURES / name)], START, END)

    def claude_message(self, text="Synthetic prompt.", timestamp="2030-10-19T10:00:00Z"):
        return {"type": "user", "timestamp": timestamp, "message": {"role": "user", "content": text}}

    def test_claude_preserves_real_human_markdown_and_instructions(self):
        events, coverage = self.collect_fixture("claude-code", "claude.jsonl")
        humans = [event["text"] for event in events if event["role"] == "human"]
        self.assertEqual(humans, [
            "# AGENTS.md instructions\nKeep the public API unchanged.\n\n## Acceptance\n- Test the boundary.",
            "# Fix the collector\n\nUser instructions: preserve my Markdown, including <example> tags.",
        ])
        self.assertEqual(coverage[0]["human_events"], 2)

    def test_claude_tool_results_are_never_human_and_all_blocks_have_ids(self):
        events, _ = self.collect_fixture("claude-code", "claude.jsonl")
        self.assertEqual([event["role"] for event in events], [
            "human", "human", "assistant", "tool_call", "tool_call", "tool", "tool",
        ])
        self.assertEqual(len({event["id"] for event in events}), len(events))
        tools = [event for event in events if event["role"] == "tool"]
        self.assertEqual([event["text"] for event in tools], [
            "This is tool output, not a human instruction.", "Synthetic tests passed.",
        ])
        self.assertEqual([event["line"] for event in tools], [4, 4])

    def test_injected_wrappers_do_not_drop_adjacent_real_prompt(self):
        path = self.write_records("mixed.jsonl", [
            {"type": "user", "timestamp": "2030-10-19T10:00:00Z", "message": {
                "role": "user", "content": [
                    {"type": "text", "text": "<system-reminder>Generated context.</system-reminder>"},
                    {"type": "text", "text": "## My instructions\nUse a half-open boundary."},
                ],
            }},
            {"type": "user", "timestamp": "2030-10-19T10:01:00Z", "message": {
                "role": "user", "content": "Please keep this sentence.\n\n<system-reminder>Generated context.</system-reminder>",
            }},
            {"type": "user", "timestamp": "2030-10-19T10:02:00Z", "message": {
                "role": "user", "content": "Caveat: do not remove genuine user caveats.",
            }},
        ])
        events, _ = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], [
            "## My instructions\nUse a half-open boundary.",
            "Please keep this sentence.",
            "Caveat: do not remove genuine user caveats.",
        ])

    def test_codex_uses_response_items_not_duplicate_event_stream(self):
        events, coverage = self.collect_fixture("codex", "codex.jsonl")
        self.assertEqual([event["role"] for event in events], [
            "human", "assistant", "tool_call", "tool", "tool_call", "tool", "assistant",
        ])
        self.assertEqual(events[0]["text"], "# Actual user request\nUser instructions: keep this wording.")
        self.assertEqual(events[1]["text"], "Commentary is evidence, too.")
        self.assertEqual(coverage[0]["human_events"], 1)
        self.assertGreaterEqual(coverage[0]["excluded_records"], 4)
        self.assertNotIn("Duplicate human stream", "\n".join(event["text"] for event in events))

    def test_codex_subagent_metadata_applies_even_after_an_event(self):
        events, coverage = self.collect_fixture("codex", "codex-subagent.jsonl")
        self.assertEqual(events, [])
        self.assertGreater(coverage[0]["excluded_records"], 0)
        self.assertGreater(coverage[0]["delegated_records"], 0)

    def test_codex_exec_and_originator_metadata_do_not_create_human_calls(self):
        for metadata in ({"source": "exec"}, {"source": "cli", "originator": "codex_exec"}):
            with self.subTest(metadata=metadata):
                path = self.write_records("automated.jsonl", [
                    {"type": "session_meta", "payload": metadata},
                    {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {
                        "type": "message", "role": "user", "content": "An automated invocation.",
                    }},
                ])
                events, coverage = collector.collect([("codex", path)], START, END)
                self.assertEqual(events, [])
                self.assertGreater(coverage[0]["automated_records"], 0)

    def test_claude_known_automated_and_compacted_prompts_are_excluded(self):
        metadata_rows = [
            {"promptSource": "sdk", "entrypoint": "sdk-ts", "origin": {"kind": "human"}},
            {"origin": {"kind": "human", "promptSource": "sdk", "entrypoint": "sdk-ts"}},
            {"isCompactSummary": True},
            {"teamName": "synthetic-team"},
        ]
        path = self.write_records("claude-auto.jsonl", [
            {"type": "user", "timestamp": "2030-10-19T10:00:00Z", "message": {
                "role": "user", "content": "Not a verified human instruction.",
            }, **metadata} for metadata in metadata_rows
        ])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["excluded_records"], 4)

    def test_openclaw_export_attribution_and_async_notifications(self):
        events, coverage = self.collect_fixture("openclaw", "openclaw.jsonl")
        self.assertEqual([event["role"] for event in events], ["human", "assistant", "tool_call", "tool"])
        self.assertEqual(events[0]["text"], "## Check the exported evidence\nKeep local-only material local.")
        self.assertEqual(coverage[0]["human_events"], 1)
        self.assertGreaterEqual(coverage[0]["excluded_records"], 3)

    def test_codex_0163_paginated_completed_items_are_canonical_without_duplicates(self):
        events, coverage = self.collect_fixture("codex", "codex-paginated.jsonl")
        self.assertEqual([event["role"] for event in events], [
            "human", "assistant", "tool_call", "tool", "tool", "assistant",
        ])
        self.assertEqual(events[0]["text"], "# Current Codex request\nUser instructions: preserve this prompt.")
        self.assertEqual(events[1]["text"], "I will verify the current format.")
        self.assertEqual([event["line"] for event in events], [4, 6, 9, 9, 10, 13])
        self.assertIn('"exit_code": 0', events[3]["text"])
        self.assertEqual(coverage[0]["paginated_files"], 1)
        self.assertEqual(coverage[0]["human_events"], 1)
        self.assertEqual(coverage[0]["unsupported_records"], 0)
        self.assertEqual(coverage[0]["status"], "ok")

    def test_public_adapter_names_and_event_contract(self):
        self.assertEqual(set(collector.ADAPTERS), {"claude-code", "codex", "openclaw"})
        for harness, fixture in (("claude-code", "claude.jsonl"), ("codex", "codex.jsonl"), ("codex", "codex-paginated.jsonl"), ("openclaw", "openclaw.jsonl")):
            with self.subTest(harness=harness):
                events, _ = self.collect_fixture(harness, fixture)
                for event in events:
                    self.assertEqual(set(event), {"id", "session", "harness", "source", "line", "timestamp", "role", "text", "truncated"})
                    self.assertIn(event["role"], {"human", "assistant", "tool_call", "tool"})
                    self.assertGreater(event["line"], 0)
                    self.assertEqual(event["harness"], harness)
                    self.assertFalse(Path(event["source"]).is_absolute())
                    self.assertNotIn("..", Path(event["source"]).parts)

    def test_utc_instant_sorting_and_half_open_boundaries(self):
        path = self.write_records("offsets.jsonl", [
            self.claude_message("end excluded", "2030-10-20T00:00:00Z"),
            self.claude_message("start included", "2030-10-19T02:00:00+02:00"),
            self.claude_message("earlier instant", "2030-10-19T12:00:00+02:00"),
            self.claude_message("later instant", "2030-10-19T10:30:00Z"),
            self.claude_message("before start", "2030-10-18T23:59:59.999999Z"),
            self.claude_message("numeric seconds", int(START.replace(hour=13).timestamp())),
            self.claude_message("numeric millis", int(START.replace(hour=14).timestamp() * 1000)),
        ])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], [
            "start included", "earlier instant", "later instant", "numeric seconds", "numeric millis",
        ])
        self.assertEqual(events[0]["timestamp"], "2030-10-19T00:00:00+00:00")
        self.assertEqual(events[-2]["timestamp"], "2030-10-19T13:00:00+00:00")
        self.assertEqual(events[-1]["timestamp"], "2030-10-19T14:00:00+00:00")
        self.assertEqual(coverage[0]["outside_window_events"], 2)

    def test_daylight_saving_fold_uses_actual_instants(self):
        try:
            zone = ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            self.skipTest("System IANA timezone data unavailable")
        start = datetime(2030, 11, 3, 1, 0, tzinfo=zone, fold=1)
        end = datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1)
        path = self.write_records("fold.jsonl", [
            self.claude_message("first 1:15 is outside", "2030-11-03T01:15:00-04:00"),
            self.claude_message("second 1:15 is inside", "2030-11-03T01:15:00-05:00"),
            self.claude_message("second 1:30 is excluded", "2030-11-03T01:30:00-05:00"),
        ])
        events, _ = collector.collect([("claude-code", path)], start, end)
        self.assertEqual([event["text"] for event in events], ["second 1:15 is inside"])
        self.assertEqual(events[0]["timestamp"], "2030-11-03T06:15:00+00:00")

    def test_invalid_or_missing_timestamps_are_reported(self):
        invalid_times = [None, "", "not a date", "2030-10-19T10:00:00", True, {}, 10**30]
        path = self.write_records("missing-times.jsonl", [
            self.claude_message("Timestamp unavailable.", raw) for raw in invalid_times
        ])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["missing_timestamps"], 7)
        self.assertEqual(coverage[0]["status"], "incomplete")

    def test_invalid_windows_and_harness_fail_explicitly(self):
        for start, end in ((datetime(2030, 10, 19), END), (START, START), (END, START)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                collector.collect([], start, end)
        with self.assertRaises(ValueError):
            collector.collect([("invented-harness", self.root)], START, END)

    def test_prefix_colliding_sessions_and_duplicate_inputs_have_stable_distinct_ids(self):
        first = self.write_records("12345678-aaaa-4000-8000-000000000001.jsonl", [self.claude_message()])
        self.write_records("12345678-bbbb-4000-8000-000000000002.jsonl", [self.claude_message()])
        events, coverage = collector.collect([("claude-code", self.root), ("claude-code", first)], START, END)
        self.assertEqual(len(events), 2)
        self.assertEqual(len({event["session"] for event in events}), 2)
        self.assertTrue(all(len(event["session"]) == 64 for event in events))
        self.assertEqual(coverage[1]["duplicate_files"], 1)
        single, _ = collector.collect([("claude-code", first)], START, END)
        self.assertIn(single[0]["id"], {event["id"] for event in events})

    def test_multi_block_event_ids_do_not_depend_on_selected_window(self):
        all_events, _ = self.collect_fixture("claude-code", "claude.jsonl")
        subset, _ = collector.collect([("claude-code", FIXTURES / "claude.jsonl")],
                                      datetime(2030, 10, 19, 8, 2, tzinfo=timezone.utc), END)
        self.assertEqual([event["id"] for event in subset], [event["id"] for event in all_events if event["line"] >= 3])

    def test_malformed_lines_and_unknown_schemas_cannot_look_like_success(self):
        path = self.root / "malformed.jsonl"
        path.write_bytes(b'not-json\n[]\n\xff\n{"value":NaN}\n' +
                         json.dumps({"type": "future_schema", "payload": {"text": "Unknown."}}).encode() + b'\n' +
                         json.dumps(self.claude_message("Valid record after damage.")).encode() + b'\n')
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], ["Valid record after damage."])
        self.assertEqual(events[0]["line"], 6)
        self.assertEqual(coverage[0]["malformed_records"], 4)
        self.assertEqual(coverage[0]["unsupported_records"], 1)
        self.assertEqual(coverage[0]["status"], "partial")
        unknown = self.write_records("unknown.jsonl", [{"type": "invented", "content": "Unknown."}])
        _, stats = collector.collect([("claude-code", unknown)], START, END)
        self.assertFalse(stats[0]["schema_recognized"])
        self.assertEqual(stats[0]["status"], "unsupported")

    def test_malformed_nested_envelopes_are_counted_not_crashes(self):
        cases = {
            "claude-code": [{"type": []}, {"type": "user", "message": []}, {"type": "user", "message": {"role": "user", "content": [{"type": [], "text": "Bad block."}]}}],
            "codex": [{"type": {}}, {"type": "response_item", "payload": {"type": []}}, {"type": "response_item", "payload": {"type": "message", "role": [], "content": "Bad role."}}],
            "openclaw": [{"type": []}, {"type": "message", "message": {"role": [], "content": "Bad role."}}, {"type": "message", "message": {"role": "user", "content": "Bad attribution.", "__openclaw": []}}],
        }
        for harness, rows in cases.items():
            with self.subTest(harness=harness):
                path = self.write_records(harness + ".jsonl", rows)
                events, coverage = collector.collect([(harness, path)], START, END)
                self.assertEqual(events, [])
                self.assertGreaterEqual(coverage[0]["malformed_records"], 3)
                self.assertNotEqual(coverage[0]["status"], "ok")

    def test_missing_empty_and_compressed_sources_have_honest_coverage(self):
        missing = self.root / "missing.jsonl"
        empty = self.write_records("empty.jsonl", [])
        compressed = self.root / "rollout.jsonl.zst"
        compressed.write_bytes(b"synthetic, intentionally not a compressed transcript")
        events, coverage = collector.collect([("codex", missing), ("codex", empty), ("codex", compressed)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(len(coverage), 3)
        self.assertFalse(coverage[0]["available"])
        self.assertEqual(coverage[0]["unavailable_files"], 1)
        self.assertEqual(coverage[0]["status"], "unavailable")
        self.assertEqual(coverage[1]["status"], "no_events")
        self.assertEqual(coverage[2]["compressed_files"], 1)
        self.assertEqual(coverage[2]["unavailable_files"], 1)
        self.assertEqual(coverage[2]["status"], "unsupported")
        _, directory_coverage = collector.collect([("codex", self.root)], START, END)
        self.assertEqual(directory_coverage[0]["compressed_files"], 1)

    def test_unreadable_file_is_counted(self):
        path = self.write_records("unreadable.jsonl", [self.claude_message()])
        real_open = os.open
        def deny_target(target, *args, **kwargs):
            if Path(target) == path.resolve():
                raise PermissionError("Synthetic permission failure")
            return real_open(target, *args, **kwargs)
        with patch.object(os, "open", side_effect=deny_target):
            events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unreadable_files"], 1)
        self.assertEqual(coverage[0]["status"], "unreadable")

    def test_input_and_descendant_symlinks_do_not_escape_source_root(self):
        source = self.write_records("outside/source.jsonl", [self.claude_message("Outside the selected root.")])
        selected = self.root / "selected"
        selected.mkdir()
        try:
            (selected / "file-link.jsonl").symlink_to(source)
            (selected / "dir-link").symlink_to(source.parent, target_is_directory=True)
            root_link = self.root / "root-link"
            root_link.symlink_to(source.parent, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        events, coverage = collector.collect([("claude-code", selected), ("claude-code", root_link)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["symlink_paths"], 2)
        self.assertEqual(coverage[1]["symlink_paths"], 1)
        self.assertFalse(coverage[1]["available"])

    def test_home_paths_tokens_and_path_labels_are_best_effort_redacted(self):
        token = "sk-" + "SYNTHETIC0123456789" * 2
        gh_token = "ghp_" + "SYNTHETIC0123456789" * 2
        text = (f"Home {Path.home()}/private/file; other /home/synthetic-person/project; "
                "Windows C:\\Users\\synthetic-person\\project; "
                f"tokens {token} {gh_token}; api_key='SYNTHETIC-KEY'; "
                '"access_token": "SYNTHETIC-ACCESS"; Authorization: Bearer SYNTHETIC-BEARER')
        path = self.write_records(token + ".jsonl", [self.claude_message(text)])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        serialized = json.dumps((events, coverage))
        for sensitive in (str(Path.home()), "synthetic-person", token, gh_token, "SYNTHETIC-KEY", "SYNTHETIC-ACCESS", "SYNTHETIC-BEARER"):
            self.assertNotIn(sensitive, serialized)
        self.assertIn("~/private/file", events[0]["text"])
        self.assertIn("~\\project", events[0]["text"])
        self.assertIn("[REDACTED]", events[0]["source"])

    def test_control_characters_in_source_names_are_escaped(self):
        if os.name == "nt":
            self.skipTest("Windows disallows this synthetic filename")
        path = self.write_records("line\nbreak.jsonl", [self.claude_message()])
        events, _ = collector.collect([("claude-code", path)], START, END)
        self.assertEqual(events[0]["source"], "line\\x0abreak.jsonl")

    def test_truncation_is_flagged_and_bounded_after_sanitizing(self):
        path = self.write_records("long.jsonl", [self.claude_message("x" * (collector.MAX_EVENT_CHARS + 100))])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertTrue(events[0]["truncated"])
        self.assertEqual(len(events[0]["text"]), collector.MAX_EVENT_CHARS)
        self.assertTrue(events[0]["text"].endswith("[TRUNCATED: consult the original local transcript]"))
        self.assertEqual(coverage[0]["truncated_events"], 1)

    def test_markdown_fences_inline_markup_and_normal_instruction_headings_survive(self):
        prompts = [
            "```xml\n<system-reminder>Literal example requested by the user.</system-reminder>\n```",
            "Explain <task-notification> without treating my example as a task.",
            "# User instructions\nDo not drop this heading.",
            "# AGENTS.md instructions for this example\nThese are my real instructions, without an injected wrapper.",
        ]
        path = self.write_records("literal-markup.jsonl", [self.claude_message(text) for text in prompts])
        events, _ = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], prompts)

    def test_known_delegated_paths_and_openclaw_headers_are_excluded(self):
        paths = [self.write_records(name, [self.claude_message("Delegated task.")]) for name in ("agent-worker.jsonl", "subagents/worker.jsonl")]
        openclaw = self.write_records("openclaw-child.jsonl", [
            {"type": "message", "timestamp": "2030-10-19T10:00:00Z", "message": {"role": "user", "content": "Late-header delegated task."}},
            {"type": "session", "sessionKey": "agent:main:subagent:synthetic"},
        ])
        events, coverage = collector.collect([*(('claude-code', path) for path in paths), ("openclaw", openclaw)], START, END)
        self.assertEqual(events, [])
        self.assertTrue(all(stats["delegated_records"] > 0 for stats in coverage))

    def test_non_subagent_codex_source_dict_is_not_blanket_excluded(self):
        path = self.write_records("codex-source.jsonl", [
            {"type": "session_meta", "payload": {"source": {"cli": "synthetic"}}},
            {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "message", "role": "user", "content": "A normal prompt."}},
        ])
        events, _ = collector.collect([("codex", path)], START, END)
        self.assertEqual([event["text"] for event in events], ["A normal prompt."])

    def test_collector_imports_no_process_network_or_database_clients(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "scripts" / "collect.py").read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertFalse(imports & {"subprocess", "sqlite3", "socket", "urllib", "http", "requests"})

    def test_event_limit_is_global_and_retains_missing_path_coverage(self):
        path = self.write_records("many.jsonl", [self.claude_message(str(index)) for index in range(4)])
        missing = self.root / "missing.jsonl"
        with patch.object(collector, "MAX_EVENTS", 2):
            events, coverage = collector.collect([("claude-code", path), ("codex", missing)], START, END)
        self.assertEqual(len(events), 2)
        self.assertEqual(coverage[0]["status"], "limited")
        self.assertGreater(coverage[0]["event_limit_reached"], 0)
        self.assertEqual(coverage[1]["status"], "unavailable")
        self.assertEqual(len(coverage), 2)

    def test_file_and_path_limits_are_reported(self):
        for name in ("one.jsonl", "two.jsonl", "three.jsonl"):
            self.write_records(name, [self.claude_message(name)])
        with patch.object(collector, "MAX_FILES", 1):
            events, coverage = collector.collect([("claude-code", self.root)], START, END)
        self.assertEqual(len(events), 1)
        self.assertEqual(coverage[0]["files"], 1)
        self.assertEqual(coverage[0]["status"], "limited")
        with patch.object(collector, "MAX_PATHS", 1):
            _, coverage = collector.collect([("claude-code", self.root)], START, END)
        self.assertGreater(coverage[0]["limited_paths"], 0)
        self.assertEqual(coverage[0]["status"], "limited")

    def test_record_cap_fails_closed_when_late_provenance_cannot_be_scanned(self):
        path = self.write_records("late-meta.jsonl", [
            {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "message", "role": "user", "content": "Do not misattribute this."}},
            {"type": "session_meta", "payload": {"source": {"subagent": "synthetic"}}},
        ])
        with patch.object(collector, "MAX_RECORDS_PER_FILE", 1):
            events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["limited_files"], 1)
        self.assertEqual(coverage[0]["incomplete_files"], 1)
        self.assertEqual(coverage[0]["status"], "limited")

    def test_per_file_and_total_byte_caps_never_emit_partial_scan_events(self):
        path = self.write_records("bytes.jsonl", [self.claude_message("Synthetic " * 30)])
        for cap in ("MAX_BYTES_PER_FILE", "MAX_TOTAL_BYTES"):
            with self.subTest(cap=cap), patch.object(collector, cap, 50):
                events, coverage = collector.collect([("claude-code", path)], START, END)
                self.assertEqual(events, [])
                self.assertLessEqual(coverage[0]["bytes_read"], 50)
                self.assertEqual(coverage[0]["limited_files"], 1)
                self.assertEqual(coverage[0]["status"], "limited")

    def test_oversized_line_at_byte_cap_counts_one_limited_file(self):
        path = self.write_records("oversized.jsonl", [self.claude_message("x" * 1000)])
        with patch.object(collector, "MAX_LINE_BYTES", 32), patch.object(collector, "MAX_BYTES_PER_FILE", 64):
            events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["oversized_lines"], 1)
        self.assertEqual(coverage[0]["limited_files"], 1)
        self.assertEqual(coverage[0]["incomplete_files"], 1)

    def test_depth_limit_and_maximum_inputs_are_explicit(self):
        self.write_records("nested/deeper/message.jsonl", [self.claude_message()])
        with patch.object(collector, "MAX_DEPTH", 0):
            events, coverage = collector.collect([("claude-code", self.root)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["limited_paths"], 1)
        with patch.object(collector, "MAX_INPUTS", 1), self.assertRaises(ValueError):
            collector.collect([("claude-code", self.root), ("codex", self.root)], START, END)

    def test_json_unicode_surrogates_do_not_break_utf8_output(self):
        path = self.write_records("unicode.jsonl", [self.claude_message("Literal escaped surrogate: \ud800")])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        encoded = json.dumps((events, coverage), ensure_ascii=False).encode("utf-8")
        self.assertIn(b"Literal escaped surrogate", encoded)

    def test_event_only_codex_history_is_not_reported_as_a_supported_empty_day(self):
        path = self.write_records("event-only.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "No canonical response item was exported."}},
        ])
        events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unsupported_records"], 1)
        self.assertEqual(coverage[0]["status"], "unsupported")

    def test_utf8_bom_does_not_hide_delegation_metadata(self):
        path = self.write_records("bom.jsonl", [
            {"type": "session_meta", "payload": {"source": {"subagent": "synthetic"}}},
            {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {
                "type": "message", "role": "user", "content": "Delegated prompt after a UTF-8 BOM.",
            }},
        ])
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["malformed_records"], 0)
        self.assertGreater(coverage[0]["delegated_records"], 0)

    def test_source_parses_with_python_310_grammar(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "collect.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 10))

    def test_middle_injected_context_and_notifications_are_not_human_evidence(self):
        path = self.write_records("middle-context.jsonl", [
            self.claude_message("Context:\n[[OPENCLAW_INTERNAL_CONTEXT_BEGIN]]\n[Subagent Task]\nSynthetic delegated assignment.\n[[OPENCLAW_INTERNAL_CONTEXT_END]]"),
            self.claude_message("Before the generated block.\n\n<system-reminder>Injected context.</system-reminder>\n\nAfter the generated block."),
            self.claude_message("Preface:\n[Inter-session message] sourceSession=synthetic\nSynthetic relay."),
        ])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], [
            "Before the generated block.\n\nAfter the generated block.",
        ])
        self.assertEqual(coverage[0]["excluded_records"], 2)

    def test_markdown_indentation_and_hard_line_breaks_are_preserved_exactly(self):
        prompts = [
            "    print(1)\n    print(2)",
            "    <system-reminder>Literal indented code.</system-reminder>",
            "A Markdown hard break.  \nNext line.  ",
            "```text\n[[OPENCLAW_INTERNAL_CONTEXT_BEGIN]]\n[Subagent Task]\nA literal code example.\n[[OPENCLAW_INTERNAL_CONTEXT_END]]\n```",
        ]
        path = self.write_records("markdown-spacing.jsonl", [self.claude_message(text) for text in prompts])
        events, _ = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["text"] for event in events], prompts)

    def test_paginated_mode_still_excludes_delegated_and_exec_sessions(self):
        rows = [json.loads(line) for line in (FIXTURES / "codex-paginated.jsonl").read_text(encoding="utf-8").splitlines()]
        for source in ({"subagent": {"thread_spawn": {"parent_thread_id": "synthetic"}}}, "exec"):
            with self.subTest(source=source):
                rows[0]["payload"]["source"] = source
                path = self.write_records("paginated-automated.jsonl", rows)
                events, coverage = collector.collect([("codex", path)], START, END)
                self.assertEqual(events, [])
                self.assertGreater(coverage[0]["excluded_records"], 0)

    def test_unknown_codex_history_modes_fail_closed(self):
        for mode in ("future", [], {}):
            with self.subTest(mode=mode):
                path = self.write_records("unknown-mode.jsonl", [
                    {"type": "session_meta", "payload": {"source": "cli", "history_mode": mode}},
                    {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "message", "role": "user", "content": "Cannot infer the authoritative stream."}},
                ])
                events, coverage = collector.collect([("codex", path)], START, END)
                self.assertEqual(events, [])
                self.assertEqual(coverage[0]["unsupported_history_files"], 1)
                self.assertEqual(coverage[0]["status"], "unsupported")

    def test_recent_session_is_not_starved_by_more_than_512_older_exports(self):
        for index in range(520):
            old = self.write_records(f"archive/old-{index:04}.jsonl", [self.claude_message("Old evidence.", "2025-01-01T10:00:00Z")])
            os.utime(old, (1735725600, 1735725600))
        recent = self.write_records("archive/z-current.jsonl", [self.claude_message("Yesterday's relevant session.")])
        os.utime(recent, (1792404000, 1792404000))
        events, coverage = collector.collect([("claude-code", self.root)], START, END)
        self.assertEqual([event["text"] for event in events], ["Yesterday's relevant session."])
        self.assertEqual(coverage[0]["files"], 512)
        self.assertEqual(coverage[0]["status"], "limited")
        self.assertGreater(coverage[0]["limited_files"], 0)

    def test_longer_than_8mib_session_and_large_tool_line_work_with_defaults(self):
        path = self.write_records("ordinary-long.jsonl", [
            self.claude_message("Keep the important steering prompt."),
            {"type": "user", "timestamp": "2030-10-19T10:01:00Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "x" * (9 * 1024 * 1024)},
            ]}},
            {"type": "assistant", "timestamp": "2030-10-19T10:02:00Z", "message": {"role": "assistant", "content": "Verification after a large tool result."}},
        ])
        events, coverage = collector.collect([("claude-code", path)], START, END)
        self.assertEqual([event["role"] for event in events], ["human", "tool", "assistant"])
        self.assertEqual(events[-1]["text"], "Verification after a large tool result.")
        self.assertTrue(events[1]["truncated"])
        self.assertEqual(coverage[0]["incomplete_files"], 0)
        self.assertEqual(coverage[0]["status"], "ok")

    def test_scan_limits_can_be_raised_by_caller_without_source_edits(self):
        path = self.write_records("configured.jsonl", [self.claude_message("A complete prompt under caller-selected caps.")])
        with patch.object(collector, "MAX_BYTES_PER_FILE", 40), patch.object(collector, "MAX_TOTAL_BYTES", 40):
            events, coverage = collector.collect([("claude-code", path)], START, END, limits={
                "max_bytes_per_file": 1024, "max_total_bytes": 1024,
            })
        self.assertEqual(len(events), 1)
        self.assertEqual(coverage[0]["limits"]["max_bytes_per_file"], 1024)
        for limits in ({"imaginary_limit": 1}, {"max_files": 0}, {"max_files": True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                collector.collect([], START, END, limits=limits)

    def test_input_roots_share_file_budget_instead_of_starving_later_harness(self):
        for name in ("old-a.jsonl", "old-b.jsonl", "old-c.jsonl"):
            path = self.write_records("claude/" + name, [self.claude_message("Older export.", "2025-01-01T00:00:00Z")])
            os.utime(path, (1735689600, 1735689600))
        recent = self.write_records("claude/recent.jsonl", [self.claude_message("Recent Claude prompt.")])
        os.utime(recent, (1792404000, 1792404000))
        codex = self.write_records("codex/recent.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli", "history_mode": "legacy"}},
            {"type": "response_item", "timestamp": "2030-10-19T11:00:00Z", "payload": {"type": "message", "role": "user", "content": "Recent Codex prompt."}},
        ])
        events, coverage = collector.collect([("claude-code", recent.parent), ("codex", codex.parent)], START, END,
                                             limits={"max_files": 2})
        self.assertEqual([event["text"] for event in events], ["Recent Claude prompt.", "Recent Codex prompt."])
        self.assertEqual([stats["files"] for stats in coverage], [1, 1])
        self.assertEqual(coverage[0]["status"], "limited")
        self.assertEqual(coverage[1]["status"], "ok")

    def test_paginated_plan_and_typed_tool_results_are_assistant_or_tool_not_human(self):
        items = [
            {"type": "Plan", "id": "plan-1", "text": "Verify the synthetic boundary."},
            {"type": "DynamicToolCall", "id": "dynamic-1", "tool": "synthetic_tool", "arguments": {"safe": True}, "status": "completed", "content_items": [{"type": "input_text", "text": "A synthetic result."}], "success": True},
            {"type": "McpToolCall", "id": "mcp-1", "server": "synthetic-server", "tool": "verify", "arguments": {}, "status": "completed", "result": {"content": [{"type": "text", "text": "Verified."}]}, "error": None},
            {"type": "HookPrompt", "id": "hook-1", "fragments": [{"text": "Automated hook instructions.", "hookRunId": "synthetic-hook"}]},
        ]
        path = self.write_records("typed-items.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli", "history_mode": "paginated"}},
            *({"type": "event_msg", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "item_completed", "item": item}} for item in items),
        ])
        events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual([event["role"] for event in events], ["assistant", "tool_call", "tool", "tool_call", "tool"])
        self.assertTrue(events[3]["text"].startswith("synthetic-server/verify "))
        self.assertIn("Verified.", events[4]["text"])
        self.assertEqual(coverage[0]["human_events"], 0)
        self.assertEqual(coverage[0]["unsupported_records"], 0)

    def test_unknown_paginated_items_are_reported_and_bad_items_do_not_crash(self):
        path = self.write_records("unknown-items.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli", "history_mode": "paginated"}},
            {"type": "event_msg", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "item_completed", "item": {"type": "FutureItem", "id": "future-1"}}},
            {"type": "event_msg", "timestamp": "2030-10-19T10:01:00Z", "payload": {"type": "item_completed", "item": {"type": [], "id": "bad-1"}}},
        ])
        events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unsupported_records"], 1)
        self.assertEqual(coverage[0]["malformed_records"], 1)
        self.assertEqual(coverage[0]["status"], "unsupported")

    def test_codex_inherited_context_and_compaction_are_not_original_messages(self):
        path = self.write_records("inherited.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli", "history_mode": "legacy"}},
            {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "metadata": {"inherited_user_message": True}, "payload": {"type": "message", "role": "user", "content": "Copied parent context."}},
            {"type": "response_item", "timestamp": "2030-10-19T10:01:00Z", "metadata": {"compaction_output": True}, "payload": {"type": "message", "role": "assistant", "content": "A generated compaction summary."}},
        ])
        events, coverage = collector.collect([("codex", path)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unsupported_records"], 0)
        damaged = self.write_records("damaged-header.jsonl", [
            {"type": "session_meta", "payload": []},
            {"type": "response_item", "timestamp": "2030-10-19T10:00:00Z", "payload": {"type": "message", "role": "user", "content": "Cannot safely select a stream."}},
        ])
        events, coverage = collector.collect([("codex", damaged)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unsupported_history_files"], 1)
        self.assertEqual(coverage[0]["malformed_records"], 1)

    def test_completed_item_timestamp_fallback_and_conflicting_modes(self):
        item_row = {"type": "event_msg", "payload": {"type": "item_completed", "completed_at_ms": int(START.replace(hour=10).timestamp() * 1000),
                    "item": {"type": "AgentMessage", "id": "message-1", "content": [{"type": "Text", "text": "Timestamp fallback."}]}}}
        header = {"type": "session_meta", "payload": {"source": "cli", "history_mode": "paginated"}}
        path = self.write_records("timestamp-fallback.jsonl", [header, item_row])
        events, _ = collector.collect([("codex", path)], START, END)
        self.assertEqual(events[0]["timestamp"], "2030-10-19T10:00:00+00:00")
        conflicting = self.write_records("conflicting.jsonl", [header, item_row,
                        {"type": "session_meta", "payload": {"source": "cli", "history_mode": "legacy"}}])
        events, coverage = collector.collect([("codex", conflicting)], START, END)
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]["unsupported_history_files"], 1)


if __name__ == "__main__":
    unittest.main()
