# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-21

First public release. The local report is the product; Gemini Notebook (formerly NotebookLM) audio is
optional and checked per episode.

### Added

- Local collection (`prepare`) for Claude Code and Codex transcript stores, plus OpenClaw session
  exports. No network calls; honours `CLAUDE_CONFIG_DIR` and `CODEX_HOME`; paginated Codex exports;
  stable ordering for tied timestamps; a coverage report of what was and was not read.
- Review contract for `review.json`: exact human quotes, supporting event spans, explicit actor and
  causal limits, zero to five moments and at most one next-session experiment.
- Validation and rendering (`render`): quote and span checks, a private local report, and a separate
  narration-ready source that excludes raw evidence, rules and audit labels.
- Audio controls on `render`: `--format`, `--length`, `--language`, repeatable `--source`, and
  `--focus` / `--focus-file`, with source and focus hashes recorded in the run manifest. Web research
  is always off so every claim stays checkable.
- Gemini Notebook adapter (`notebooklm.py start|status|wait`): explicit `--allow-upload`, resumable
  remote ids, and a version-pinned single-send guard so an audio request is dispatched at most once.
- `audit-audio` triage for a complete local ASR transcript.
- `check-narration`: claim-level check of an episode transcript against the evidence and review, with
  a hashed receipt and an `accepted`, `rejected` or `unverified` decision.
- Pre-registered checker evaluation: 48/48 labelled failures caught, 0/969 false flags, 54/54
  decisions, stable across three runs on a small fictional development set.
- `doctor` onboarding command: read-only setup check with numbered next steps; the skill runs it on
  first use.
- `TESTED_MODEL` in `scripts/models.py`; `--model` overrides are labelled `unvalidated` in receipts and
  output.
- Fictional demo (`examples/make_demo.py`) and fact sheet, offline test suite and CI workflow.

### Known limitations

- The audio renderer still embellishes at times; both recorded Brief episodes were rejected by review.
- The checker evaluation is directional: two fictional scenarios, Brief length, no held-out set.

[0.1.0]: https://github.com/Leit-motif/agent-game-tape/releases/tag/v0.1.0
