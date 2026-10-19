# Agent Game Tape

**Review your human–AI sessions like an athlete reviewing the tape.**

Not a productivity score, a code review, or a blow-by-blow recap. Find the calls that changed an outcome:
what you asked, what the assistant did, what the evidence supports, and one move worth practicing next time.

Built as a portable skill for **Claude Code and Codex**. OpenClaw session exports are an optional third
adapter. NotebookLM turns the reviewed material into audio; it does not decide what happened.

> **Release gate:** publication is held while the behavioral checks run. See the
> [actual results and remaining gate](references/validation.md). No reliability claim is inferred from unit tests.

## What you get

```text
Local session logs → attributed evidence → selected coaching moments → local report
                                                             └── optional NotebookLM audio → full narration QA
```

- A private, evidence-linked report with exact human quotes and supporting events.
- Human steering separated from agent execution and system failures. A bad outcome is not automatically
  your bad call.
- A small set of lessons—not a mandatory daily podcast or an invented fault on a quiet day.
- A narration-ready source file without the raw transcript, rulebook, coverage inventory, or audit labels.
- Explicit source/prompt hashes and artifact ids. “Generated” never silently means “quality accepted.”

## Install the skill

Python **3.10+** is the only local requirement. Keep the clone; skill links refer to it.

```bash
git clone https://github.com/Leit-motif/agent-game-tape.git
cd agent-game-tape
```

**Claude Code — personal skill:**

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)" ~/.claude/skills/agent-game-tape
```

Then ask Claude Code: `/agent-game-tape Review yesterday's sessions. Start with a local report.`

**Codex — personal skill:**

```bash
mkdir -p ~/.agents/skills
ln -s "$(pwd)" ~/.agents/skills/agent-game-tape
```

Then ask Codex: `$agent-game-tape Review yesterday's sessions. Start with a local report.`

For project-scoped installation, use `.claude/skills/agent-game-tape` or
`.agents/skills/agent-game-tape` inside that project instead. Copying the skill directory also works where
symlinks are inconvenient. Do not overwrite an existing installation. Start/reload the host if it has not
refreshed skill discovery. See [host and transcript details](references/adapters.md).

The agent does the reading and judgment. The helpers handle deterministic collection, quote validation,
rendering and optional audio execution. No model API key or additional paid model service is required.

## Try it without any real sessions

The demo is entirely fictional and makes no network requests:

```bash
python3 examples/make_demo.py --out /tmp/game-tape-demo
python3 scripts/game_tape.py render /tmp/game-tape-demo/case-a
```

Read `/tmp/game-tape-demo/case-a/report.md`. It contains a successful regression-first instruction and a
publication condition the assistant failed to follow—not an accusation that the human should have asked harder.
The [frozen fact sheet](examples/fact-sheet.md) makes its factual boundaries inspectable.

## Run locally

Normally the skill handles these commands. For direct use:

```bash
python3 scripts/game_tape.py prepare \
  --day yesterday --timezone America/New_York \
  --out /private/path/game-tape/run-01
```

Use **your** timezone; the example is not a preference the skill assumes. Explicit dates, a shifted day
boundary, transcript roots and a rules file are supported. Default discovery reads Claude Code and Codex
local stores, honoring `CLAUDE_CONFIG_DIR` and `CODEX_HOME`. It does not SSH to other machines or read
OpenClaw's live database. Prior context can inform the review without becoming a new in-window moment.

Have your agent read the evidence and write `review.json` using the
[review contract](references/review-contract.md), then:

```bash
python3 scripts/game_tape.py render /private/path/game-tape/run-01
```

The starter rubric is customizable. Supply the standards actually applicable to your work with
`--rules /path/to/rules.json`; a sample is in `references/rules.json`. Don't retrospectively grade someone
against rules they had not adopted. Sparse evidence is a reason to abstain, not pad the review.

## Optional NotebookLM audio

Install/authenticate the separate [NotebookLM CLI](https://github.com/jacob-bd/gemini-notebook-mcp-cli)
first. Check [real controls and execution](references/notebooklm.md), then explicitly request audio after
reviewing what will be uploaded:

```bash
python3 scripts/notebooklm.py start /private/path/game-tape/run-01 --allow-upload
python3 scripts/notebooklm.py wait /private/path/game-tape/run-01 --download
```

Only the prepared narration file is uploaded. The notebook remains private unless you separately change
its sharing. Full-episode transcription and [semantic QA](references/audio-qa.md) are required before
calling the narration accurate. Opening checks miss later drift.

**NotebookLM is generative.** Format, relative length, language, focus and source selection are real controls;
exact minutes, fixed voices, deterministic seeds and verbatim scripts are not supported promises. You can
use just the local report, or feed the reviewed prose into another presentation tool.

## Privacy and limits

Collection and rendering make no network calls. The model running your coding agent still sees the evidence
it reads under that host's normal data policy. `--allow-upload` sends the selected narration to your Google
account. Review it for confidential information first. Recognizable-token redaction is **not** a guarantee
that secrets or personal details have been removed.

Runtime files belong outside this public checkout; `runs/` and `private/` are also gitignored as a fallback.
Never publish real session logs, generated private reviews, browser profiles, account ids, or credentials.
This repository's examples and fixtures are synthetic. No schedule, account setup, cookie extraction,
public notebook sharing, auto-remediation, or public posting is installed by the skill.

Transcript formats evolve. See the adapter coverage report instead of treating an empty result as a quiet
day. Python validates structure and exact spans, not semantic truth or causal responsibility. Human/model
judgment and final-artifact inspection remain part of the workflow.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts examples
```

Tests are offline. The [evaluation protocol](references/evaluation-protocol.md) keeps behavioral comparisons
separate from unit tests. Report actual outputs and limitations, not a universal “best prompt.”

MIT licensed. Not affiliated with Google, Anthropic, or OpenAI.
