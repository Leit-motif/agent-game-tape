# Contributing

Thanks for helping. Agent Game Tape is small on purpose: keep changes focused and dependency-free where
possible.

## Setup

Python 3.10 or newer. There are no third-party dependencies to install.

```bash
git clone https://github.com/Leit-motif/agent-game-tape.git
cd agent-game-tape
```

## Before you open a pull request

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts examples
git diff --check
```

Tests run offline and use a fake model backend.

## Data rules

- Use synthetic fixtures only. Never commit real transcripts, generated reviews, audio, account ids,
  notebook ids or credentials.
- Write runtime output outside the repository (default `~/.agent-game-tape`).

## Behavioural changes

Changes to prompts, focus text, the renderer or the narration checker follow
[references/evaluation-protocol.md](references/evaluation-protocol.md). Unit tests prove the code does
what it says. They do not prove the audio renderer or the checker model behaves as intended. Write the
pass bar down before running, report actual results including failures, and do not loosen a bar after
seeing results.

## Workflow

- GitHub Issues is the tracker. Open or reference an issue for anything beyond a typo.
- Keep pull requests small and single-purpose.
- Use [Conventional Commits](https://www.conventionalcommits.org/) titles, e.g.
  `fix(collect): handle empty Codex sessions`.
- Read the rendered README before merging documentation changes.
