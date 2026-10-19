# Agent Game Tape development

This repository is the portable source, not a live user's workspace. Read README.md and the relevant
reference before changing behavior. Keep collection local and NotebookLM upload explicit. Use synthetic
fixtures only; private transcripts, account identities, runtime outputs and credentials never enter git.

Run `python3 -m unittest discover -s tests -v`, `python3 -m compileall -q scripts examples`, and
`git diff --check`. Behavioral changes also follow `references/evaluation-protocol.md`: unit tests are
not evidence that NotebookLM obeyed a prompt. Preserve factual/attribution boundaries and never weaken
acceptance gates after seeing results. Inspect the rendered README before publication.

GitHub Issues is the project tracker. Keep changes small, dependency-free where possible, and committed
with Conventional Commit titles. Do not alter installed skills, host config, credentials, schedules or
public notebook sharing while developing this repository.
