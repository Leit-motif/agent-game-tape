# Validation status

## In short

- **What was tested:** the local report, the claim checker (`check-narration`), and raw audio from Gemini
  Notebook (formerly NotebookLM) on two fictional cases, in both Deep Dive and Brief formats.
- **What passed:** the local report is stable. The claim checker caught 48 of 48 labelled errors, flagged
  0 of 969 faithful claims, and gave the same verdict on every case across three runs. See the
  [checker evaluation](checker-eval.md).
- **What failed:** raw Gemini Notebook narration added claims the evidence did not support in both Deep Dive
  trials and both fictional Brief episodes. Full-episode review caught every one of them.
- **What the narration climb found (2026-10-21/22):** naming the literal first sentence in the Brief focus fixed
  the opening (0 of 8 episodes before, 6 of 6 after); it is now the default. With it, 2 of 5 scored Brief episodes
  passed `check-narration`. Prompt and source changes aimed at the remaining invented durations and savings
  showed no gain. 6 of 20 requests ended in a Google-side `failed` artifact with no audio. See the
  [narration climb](narration-climb.md).
- **What it means for you:** treat the local report as the reliable output. Audio is experimental and gated per
  episode: the skill delivers an episode only after `check-narration` accepts it, and otherwise offers one
  regeneration or the local report. Expect more episodes to be rejected than accepted.

*Naming note:* NotebookLM was renamed Gemini Notebook. This record keeps the name used at the time.

*Terms used below:* arm = one variant in a comparison; frozen = fixed before any output was seen;
veto = a single failure that rejects an episode regardless of its total score; admission = the
preconditions checked before a study may start; ASR = automatic speech recognition (transcription).

The full record follows. Earlier sections are unchanged; the narration climb is summarized at the end.

---

**Released 2026-10-21: local report stable, NotebookLM audio experimental.** Unit tests and source cleanup
do not establish NotebookLM behavior. This document reports what was actually tested, including negative results.

## Release decision

The earlier gate held publication until raw NotebookLM output passed a fidelity bar. That tested the
renderer, which this package does not control and cannot seed, script or pin. What the package does
control is the review: evidence collection, exact-quote validation, the local report, and full-episode QA
that rejects an embellished narration. Both Brief episodes below were caught and rejected by that QA, which
is the safeguard working as designed. The skill ships with the local report as its primary artifact and
audio labeled experimental; per-episode QA, not a one-time renderer trial, decides whether a given episode
is accurate. The failed results below are preserved unchanged. Narration fidelity remains open work.

## Source-renderer test: failed

Two versions of the same entirely fictional Case A used the same selected facts, rules, order, focus,
Deep Dive format, English and default relative length. One retained field labels; one rendered prose.
Both full narrations were transcribed and independently scored against the frozen fact sheet, blinded to arm.

| Case A source | Measured audio | Score | Factual/closing gates |
|---|---:|---:|---|
| Fielded | 17:22 | 4/10 | Failed |
| Prose | 18:31 | 4/10 | Failed |

The five scores were factual support, coaching usefulness, concision, natural address, and a usable
closing experiment, each 0–2. Both retained useful lessons and direct address. Both also invented
model-internal explanations, strengthened uncertain elapsed-time evidence into public-duration claims,
and added a philosophical ending after the supplied experiment. The coarse tie does not mean their
individual errors were identical.

**Conclusion:** narration-ready prose is a cleaner input boundary, not a demonstrated factual-quality fix.
One generation per arm in one fictional case cannot establish a population noise floor, significance,
or general renderer superiority. The observed score delta was zero; headroom to the ten-point ceiling was six.
These are development observations, not a sealed holdout or a full-audio listening pass.

## Transport gate: failed stock client; narrow guard checked offline and live

The planned four-output renderer trial suffered a separate integrity incident: one failed stock CLI audio
kickoff left four remote artifacts in a new notebook. The outer runner did not retry. All unexpected
artifact ids were recorded for preservation instead of choosing a favorable output. The trial was not relabeled a valid four-output pass.

Pinned-source inspection and mocked transport tests confirm that the inspected 0.15.1 and 0.15.6 upstream
audio paths can replay mutations after some HTTP/RPC/auth failures; CDP is not a safe blanket workaround.
That demonstrates a replay mechanism, not the exact historical response sequence. The bundled narrow
single-dispatch adapter passed independent review and 21 tests, including exact-upstream mocked failure
scenarios. The combined package suite passed all 97 tests with upstream compatibility cases enabled; the
read-only runtime fingerprint probe passed without loading authentication. These initial checks were
offline. In the subsequent two-case Brief study below, passive Python call observation recorded one
adapter POST, one HTTPX POST and one transport call per successful kickoff; each separate notebook
contained its one intended source and exact returned audio artifact. This is narrow client-side execution
evidence, not Google-side exactly-once proof. No extra generation was added to test the guard.

## Brief-preset check: failed; publication remains held

The [separately preregistered Brief study](brief-validation-protocol.md) ran on 2026-10-19 using frozen
source commit `7700755`. It used the same fictional prose, facts and order, with Brief/default/English
and the compatible short single-speaker focus. This tests a preset bundle, not the causal effect of
format alone. All four ambiguous artifacts from the prior incident had reached terminal failure before
admission; none had a completed file to select. Existing quota was 100% rolling and 91.5% weekly available.
All 99 package tests, including exact-upstream adversarial transport cases, and the pinned runtime probe
passed before dispatch. The study used exactly its two permitted generations, one per case, without retries.

Both complete files were locally transcribed and independently reviewed against the frozen evidence.
Scores below are **factual support / coaching usefulness / concision / natural address / usable closing
experiment**, each 0–2. Hard vetoes override the total.

| Case | Measured seconds | Five scores | Total | Acceptance |
|---|---:|---|---:|---|
| A | 103.398458 | 0 / 1 / 1 / 2 / 2 | 6/10 | Failed: factual and opening-editorial vetoes |
| B | 93.738957 | 2 / 1 / 1 / 2 / 2 | 8/10 | Failed: opening-editorial veto |

- **Case A, 00:32.840–00:37.000:** “how much time that saved you” presupposes a time saving that the
  record does not establish. The successful targeted check and absence of a rewrite do not measure a
  counterfactual benefit.
- **Case A, 00:59.320–01:09.240:** “forcing an 8-minute rollback” converts the eight-minute interval from
  conditional instruction to rollback completion into a rollback duration. No rollback start or labor
  duration was recorded. The later visitor-log caveat does not repair that invented metric.
- **Both openings:** a generic explanation of the review's method preceded the first decision (Case A
  00:04.200–00:16.200; Case B 00:03.000–00:18.000). The frozen fact sheet expressly prohibits a generic
  methodology preamble. Useful later coaching does not waive this gate.
- **Case B:** preserved the unknown running outcome and the distinction between a confirmed commit and
  a merely reported restart. Its 8/10 score is not acceptance. Omitting the end-to-end versus handler-only
  measurement labels also weakened the practical lesson without inventing a component-level cause.

Both met the 150-second limit, used direct address, covered the two selected moments in order and ended
with one usable experiment and observable check. Neither added an unrelated philosophical epilogue.
Those successes do not cancel the failures.

**Review scope:** all 26 Case A and 24 Case B ASR segments were checked, spanning 0–103.16 and 0–93.40
seconds respectively. Full-file transcription and timestamp coverage are not acoustic listening: no
sound-quality or complete-listening pass is claimed. Subsecond segment gaps/tails remain unverified.
Original files, transcripts, dispatch observations and failures are preserved outside this source repository.

**Conclusion:** the two-generation budget is exhausted and the public-release gate failed. Do not
regenerate, choose a favorable artifact, change thresholds, or publish a local-only substitute as completion.
The remaining blocker is narration fidelity and the frozen opening requirement, not quota or unfinished
collector/driver integration. Any later candidate requires a separate preregistered study and generation
budget; no further study is scheduled by this package. The earlier failed trial remains failed too.

These are two development observations, one realization per case: headroom to ten was four and two
points. They establish neither a population noise floor, general format superiority, statistical
significance nor reliability on private sessions. See [the original protocol](evaluation-protocol.md),
[frozen facts](../examples/fact-sheet.md), and [full-episode QA](audio-qa.md).

## Narration climb: opening fixed, fidelity not; audio ships gated per episode

The [narration climb](narration-climb.md) was pre-registered on 2026-10-21 and amended by the owner the same day
to one generation per round with a Pareto goal. It tested the two levers this package controls, the uploaded
narration and the focus prompt, with Brief / short / English on three fictional cases. 20 generations were
requested in total: 14 produced audio and were scored, and 6 were ambiguous single-send kickoffs that ended
`failed` on Google's side with no audio (none was resent).

| Variant | Scored | Accepted | Opening ok |
|---|---:|---:|---:|
| Baseline Brief focus (v0) | 4 | 0 | 0 |
| Affirmative-only source (v1) | 4 | 0 | 0 |
| First-sentence opening (v2, now the default) | 5 | 2 | 5 |
| v2 plus “do not mention durations or savings” (amended r2) | 1 | 0 | 1 |

v2's two accepted episodes are counted after the title-line checker fix (a spoken title line no longer makes an
episode `unverified`). Every rejection was a checker `rejected` decision on a flagged claim or a failed opening;
no episode exceeded 150 seconds. The most common remaining failure is a time saving, prevented damage or an
interval voiced as a measured result. A focus sentence that names it did not stop it in its one scored episode
(“you absolutely protected the real data”), so it was not shipped.

**Decision.** Ship the opening fix as the Brief default. Keep audio experimental, gated per episode by
`check-narration`: an episode it does not accept is never delivered, and the user is offered one regeneration
or the local report. With the shipped defaults expect roughly 2 in 5 Brief episodes to pass on cases like these.
That figure rests on 5 episodes and is directional only; it is not a rate to promise on private sessions.
