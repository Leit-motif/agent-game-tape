# NotebookLM: real controls, soft direction, and execution

NotebookLM is optional. The local report is the primary coaching artifact; audio is another presentation
of the reviewed material. The external `notebooklm-mcp-cli` client uses undocumented Google endpoints and
is not an official Google API. Pin a version and recheck its `--help` when upgrading.

## Parameter map

| Control | Mechanism | What it does not guarantee |
|---|---|---|
| Eligible narration | One immutable source and explicit `--source-ids` | Exhaustive or ordered coverage |
| Focus | Versioned natural-language `--focus` | Obedience, exact wording, or preserved uncertainty |
| Format | `deep_dive`, `brief`, `critique`, `debate` | A specific host personality or voice |
| Length | `short`, `default`, `long` | Exact minutes, maximum seconds, or stable duration |
| Language | Explicit language code, e.g. `en` | Stable accent or voice identity |
| Moment count / source word budget | Local selection and renderer | A linear relation to spoken duration |
| Factual quality | Evidence selection, semantic review, full narration QA | A guarantee from prompt acceptance or regexes |

Google describes Deep Dive as two hosts explaining/connecting material; Brief as one speaker under two
minutes; Critique as constructive evaluation of material; Debate as competing perspectives. Critique may
help some coaching styles, but can also critique the document rather than the interaction. Treat it as a
separate experiment, not a free upgrade. This repository's first renderer comparison freezes Deep Dive,
English and default length. It does not measure a best-format winner.

No seed, temperature, top-p, model-version, fixed-voice, per-host-role, exact-duration or verbatim-script
control was found in the inspected audio interface. Do not invent these knobs or transfer settings from
chat configuration into Audio Overview. No current numeric audio focus limit was verified; keep focus
concise rather than assuming unlimited instructions. Google's Help lists length customization as English-only.

## Source architecture

`evidence.json` and `review.json` hold attribution, citations, rules and uncertainty. `report.md` exposes
that audit trail locally. `upload/game-tape.md` is a compact prose rendering of only selected moments and
one supported experiment. A qualification belongs beside the claim it changes; the full missing-data
inventory stays local. A separate missing-goals or coverage source can become a whole spoken segment.

The default focus asks for direct coaching, grounded consequences and a usable close. It does not list
all the mistakes the hosts must avoid: those prohibitions can themselves become dialogue. Factual
invariants belong in the evidence and reviewer, not a longer list of requests to the hosts.

## Install and authenticate separately

Python 3.10+ is enough for local work. For audio, install a compatible client in an isolated environment,
for example with pipx, and authenticate using its supported interactive login. This project never reads,
exports or stores browser cookies and never asks for keys. Check the actual client and account first.

```bash
pipx install 'notebooklm-mcp-cli==0.15.6'
nlm --version
nlm login
nlm login --check
```

The public interface was inspected at 0.15.6; the initial live evaluation uses an existing 0.15.1 client.
See the evaluation receipt for what was actually executed. A certificate/transport failure is not proof
that login expired. Fix the underlying environment rather than disabling TLS verification.

## Execution and recovery

The adapter requires `--allow-upload` and validates source, focus, review and evidence fingerprints.
It uploads a sealed copy of the verified `upload/game-tape.md` bytes, never the entire folder. Separate notebooks prevent opposite
experiment arms and old sources from contaminating generation. Every mutation records an intent before
sending; successful returned ids are saved immediately. A concurrent publisher is blocked.

```bash
python3 scripts/notebooklm.py start /private/path/to/run --allow-upload
python3 scripts/notebooklm.py status /private/path/to/run
python3 scripts/notebooklm.py wait /private/path/to/run --download --max-minutes 25
```

`--nlm /absolute/path/to/executable` selects a compatible wrapper without shell expansion. It is not a
shell-command string. Polling is every thirty seconds while waiting for the artifact, with a bounded wait.
Exit 3 from `wait` means still generating, not failed. Resume by checking the same run.

After an uncertain remote write, do not blindly retry or adopt an unrelated ready artifact. Inspect the
private state and the exact notebook through `nlm notebook list`, `nlm source list NOTEBOOK_ID --json`
and `nlm studio status NOTEBOOK_ID --json`. Reconcile the returned ids against the submitted title/source/
prompt before repairing `notebooklm-state.json`. The helper deliberately has no automatic 'clear uncertainty'
button. Preserve the original state first. A crashed `.publisher.lock` requires checking its PID before removal.

A generated artifact can temporarily be unavailable for download. Check the same artifact and retry the
read/download later; do not create another episode. Downloads use `--id ARTIFACT_ID` and an `.m4a` filename.
Do not label AAC audio as MP3; transcoding is a separate operation.

### Audio writes are single-dispatch, not stock CLI retries

The initial live test exposed a critical upstream behavior: one failed stock `nlm audio create` command
left four audio artifacts. The inspected 0.15.1 and 0.15.6 client audio kickoff paths can replay HTTP/RPC
or authentication failures. A rate-limit retry variable alone does not disable every replay. Upgrading
alone or switching to CDP is not a safe single-send control.

For audio creation, this publisher therefore uses the bundled, narrowly version/fingerprint-pinned
`nlm_single_send.py` adapter under the client's Python. It reuses upstream payload construction and parsing,
but dispatches one HTTP POST without the kickoff retry/recovery/CDP wrappers. Unknown compatibility fails
closed. Normal CLI reads and notebook/source setup remain separate; no guarantee is made that the stock
client makes all of its own setup operations single-send. Ambiguous setup still needs reconciliation.

The client Python is derived from the `nlm` environment when possible. Use `--client-python` explicitly
when it cannot be located. An optional `--environment-entrypoint` loads an existing guarded Python CLI
wrapper's host-specific TLS setup without invoking its main. It does not edit the installed package,
authentication or host configuration. Keep certificate-chain and hostname checks intact.

The guarantee is **at most one audio-adapter dispatch**, not exactly-once execution inside Google: no
server idempotency contract is exposed. Any failed or missing-id response remains uncertain, even if an
immediate read finds nothing. Never blindly retry or choose one of several unexpected outputs.

The adapter records `generation_state: generated` and `audio_quality: unverified`. Semantic editorial
acceptance is a separate review receipt, not inferred from generation success or the recorded focus string.
No public sharing, recurring schedule, regeneration loop or delivery outside the requesting conversation
is configured by this skill.

## Sources checked

- [Google Audio Overview Help](https://support.google.com/notebooklm/answer/16212820?hl=en)
- [Pinned client CLI](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/cli/commands/studio.py)
- [Pinned service and source fallback](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/services/studio.py)
- [Pinned audio request construction](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/core/studio.py)
