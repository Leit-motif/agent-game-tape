"""Bounded, read-only JSONL adapters for Claude Code, Codex, and OpenClaw exports.

collect(inputs, start, end) returns (events, coverage), one coverage entry per input.
The window is half-open [start, end); both bounds must be aware datetimes. Event
IDs use the full SHA-256 of harness + canonical source path, physical line, and
within-line ordinal, independent of the selected window. `session` identifies a
source file, NOT a claimed cross-file conversation. Sources are relative to the
input directory, or a basename for a file input; no absolute source paths leak.

Coverage `available` means the input path exists and is a regular file/directory,
not that it yielded usable evidence. Consult `status` and counters: unreadable,
malformed, missing timestamps (candidate events), excluded, unsupported, and
unavailable files. `recognized_records` counts known envelopes, not acceptance.
Counters can overlap (e.g. delegated records are also excluded). All limits below
are hard local scan/output caps; reaching one is reported, never a full scan.
Files are discovered before the file cap is applied, then read newest-mtime first
(across subdirectories), so years of old exports do not starve recent sessions.
Modification time is a priority hint, NOT evidence that a file is outside the
requested window. All discovered files remain eligible. Discovery itself is
bounded and reported; no completeness is claimed when a cap is reached. File
and byte budgets are shared fairly across remaining input roots. Callers can
raise/lower positive caps with collect(..., limits={"max_bytes_per_file": ...,
"max_total_bytes": ...}); effective limits and each root's budget are reported.
A file whose byte/line/record scan was cut short yields no events, so unseen late
session metadata cannot turn a delegated prompt into a human call.

Only JSONL exports are read. No live databases, subprocesses, or network access.
Compressed JSONL is explicitly unsupported, including Codex .jsonl.zst. Codex
selects one authoritative stream using session_meta.payload.history_mode:
legacy (also the absent-field default) uses response_item; paginated uses
completed TurnItems in event_msg.item_completed, never legacy user_message or
agent_message notifications. Raw response items are skipped in paginated mode
so duplicate messages/tool evidence cannot be counted twice. Supported completed
items: UserMessage, AgentMessage, Plan, CommandExecution, FunctionCallOutput,
DynamicToolCall, and McpToolCall. Other durable items are explicitly counted as
unsupported; hidden reasoning, hooks, and task activity are excluded. Schema
verified against openai/codex rust-v0.163.0 (commit83086188ae0614bd882818ff1aa23f3194962012):
codex-rs/protocol/src/{protocol,items,user_input}.rs, history/src/rollout_payload.rs,
and rollout/src/policy.rs.
Unknown or contradictory history modes fail closed. Inherited history references
are not followed; collection is of the supplied physical export files only.
Claude meta/sidechain/team/compaction and known SDK/ACP prompts are excluded.
Codex subagent and exec sessions and explicitly delegated OpenClaw sessions are
excluded, even if metadata occurs after messages. Missing provenance remains a
limit: `human` means a user-role prompt minus known generated/automated material;
it is not proof of a person's authorship. OpenClaw exports may lack owner/session
metadata; do not infer identity from those omissions. Unknown record types and
unsupported content blocks are counted, not silently accepted. Assistant commentary is retained, not hidden
reasoning. Non-text media is not transcribed. Input symlinks and symlink descendants
are skipped; ordinary ancestor aliases are canonicalized. This is not a sandbox
against concurrent directory replacement; collect stable exports.

Redaction is BEST EFFORT, NOT anonymization or upload approval. It masks common
home-directory prefixes and recognizable API-token/assignment/bearer patterns,
but can miss secrets, personal information, private code, and unusual paths. Text
can still be sensitive. Review locally before sharing; raw events are not a safe
publication artifact. Only synthetic fixtures belong in the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Per collect() call unless explicitly named per-file/per-event.
MAX_INPUTS = 64
MAX_FILES = 512
MAX_PATHS = 20_000
MAX_DEPTH = 32
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_BYTES_PER_FILE = 64 * 1024 * 1024
MAX_RECORDS_PER_FILE = 100_000
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 10_000
MAX_EVENT_CHARS = 16_000
TRUNCATION = "\n[TRUNCATED: consult the original local transcript]"

SECRETS = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b")
ASSIGNMENT = re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|password|secret)[\"']?\s*[:=]\s*)[\"']?[^\s\"',;}]+[\"']?")
BEARER = re.compile(r"(?i)(\bauthorization[\"']?\s*:\s*[\"']?bearer\s+)[^\s\"']+")
POSIX_HOME = re.compile(r"(?<![\w/])/(?:Users|home)/[^/\s\"'<>:]+")
WINDOWS_HOME = re.compile(r"(?i)(?<![\w])(?:[a-z]:[\\/](?:Users|Documents and Settings)[\\/])[^\\/\s\"'<>:]+")
INTERNAL = (
    "[Inter-session message]", "[OpenClaw session event]", "[Subagent Task]",
    "[Subagent Context]", "[cron:",
    "Caveat: The messages below were generated by the user while running local commands.",
)
INJECTED_TAGS = (
    "task-notification", "system-reminder", "subagent_notification",
    "environment_context", "permissions instructions", "relay",
    "local-command-stdout", "local-command-stderr",
)
TEXT_BLOCKS = {"text", "input_text", "output_text"}
NON_TEXT_BLOCKS = {"image", "input_image", "image_url", "audio", "input_audio", "document"}
CLAUDE_METADATA = {"system", "summary", "progress", "file-history-snapshot", "queue-operation", "last-prompt", "pr-link"}
CODEX_METADATA = {"turn_context", "compacted", "token_usage_record", "world_state", "retained_context", "security_risk_score", "inter_agent_communication", "inter_agent_communication_metadata"}
CODEX_NOISE = {"token_count", "task_started", "task_complete", "turn_started", "turn_complete", "turn_aborted", "error", "warning", "context_compacted", "agent_reasoning", "agent_reasoning_raw_content", "item_started", "thread_goal_updated", "thread_rolled_back", "thread_settings_applied"}
OPENCLAW_METADATA = {"session", "model_change", "thinking_level_change", "custom", "custom_message", "compaction", "branch_summary", "label"}
COMPRESSED_SUFFIXES = (".jsonl.zst", ".jsonl.gz", ".jsonl.bz2", ".jsonl.xz", ".jsonl.zip")
RawEvent = tuple[int, Any, str, str]
Stats = dict[str, Any]


def sanitize(text: str) -> str:
    """Best-effort masking only; callers must still perform a privacy review."""
    # JSON can encode lone surrogates; keep returned artifacts UTF-8 writable.
    text = text.encode("utf-8", errors="backslashreplace").decode("utf-8")
    home = str(Path.home())
    if home not in ("/", "."):
        text = re.sub(re.escape(home) + r"(?=$|[/\\\s\"'<>:])", "~", text)
    text = POSIX_HOME.sub("~", text)
    text = WINDOWS_HOME.sub("~", text)
    text = SECRETS.sub("[REDACTED]", text)
    text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
    return BEARER.sub(r"\1[REDACTED]", text)


def _path_label(path: Path | str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", lambda match: f"\\x{ord(match[0]):02x}", sanitize(str(path)))


def timestamp(value: Any) -> datetime | None:
    """Parse an aware ISO timestamp or Unix seconds/milliseconds, normalized to UTC."""
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000 if abs(value) >= 10**11 else value, timezone.utc)
        if not isinstance(value, str):
            return None
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return dt.astimezone(timezone.utc) if dt.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(block["text"] for block in content if isinstance(block, dict)
                     and block.get("type") in TEXT_BLOCKS and isinstance(block.get("text"), str))


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """Protect literal Markdown code fences, including an unfinished final fence."""
    spans = []
    fence = ""
    start = offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if not fence and match:
            fence, start = match[1], offset
        elif fence and re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*(?:\r?\n)?", line):
            spans.append((start, offset + len(line)))
            fence = ""
        offset += len(line)
    if fence:
        spans.append((start, len(text)))
    return spans


def human_text(text: str) -> str:
    """Remove line-delimited generated blocks anywhere, preserving literal Markdown.

    Known wrappers at ordinary line starts are treated as generated; fenced and
    four-space/tab-indented examples are literal. This is not a general Markdown
    parser or an authorship oracle. No whitespace is stripped from an untouched
    prompt: leading indentation and trailing Markdown hard breaks are evidence.
    """
    try:
        envelope = json.loads(text) if text.lstrip().startswith("{") else None
        if isinstance(envelope, dict) and any(envelope.get(key) == "chatgpt-web-cli.async.delivery" for key in ("type", "kind", "event", "method")):
            return ""
    except (ValueError, RecursionError):
        pass
    protected = _fenced_spans(text)
    protected_starts = [start for start, _ in protected]

    def in_code(position: int) -> bool:
        index = bisect_right(protected_starts, position) - 1
        return index >= 0 and position < protected[index][1]

    removals: list[tuple[int, int]] = []

    def remove_blocks(opening: str, closing: str, internal: bool = False) -> bool:
        after = 0
        for match in re.finditer(opening, text, re.MULTILINE):
            if match.start() < after or in_code(match.start()):
                continue
            close = text.find(closing, match.end())
            end = len(text) if close < 0 else close + len(closing)
            if internal and (close < 0 or "[Subagent" in text[match.end():end]):
                return True  # A delegated assignment is not an owner prompt.
            removals.append((match.start(), end))
            after = end
        return False

    for tag in INJECTED_TAGS:
        remove_blocks(r"^ {0,3}<" + re.escape(tag) + r"(?:[ \t][^\r\n>]*|)>", "</" + tag + ">")
    remove_blocks(r"^ {0,3}# AGENTS\.md instructions for [^\r\n]+\r?\n[ \t\r\n]*<INSTRUCTIONS>", "</INSTRUCTIONS>")
    date_prefix = r"(?:\[[^\r\n]{1,100}\][ \t]+)?"
    if remove_blocks(r"^ {0,3}" + date_prefix + r"\[\[OPENCLAW_INTERNAL_CONTEXT_BEGIN\]\]", "[[OPENCLAW_INTERNAL_CONTEXT_END]]", internal=True):
        return ""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(removals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    removed_starts = [start for start, _ in merged]
    for match in re.finditer(r"^ {0,3}" + date_prefix + r"(?:" + "|".join(re.escape(prefix) for prefix in INTERNAL) + ")", text, re.MULTILINE):
        index = bisect_right(removed_starts, match.start()) - 1
        already_removed = index >= 0 and match.start() < merged[index][1]
        if not in_code(match.start()) and not already_removed:
            return ""
    if not merged:
        return text
    result = text
    for start, end in reversed(merged):
        left, right = result[:start], result[end:]
        if left.endswith(("\r", "\n")) and right.startswith(("\r", "\n")):
            right = right.lstrip("\r\n")  # Do not double a removed block's separators.
        result = left + right
    return result.strip("\r\n")


def _human_content(content: Any) -> str:
    if isinstance(content, str):
        return human_text(content)
    if not isinstance(content, list):
        return ""
    return "\n".join(part for block in content if isinstance(block, dict)
                     and block.get("type") in TEXT_BLOCKS and isinstance(block.get("text"), str)
                     if (part := human_text(block["text"])))


def _body(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _unsupported(stats: Stats) -> None:
    stats["unsupported_records"] += 1


def _content_valid(content: Any, allowed: set[str], stats: Stats) -> bool:
    if not isinstance(content, (str, list)):
        stats["malformed_records"] += 1
        return False
    if isinstance(content, list):
        if any(not isinstance(block, dict) or not isinstance(block.get("type"), str)
               or (block.get("type") in TEXT_BLOCKS and not isinstance(block.get("text"), str)) for block in content):
            stats["malformed_records"] += 1
            return False
        if any(block["type"] not in allowed | TEXT_BLOCKS | NON_TEXT_BLOCKS for block in content):
            _unsupported(stats)
    return True


def _metadata_sources(obj: dict) -> Iterator[dict]:
    yield obj
    for key in ("origin", "metadata", "meta", "message"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            yield nested
            for subkey in ("origin", "metadata", "meta"):
                if isinstance(nested.get(subkey), dict):
                    yield nested[subkey]


def _automated_claude(obj: dict) -> bool:
    for meta in _metadata_sources(obj):
        prompt_source = str(meta.get("promptSource", "")).lower()
        entrypoint = str(meta.get("entrypoint", "")).lower()
        if prompt_source in {"sdk", "acp", "api", "automation"} or entrypoint.startswith(("sdk", "acp")):
            return True
    return False


def _json_rows(path: Path, stats: Stats, budget: Stats) -> list[tuple[int, dict]]:
    """Read bounded physical lines, rejecting non-finite JSON numbers and symlink leaves."""
    rows: list[tuple[int, dict]] = []
    limits = budget["limits"]
    incomplete = False
    io_failed = False
    read_bytes = 0
    number = 0
    oversized = False
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                stats["unavailable_files"] += 1
                return []
            handle = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            while True:
                allowance = min(limits["max_bytes_per_file"] - read_bytes, budget["bytes"], budget["input_bytes"])
                if allowance <= 0 or number >= limits["max_records_per_file"]:
                    incomplete = True
                    break
                chunk = handle.readline(min(limits["max_line_bytes"] + 1, allowance))
                if not chunk:
                    break
                number += 1
                stats["lines"] += 1
                read_bytes += len(chunk)
                budget["bytes"] -= len(chunk)
                budget["input_bytes"] -= len(chunk)
                stats["bytes_read"] += len(chunk)
                if not chunk.endswith(b"\n") and len(chunk) == allowance and len(chunk) <= limits["max_line_bytes"]:
                    incomplete = True  # The byte budget cut a physical line short.
                    break
                if len(chunk) > limits["max_line_bytes"]:
                    # Discard the rest of the physical line without allocating it.
                    stats["oversized_lines"] += 1
                    oversized = True
                    while chunk and not chunk.endswith(b"\n"):
                        allowance = min(limits["max_bytes_per_file"] - read_bytes, budget["bytes"], budget["input_bytes"])
                        if allowance <= 0:
                            incomplete = True
                            break
                        chunk = handle.readline(min(limits["max_line_bytes"] + 1, allowance))
                        read_bytes += len(chunk)
                        budget["bytes"] -= len(chunk)
                        budget["input_bytes"] -= len(chunk)
                        stats["bytes_read"] += len(chunk)
                    if incomplete:
                        break
                    continue
                try:
                    obj = json.loads(chunk.decode("utf-8-sig" if number == 1 else "utf-8"), parse_constant=_reject_constant)
                    if not isinstance(obj, dict):
                        raise ValueError("JSONL record is not an object")
                    rows.append((number, obj))
                except (ValueError, UnicodeError, RecursionError):
                    stats["malformed_records"] += 1
    except OSError:
        stats["unreadable_files"] += 1
        io_failed = True
        incomplete = True
    if incomplete or oversized:
        stats["incomplete_files"] += 1
        if oversized or not io_failed:
            stats["limited_files"] += 1
        return []
    stats["read_files"] += 1
    return rows


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite number in JSON")


def claude_records(path: Path, stats: Stats, budget: Stats) -> Iterator[RawEvent]:
    delegated = "subagents" in path.parts or path.name.startswith("agent-")
    for line, obj in _json_rows(path, stats, budget):
        kind = obj.get("type")
        if not isinstance(kind, str):
            stats["malformed_records"] += 1
            continue
        if kind in CLAUDE_METADATA:
            stats["recognized_records"] += 1
            stats["excluded_records"] += 1
            continue
        if kind not in ("user", "assistant"):
            _unsupported(stats)
            continue
        stats["recognized_records"] += 1
        if delegated or obj.get("isSidechain") or obj.get("teamName"):
            stats["delegated_records"] += 1
            stats["excluded_records"] += 1
            continue
        if obj.get("isMeta") or obj.get("isCompactSummary"):
            stats["excluded_records"] += 1
            continue
        if kind == "user" and _automated_claude(obj):
            stats["automated_records"] += 1
            stats["excluded_records"] += 1
            continue
        message = obj.get("message")
        if not isinstance(message, dict) or message.get("role", kind) != kind:
            stats["malformed_records"] += 1
            continue
        content = message.get("content")
        if not _content_valid(content, {"tool_result", "tool_use", "thinking", "redacted_thinking"}, stats):
            continue
        emitted = False
        text = _human_content(content) if kind == "user" else text_of(content)
        if text.strip():
            emitted = True
            yield line, obj.get("timestamp"), "human" if kind == "user" else "assistant", text
        for block in content if isinstance(content, list) else []:
            if kind == "user" and block["type"] == "tool_result":
                if not _content_valid(block.get("content"), set(), stats):
                    continue
                result = text_of(block["content"])
                if result.strip():
                    emitted = True
                    yield line, obj.get("timestamp"), "tool", result
            elif kind == "assistant" and block["type"] == "tool_use":
                if not isinstance(block.get("name"), str):
                    stats["malformed_records"] += 1
                    continue
                emitted = True
                yield line, obj.get("timestamp"), "tool_call", block["name"] + " " + _body(block.get("input", {}))
        if not emitted:
            stats["excluded_records"] += 1


def _codex_completed(item: Any, line: int, raw_ts: Any, stats: Stats) -> Iterator[RawEvent]:
    """The PascalCase TurnItem wire shape in Codex 0.163, not legacy event text."""
    if not isinstance(item, dict) or not isinstance(item.get("type"), str) or not isinstance(item.get("id"), str):
        stats["malformed_records"] += 1
        return
    typ = item["type"]
    if typ in {"Reasoning", "HookPrompt", "ContextCompaction", "SubAgentActivity", "EnteredReviewMode", "ExitedReviewMode"}:
        stats["excluded_records"] += 1
    elif typ in {"UserMessage", "AgentMessage"}:
        content = item.get("content")
        if not isinstance(content, list):
            stats["malformed_records"] += 1
            return
        if typ == "AgentMessage":
            content = [{**block, "type": "text"} if isinstance(block, dict) and block.get("type") == "Text" else block for block in content]
        if not _content_valid(content, {"local_image", "local_audio", "skill", "mention"}, stats):
            return
        text = _human_content(content) if typ == "UserMessage" else text_of(content)
        if text.strip():
            yield line, raw_ts, "human" if typ == "UserMessage" else "assistant", text
        else:
            stats["excluded_records"] += 1
    elif typ == "Plan":
        if isinstance(item.get("text"), str):
            yield line, raw_ts, "assistant", item["text"]
        else:
            stats["malformed_records"] += 1
    elif typ == "CommandExecution":
        command = item.get("command")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            stats["malformed_records"] += 1
            return
        yield line, raw_ts, "tool_call", "command " + _body({"command": command, "cwd": item.get("cwd")})
        output = {key: item[key] for key in ("aggregated_output", "exit_code", "status") if key in item}
        if output:
            yield line, raw_ts, "tool", _body(output)
    elif typ == "FunctionCallOutput":
        if "output" in item:
            yield line, raw_ts, "tool", _body(item["output"])
        else:
            stats["malformed_records"] += 1
    elif typ in {"DynamicToolCall", "McpToolCall"}:
        if not isinstance(item.get("tool"), str) or "arguments" not in item:
            stats["malformed_records"] += 1
            return
        name = (str(item.get("server", "")) + "/" if typ == "McpToolCall" else "") + item["tool"]
        yield line, raw_ts, "tool_call", name + " " + _body(item["arguments"])
        output = {key: item[key] for key in ("content_items", "result", "error", "success", "status") if key in item}
        if output:
            yield line, raw_ts, "tool", _body(output)
    else:
        _unsupported(stats)


def codex_records(path: Path, stats: Stats, budget: Stats) -> Iterator[RawEvent]:
    rows = _json_rows(path, stats, budget)
    metadata = [obj["payload"] for _, obj in rows if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict)]
    modes = [meta.get("history_mode", "legacy") for meta in metadata] or ["legacy"]
    malformed_header = any(obj.get("type") == "session_meta" and not isinstance(obj.get("payload"), dict) for _, obj in rows)
    if malformed_header or any(not isinstance(mode, str) or mode not in {"legacy", "paginated"} for mode in modes) or len(set(modes)) > 1:
        stats["malformed_records"] += int(malformed_header)
        stats["unsupported_history_files"] += 1
        stats["excluded_records"] += len(rows)
        _unsupported(stats)
        return
    mode = modes[0]
    if rows:
        stats[mode + "_files"] += 1
    delegated = any(isinstance(meta.get("source"), dict) and "subagent" in meta["source"] for meta in metadata)
    automated = any(meta.get("source") == "exec" or (isinstance(meta.get("source"), dict) and "exec" in meta["source"])
                    or str(meta.get("originator", "")).startswith("codex_exec") for meta in metadata)
    canonical_messages = any(obj.get("type") == "response_item" and isinstance(obj.get("payload"), dict)
                             and obj["payload"].get("type") == "message" for _, obj in rows)
    for line, obj in rows:
        kind, payload = obj.get("type"), obj.get("payload")
        if not isinstance(kind, str):
            stats["malformed_records"] += 1
            continue
        if kind not in {"session_meta", "response_item", "event_msg"} | CODEX_METADATA:
            _unsupported(stats)
            continue
        stats["recognized_records"] += 1
        if not isinstance(payload, dict):
            stats["malformed_records"] += 1
            continue
        if delegated or automated:
            stats["delegated_records" if delegated else "automated_records"] += 1
            stats["excluded_records"] += 1
            continue
        if kind in {"session_meta"} | CODEX_METADATA:
            stats["excluded_records"] += 1
            continue
        record_meta = obj.get("metadata")
        if record_meta is None:
            record_meta = {}
        if not isinstance(record_meta, dict):
            stats["malformed_records"] += 1
            continue
        if record_meta.get("inherited_user_message") or record_meta.get("compaction_output"):
            stats["excluded_records"] += 1
            continue
        typ = payload.get("type")
        if not isinstance(typ, str):
            stats["malformed_records"] += 1
            continue
        if kind == "event_msg":
            if mode == "paginated" and typ == "item_completed":
                raw_ts = obj.get("timestamp", payload.get("completed_at_ms") or None)
                yield from _codex_completed(payload.get("item"), line, raw_ts, stats)
            elif mode == "paginated" and typ in {"user_message", "agent_message"}:
                stats["duplicate_stream_records"] += 1
                stats["excluded_records"] += 1
            elif typ == "item_completed" or (typ in {"user_message", "agent_message"} and not canonical_messages) or typ not in CODEX_NOISE | {"user_message", "agent_message"}:
                _unsupported(stats)
            else:
                stats["excluded_records"] += 1
            continue
        if mode == "paginated":
            stats["duplicate_stream_records"] += 1
            stats["excluded_records"] += 1
            continue
        if typ == "message":
            role, content = payload.get("role"), payload.get("content")
            if not isinstance(role, str):
                stats["malformed_records"] += 1
                continue
            if role not in {"user", "assistant", "system", "developer"}:
                _unsupported(stats)
                continue
            if role in {"system", "developer"}:
                stats["excluded_records"] += 1
                continue
            if not _content_valid(content, set(), stats):
                continue
            text = _human_content(content) if role == "user" else text_of(content)
            if text.strip():
                yield line, obj.get("timestamp"), "human" if role == "user" else "assistant", text
            else:
                stats["excluded_records"] += 1
        elif typ in {"function_call", "custom_tool_call"}:
            if not isinstance(payload.get("name"), str):
                stats["malformed_records"] += 1
                continue
            yield line, obj.get("timestamp"), "tool_call", payload["name"] + " " + _body(payload.get("arguments", payload.get("input", "")))
        elif typ in {"function_call_output", "custom_tool_call_output"}:
            if "output" not in payload:
                stats["malformed_records"] += 1
                continue
            yield line, obj.get("timestamp"), "tool", _body(payload["output"])
        elif typ == "reasoning":
            stats["excluded_records"] += 1
        else:
            _unsupported(stats)


def openclaw_records(path: Path, stats: Stats, budget: Stats) -> Iterator[RawEvent]:
    rows = _json_rows(path, stats, budget)
    delegated = any(any(marker in str(obj.get("sessionKey", obj.get("key", "")))
                        for marker in (":subagent:", ":cron:", ":heartbeat", ":brain-"))
                    for _, obj in rows if obj.get("type") == "session")
    for line, obj in rows:
        kind = obj.get("type")
        if not isinstance(kind, str):
            stats["malformed_records"] += 1
            continue
        if kind in OPENCLAW_METADATA:
            stats["recognized_records"] += 1
            stats["excluded_records"] += 1
            continue
        if kind != "message":
            _unsupported(stats)
            continue
        stats["recognized_records"] += 1
        if delegated:
            stats["delegated_records"] += 1
            stats["excluded_records"] += 1
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            stats["malformed_records"] += 1
            continue
        role, content = message.get("role"), message.get("content")
        if not isinstance(role, str):
            stats["malformed_records"] += 1
            continue
        if role not in {"user", "assistant", "toolResult", "system"}:
            _unsupported(stats)
            continue
        if role == "system":
            stats["excluded_records"] += 1
            continue
        if not _content_valid(content, {"toolCall", "thinking"}, stats):
            continue
        meta = message.get("__openclaw", {})
        if not isinstance(meta, dict):
            stats["malformed_records"] += 1
            continue
        if role == "user" and meta.get("senderIsOwner") is False:
            stats["excluded_records"] += 1
            continue
        raw_ts = obj.get("timestamp", message.get("timestamp"))
        text = _human_content(content) if role == "user" else text_of(content)
        emitted = False
        if text.strip():
            emitted = True
            yield line, raw_ts, {"user": "human", "assistant": "assistant", "toolResult": "tool"}[role], text
        if role == "assistant":
            for block in content if isinstance(content, list) else []:
                if block["type"] == "toolCall":
                    if not isinstance(block.get("name"), str):
                        stats["malformed_records"] += 1
                        continue
                    emitted = True
                    yield line, raw_ts, "tool_call", block["name"] + " " + _body(block.get("arguments", {}))
        if not emitted:
            stats["excluded_records"] += 1


ADAPTERS = {"claude-code": claude_records, "codex": codex_records, "openclaw": openclaw_records}


def _coverage(harness: str, root: Path) -> Stats:
    counters = (
        "files", "read_files", "events", "human_events", "lines", "bytes_read",
        "malformed_records", "unreadable_files", "unavailable_files", "excluded_records",
        "recognized_records", "unsupported_records", "missing_timestamps", "truncated_events",
        "delegated_records", "automated_records", "outside_window_events", "empty_events",
        "symlink_paths", "duplicate_files", "compressed_files", "oversized_lines",
        "limited_files", "incomplete_files", "limited_paths", "event_limit_reached",
        "legacy_files", "paginated_files", "unsupported_history_files", "duplicate_stream_records",
        "candidate_files", "file_budget", "byte_budget",
    )
    return {"harness": harness, "root": _path_label(root), "available": False,
            "schema_recognized": False, "status": "unavailable", **dict.fromkeys(counters, 0)}


def _paths(root: Path, stats: Stats, budget: Stats) -> Iterator[Path]:
    """Bounded metadata discovery, then global-per-root newest-file-first admission."""
    if root.is_file():
        stats["candidate_files"] += 1
        yield root
        return
    pending = [(root, 0)]
    candidates = []
    exhausted = False
    while pending:
        directory, depth = pending.pop()
        entries = []
        subdirectories = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if budget["paths"] <= 0:
                        stats["limited_paths"] += 1
                        exhausted = True
                        break
                    budget["paths"] -= 1
                    entries.append(entry)
        except OSError:
            stats["unreadable_files"] += 1
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    stats["symlink_paths"] += 1
                elif entry.is_dir(follow_symlinks=False):
                    if depth >= budget["limits"]["max_depth"]:
                        stats["limited_paths"] += 1
                    else:
                        subdirectories.append((entry.stat(follow_symlinks=False).st_mtime_ns, str(path), path))
                elif entry.name.endswith(".jsonl") or entry.name.endswith(COMPRESSED_SUFFIXES):
                    if entry.is_file(follow_symlinks=False):
                        stats["candidate_files"] += 1
                        candidates.append((entry.stat(follow_symlinks=False).st_mtime_ns, str(path), path))
                    else:
                        stats["unavailable_files"] += 1
            except OSError:
                stats["unreadable_files"] += 1
        if exhausted:
            break
        # Recent directories are discovered first if the path budget is exhausted.
        pending.extend((path, depth + 1) for _, _, path in sorted(subdirectories))
    yield from (path for _, _, path in sorted(candidates, key=lambda entry: (-entry[0], entry[1])))


def _scan_limits(overrides: dict[str, int] | None) -> dict[str, int]:
    values = {
        "max_inputs": MAX_INPUTS, "max_files": MAX_FILES, "max_paths": MAX_PATHS,
        "max_depth": MAX_DEPTH, "max_total_bytes": MAX_TOTAL_BYTES,
        "max_bytes_per_file": MAX_BYTES_PER_FILE, "max_records_per_file": MAX_RECORDS_PER_FILE,
        "max_line_bytes": MAX_LINE_BYTES, "max_events": MAX_EVENTS,
        "max_event_chars": MAX_EVENT_CHARS,
    }
    if overrides is not None:
        if not isinstance(overrides, dict) or any(key not in values or not isinstance(value, int)
                                                 or isinstance(value, bool) or value <= 0 for key, value in overrides.items()):
            raise ValueError("limits must use known max_* names and positive integer values")
        values.update(overrides)
    return values


def _status(stats: Stats) -> str:
    stats["schema_recognized"] = stats["recognized_records"] > 0
    if not stats["available"]:
        return "unavailable"
    if stats["limited_files"] or stats["limited_paths"] or stats["event_limit_reached"]:
        return "limited"
    issues = stats["malformed_records"] + stats["unreadable_files"] + stats["unavailable_files"] + stats["unsupported_records"] + stats["missing_timestamps"]
    if issues:
        if stats["events"]:
            return "partial"
        if stats["unsupported_records"] or stats["compressed_files"]:
            return "unsupported"
        return "unreadable" if stats["unreadable_files"] else "incomplete"
    return "ok" if stats["events"] else "no_events"


def collect(inputs: list[tuple[str, Path]], start: datetime, end: datetime, *,
            limits: dict[str, int] | None = None) -> tuple[list[dict], list[dict]]:
    """Collect read-only JSONL evidence; optional positive max_* limits override defaults."""
    effective = _scan_limits(limits)
    if not isinstance(start, datetime) or not isinstance(end, datetime) or start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("start and end must be timezone-aware datetimes")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("end must be strictly after start")
    if len(inputs) > effective["max_inputs"]:
        raise ValueError(f"at most {effective['max_inputs']} inputs are supported")
    if any(harness not in ADAPTERS for harness, _ in inputs):
        raise ValueError("unsupported harness; choose claude-code, codex, or openclaw")
    events: list[dict] = []
    coverage: list[dict] = []
    seen: set[tuple[str, str]] = set()
    budget = {"files": effective["max_files"], "paths": effective["max_paths"],
              "bytes": effective["max_total_bytes"], "events": effective["max_events"], "limits": effective}
    for input_index, (harness, supplied) in enumerate(inputs):
        root = Path(supplied).expanduser().absolute()
        stats = _coverage(harness, root)
        stats["limits"] = dict(effective)
        roots_left = len(inputs) - input_index
        file_quota = max(1, budget["files"] // roots_left) if budget["files"] else 0
        byte_quota = max(1, budget["bytes"] // roots_left) if budget["bytes"] else 0
        stats["file_budget"], stats["byte_budget"] = file_quota, byte_quota
        budget["input_bytes"] = byte_quota
        coverage.append(stats)
        try:
            mode = root.lstat().st_mode
            if stat.S_ISLNK(mode):
                stats["symlink_paths"] += 1
                stats["unavailable_files"] += 1
                continue
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                stats["unavailable_files"] += 1
                continue
            root = root.resolve(strict=True)
            stats["available"] = True
        except FileNotFoundError:
            stats["unavailable_files"] += 1
            continue
        except (OSError, RuntimeError):
            stats["unreadable_files"] += 1
            continue
        if budget["events"] <= 0 or budget["files"] <= 0 or budget["bytes"] <= 0:
            stats["event_limit_reached" if budget["events"] <= 0 else "limited_files"] += 1
        else:
            for path in _paths(root, stats, budget):
                if stats["files"] >= file_quota or budget["input_bytes"] <= 0 or budget["files"] <= 0 or budget["bytes"] <= 0 or budget["events"] <= 0:
                    stats["event_limit_reached" if budget["events"] <= 0 else "limited_files"] += 1
                    break
                if path.name.endswith(COMPRESSED_SUFFIXES):
                    stats["compressed_files"] += 1
                    stats["unavailable_files"] += 1
                    continue
                if path.suffix != ".jsonl":
                    stats["unavailable_files"] += 1
                    continue
                identity = (harness, str(path))
                if identity in seen:
                    stats["duplicate_files"] += 1
                    continue
                seen.add(identity)
                budget["files"] -= 1
                stats["files"] += 1
                source = _path_label(path.relative_to(root) if root.is_dir() else path.name)
                digest = hashlib.sha256((harness + "\0" + str(path)).encode("utf-8", errors="surrogatepass")).hexdigest()
                ordinals: dict[int, int] = {}
                for line, raw_ts, role, text in ADAPTERS[harness](path, stats, budget):
                    ordinal = ordinals.get(line, 0)
                    ordinals[line] = ordinal + 1
                    ts = timestamp(raw_ts)
                    if ts is None:
                        stats["missing_timestamps"] += 1
                        continue
                    if not start <= ts < end:
                        stats["outside_window_events"] += 1
                        continue
                    if not text.strip():
                        stats["empty_events"] += 1
                        continue
                    safe = sanitize(text)
                    truncated = len(safe) > effective["max_event_chars"]
                    if truncated:
                        stats["truncated_events"] += 1
                        keep = max(0, effective["max_event_chars"] - len(TRUNCATION))
                        safe = (safe[:keep] + TRUNCATION)[:effective["max_event_chars"]]
                    events.append({"id": f"{harness}:{digest}:{line}:{ordinal}", "session": digest,
                                   "harness": harness, "source": source, "line": line,
                                   "timestamp": ts.isoformat(), "role": role, "text": safe, "truncated": truncated})
                    stats["events"] += 1
                    stats["human_events"] += role == "human"
                    budget["events"] -= 1
                    if budget["events"] <= 0:
                        stats["event_limit_reached"] += 1
                        break
        stats["status"] = _status(stats)
    events.sort(key=lambda event: (datetime.fromisoformat(event["timestamp"]), event["id"]))
    return events, coverage
