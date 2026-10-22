# Gemini Notebook (formerly NotebookLM): audio controls and execution

Audio is optional. The local report is the coaching artifact. Gemini Notebook can turn the reviewed
narration into a spoken episode, like a short podcast about your own sessions.

**What this skill does.** It uploads a sealed copy of the narration file (plus any extra sources you chose),
asks Gemini Notebook for one Audio Overview with the controls below, waits for it, and downloads it. It
records every returned id so a run can be checked or resumed later.

**What is guaranteed.** Only the files listed in the run's manifest are uploaded, byte for byte as hashed.
Nothing is uploaded without `--allow-upload`. The audio request is sent at most once per run. The notebook
stays private unless you change its sharing yourself.

**What is not guaranteed.** The episode is generated. Gemini Notebook may skip, reorder or embellish
material, ignore parts of the focus prompt, or run longer or shorter than asked. That is why every episode
is transcribed and checked before anyone calls it accurate ([full-episode QA](audio-qa.md)).

The `nlm` command comes from the separate `notebooklm-mcp-cli` package. It uses undocumented Google
endpoints and is not an official Google API. Pin a version and recheck its `--help` when upgrading.

## Parameter map

Set these on `game_tape.py render RUN`. They are written to `manifest.json`, and `notebooklm.py start`
sends exactly what the manifest records.

| Control | Flag and values | Default | What it does not guarantee |
|---|---|---|---|
| Format | `--format deep_dive \| brief \| critique \| debate` | `deep_dive` | A specific host personality or voice |
| Length | `--length short \| default \| long` | `default` | Exact minutes, maximum seconds, or stable duration |
| Language | `--language CODE`, e.g. `en`, `es`, `ja` | `en` | Stable accent or voice identity |
| Sources | `--source PATH`, repeatable; `narration` means `upload/game-tape.md` | narration only | Exhaustive or ordered coverage |
| Focus | `--focus TEXT` or `--focus-file PATH` (one or the other) | bundled template | Obedience, exact wording, or preserved uncertainty |
| Web research | none | always off | Not offered (see below) |
| Moment count / word budget | Local selection and renderer | `--max-words 1600` | A linear relation to spoken duration |
| Factual quality | Evidence selection, semantic review, full narration QA | n/a | A guarantee from prompt acceptance or regexes |

**Sources.** Extra sources are copied into `RUN/upload/sources/` and hashed in `manifest.json` as
`sources: [{path, sha256}]`. The run's raw `evidence.json`, `evidence.md`, `review.json` and rules files are
refused as sources: they hold private attribution and audit detail that belongs in the local report. Add a
file only when the user chose it and it has been reviewed for private data. Every uploaded source id is
passed to the audio request.

**Focus.** The bundled template is `references/audio-focus.txt` (`audio-focus-brief.txt` for Brief). It asks
for direct coaching, grounded consequences and a usable close. It does not list every mistake the hosts must
avoid, because those prohibitions can themselves become dialogue. Factual limits belong in the evidence and
the reviewer, not in a longer list of requests. The Brief focus names the literal first sentence (`You said,
“<first quote>”`): with “Begin with the first decision” Brief opened with a generic preamble in 8 of 8
episodes, and with the literal sentence it opened on the quote in 5 of 5 ([narration climb](narration-climb.md)).
Override the focus only when the user wants a different emphasis. The manifest records `focus_origin: bundled` or `caller`.

**Web research.** Gemini Notebook can discover and add outside sources. This skill never turns that on.
Outside facts have no evidence ids, so the narration could no longer be checked claim by claim against
your sessions.

**Formats.** Google describes Deep Dive as two hosts explaining and connecting the material; Brief as one
speaker under two minutes; Critique as constructive evaluation; Debate as competing perspectives. Critique
may critique the document rather than the interaction, so treat it as an experiment, not an upgrade. Brief
accepts at most two selected moments. The repository's renderer comparison used Deep Dive, English and
default length. It did not measure a best format.

**Not available.** No seed, temperature, top-p, model-version, fixed-voice, per-host-role, exact-duration or
verbatim-script control was found in the audio interface. Do not invent these knobs or carry settings over
from chat configuration. No numeric focus limit was verified; keep focus concise. Google's Help lists length
customization as English-only.

## What gets uploaded

`evidence.json` and `review.json` hold attribution, citations, rules and uncertainty. `report.md` exposes
that audit trail locally. `upload/game-tape.md` is a compact prose rendering of only the selected moments
and one supported experiment. A qualification sits beside the claim it changes; the full missing-data
inventory stays local. A separate coverage or missing-goals source would tend to become a whole spoken
segment, so it is not uploaded.

## Install and authenticate separately

Python 3.10+ is enough for local work. For audio, install a compatible client in an isolated environment,
for example with pipx, and authenticate using its interactive login. This project never reads, exports or
stores browser cookies and never asks for keys. `game_tape.py doctor` reports whether `nlm` is installed and
logged in without changing anything.

```bash
pipx install 'notebooklm-mcp-cli==0.15.6'
nlm --version
nlm login
nlm login --check
```

The public interface was inspected at 0.15.6; the first live evaluation used an existing 0.15.1 client.
A certificate or transport failure is not proof that login expired. Fix the underlying environment rather
than disabling TLS verification.

## Execution and recovery

`start` requires `--allow-upload` and checks the source, focus, review and evidence fingerprints against the
manifest. It uploads sealed copies of the manifest's sources, never the whole folder. Each run gets its own
notebook, so earlier sources and other runs cannot leak into generation. Every remote write records its
intent before sending, and returned ids are saved immediately. A second concurrent publisher is blocked.

```bash
python3 scripts/notebooklm.py start /private/path/to/run --allow-upload
python3 scripts/notebooklm.py status /private/path/to/run
python3 scripts/notebooklm.py wait /private/path/to/run --download --max-minutes 25
```

`--nlm /absolute/path/to/executable` selects a compatible wrapper. It is a path, not a shell command. `wait`
polls every thirty seconds up to its limit. Exit 3 from `wait` means still generating, not failed. Resume by
checking the same run.

After an uncertain remote write, do not retry blindly or adopt an unrelated ready artifact. Inspect the
private state and the exact notebook with `nlm notebook list`, `nlm source list NOTEBOOK_ID --json` and
`nlm studio status NOTEBOOK_ID --json`. Match the returned ids against the submitted title, sources and
prompt before repairing `notebooklm-state.json`. There is deliberately no automatic "clear uncertainty"
command. Keep a copy of the original state first. For an uncertain `source_add`, set
`source_ids[pending_source_sha256]` to the verified id, then clear `pending_mutation` and
`pending_source_sha256`. Before removing a stale `.publisher.lock`, confirm its
PID is no longer running.

A generated artifact can be briefly unavailable for download. Retry the download of the same artifact
later; do not create another episode. Downloads use `--id ARTIFACT_ID` and an `.m4a` filename. The file is
AAC audio, not MP3; transcoding is a separate step.

### The audio request is sent once

In the first live test, one failed stock `nlm audio create` command left four audio artifacts. The
inspected 0.15.1 and 0.15.6 clients can replay the audio request after HTTP, RPC or authentication
failures. A rate-limit retry setting does not disable every replay, and upgrading or switching to CDP does
not fix it.

So audio creation goes through the bundled `nlm_single_send.py` adapter, pinned to known client versions
and fingerprints and run under the client's Python. It reuses the client's request construction and
parsing, but sends one HTTP POST without the retry, recovery or CDP wrappers. An unknown client version
fails closed. Ordinary reads and notebook/source setup still use the stock CLI, which may retry on its own;
an ambiguous setup step still needs reconciliation.

The client's Python is found from the `nlm` installation when possible. Pass `--client-python` when it
cannot be located.

The guarantee is **at most one audio request sent**, not exactly-once execution inside Google, which exposes
no idempotency contract. A failed or id-less response stays uncertain even if an immediate read finds
nothing. Never retry blindly or pick one of several unexpected outputs.

The state records `generation_state: generated` and `audio_quality: unverified`. Editorial acceptance is a
separate receipt, never inferred from generation success or the focus text. This skill configures no public
sharing, recurring schedule, regeneration loop or delivery outside the requesting conversation.

## Advanced: custom network environments

Some hosts reach Google only through a custom TLS or proxy setup that an existing Python CLI wrapper
installs at startup. `notebooklm.py start --environment-entrypoint PATH` loads that wrapper's environment
setup without running its main, so the single-send adapter sees the same network configuration. It does not
edit the installed package, authentication or host configuration. Keep certificate-chain and hostname
checks intact. The flag is hidden from `--help` because most setups never need it.

## Sources checked

- [Google Audio Overview Help](https://support.google.com/notebooklm/answer/16212820?hl=en)
- [Pinned client CLI](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/cli/commands/studio.py)
- [Pinned service and source fallback](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/services/studio.py)
- [Pinned audio request construction](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/d6d427cd0ef8519843a46c447e3572b4c08c7081/src/notebooklm_tools/core/studio.py)
