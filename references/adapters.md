# Hosts and transcript adapters

The skill format is one `SKILL.md` plus relative resources. No OpenClaw tool names or private filesystem
layout are required for the core workflow.

## Hosts

| Host | Project skill directory | Personal skill directory | Explicit invocation |
|---|---|---|---|
| Claude Code | `.claude/skills/agent-game-tape/` | `~/.claude/skills/agent-game-tape/` | `/agent-game-tape` |
| Codex | `.agents/skills/agent-game-tape/` | `~/.agents/skills/agent-game-tape/` | `$agent-game-tape` |
| OpenClaw | workspace `skills/agent-game-tape/` | configured skill directories | Ask for the skill by name |

Install by linking or copying this complete directory. The repository's CLAUDE.md imports development
instructions; it is not a substitute for installing the skill. Host permissions still apply: a skill
cannot grant access to transcript stores or Google. On Windows, use a directory copy and ensure Python's
IANA timezone data is available (install `tzdata` if the OS supplies none).

## Explicit collection roots

```bash
python3 scripts/game_tape.py prepare \
  --day 2030-04-10 --timezone Europe/London \
  --claude /path/to/claude/projects \
  --codex /path/to/codex/sessions \
  --out /private/path/review
```

Roots are repeatable and can be a JSONL file or directory. Supplying any root disables automatic default
roots, so the scope stays intentional. Automatic defaults are `~/.claude/projects` and `~/.codex/sessions`,
honoring `CLAUDE_CONFIG_DIR` and `CODEX_HOME`. Archives or exports from another machine must be explicitly
selected; there is no SSH, GitHub scan, or remote copy inside collection.

The requested local calendar day uses an exclusive end boundary and respects daylight saving. Add
`--day-start-hour 4` for a shifted working day. Default `--lookback-hours 24` includes preceding context,
but those context-only human messages are ineligible as new moments. Timestamps without a timezone are
reported rather than guessed. An output folder with existing evidence is not silently overwritten.

## Attribution and coverage

The adapters preserve human messages, assistant text, tool calls and results separately. Tool results are
not human instructions; calls are attempts, not proof of success. Known delegated, injected, relayed and
automated messages are excluded from human quotes. Unknown authorship must still be checked against
invocation provenance: a user role or a harness's 'human' flag can describe an SDK-delivered agent prompt.

Local storage is not a stable public API. Inspect coverage counters for unsupported formats, missing
stores, malformed/unreadable records, missing timestamps, excluded records and truncation. A zero-event
scan is not sufficient evidence of a quiet day. The model must inspect candidate exchanges, not use a
word-list or profanity count as a relevance/impact score.

Claude logs can contain branches, compaction, user-role tool results, meta events and subagents. This is a
historical event review, not a reconstruction of a guaranteed current conversation branch. References
retain source identity and location; repeated text alone is not a safe deduplication key.

Codex legacy response items can duplicate event messages. The adapter selects the authoritative stream
from `session_meta.payload.history_mode`: legacy uses response items; current paginated history uses
`event_msg` → `item_completed` → PascalCase `UserMessage`/`AgentMessage` and supported tool items. The
second representation is excluded rather than double-counted. Unknown or conflicting modes fail closed.
Compressed files, including `.jsonl.zst`, are explicitly unsupported. Parent/fork references are not followed
as new child activity; known inherited/delegated records are excluded.

Discovery prioritizes newest file mtime across subdirectories before the file cap. Mtime is a priority
hint, not proof of the date inside a record. Defaults bound scanning to 512 files, 256 MiB total, 64 MiB
per file, 16 MiB per line and 10,000 emitted events; cap exhaustion remains explicit. Supply `--scan-limits`
with a JSON object of positive `max_*` overrides when a legitimate larger export needs them. Effective
limits are retained in coverage; raising a cap is not a completeness claim.

The exact implemented adapter support and regression coverage are documented by `scripts/collect.py` and
`tests/test_collect.py`. Version claims apply to the cited upstream interfaces, not every future store.

## OpenClaw, deliberately tertiary

Pass exported JSONL files explicitly:

```bash
python3 scripts/game_tape.py prepare --day 2030-04-10 --timezone UTC \
  --openclaw /path/to/exported-session.jsonl --out /private/path/openclaw-review
```

This adapter does not read a live OpenClaw SQLite database, guess where an installation stores sessions,
or retrieve selection-comment attachments and question-card respondent metadata. Export those through
the host's supported history tools when needed and review their attribution. Missing attachment text or
an agent-written option label must not be invented as a human-authored quote. This is intentionally
narrower than a bespoke private OpenClaw collector; the portable primary workflow is Claude Code/Codex.

## Public references

- [Claude Code skill discovery](https://code.claude.com/docs/en/skills#where-skills-live)
- [Codex skill documentation](https://learn.chatgpt.com/docs/build-skills)
- [Claude session storage](https://code.claude.com/docs/en/agent-sdk/sessions)
- [Claude SDK parser](https://github.com/anthropics/claude-agent-sdk-python/blob/498e063489d08a36210dbfc5fa5f5b72b401ea62/src/claude_agent_sdk/_internal/sessions.py)
- [Codex rollout policy](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/rollout/src/policy.rs)
- [Codex message items](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/protocol/src/items.rs)
