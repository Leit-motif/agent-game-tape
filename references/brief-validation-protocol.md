# Brief-preset validation — fixed before generation

The earlier source-renderer comparison failed: the complete Case A fielded and prose narrations both
scored 4/10 and contained material unsupported claims. The intended four-output trial also suffered a
transport-integrity failure: one failed command left four remote artifacts. That trial is not relabeled
as a pass, and no favorable artifact is selected from the ambiguous outputs.

## Question and candidate

Does a deliberately short, single-speaker coaching preset produce a faithful, usable debrief on the two
already frozen fictional cases? This tests a **preset bundle**, not an isolated causal effect of format:
Brief format requires compatible single-speaker focus wording instead of the previous two-coach framing.

Freeze before dispatch:

- the same Case A and Case B evidence/reviews in `examples/make_demo.py`, same prose renderer, selection,
  facts, order, uncertainty and next-run experiments as the first trial;
- one immutable narration source per case, explicit source ids, English, format `brief`, length `default`;
- focus assembled from `audio-focus-brief.txt` with the same supported-experiment closing for both cases;
- the single-send audio adapter, version/fingerprint checks, source/focus/evidence/review hashes, and exact
  returned artifact ids;
- a new notebook for each case, containing only its intended narration packet.

The previous Deep Dive Case A is a diagnosed development baseline, not a fresh time-paired control. Do
not claim isolated format superiority, population reliability, held-out generalization, or statistical
significance from this check. Case B's unplanned extra artifacts are preserved separately, not cherry-picked
into a clean control arm.

## Budget and admission

At most **two new audio generations**, one per case, one adapter dispatch each. No retry for a disappointing
successful narration. Any failed or ambiguous kickoff stops the study until read-only reconciliation;
zero immediate matches is not permission to resend. Do not bypass the limit through another client.

No paid model/API credits or capacity purchase. First reconcile the prior ambiguous artifacts by read-only
status and preserve every completed output; do not start the new study while those prior generations are
still pending. Wait for existing quota refresh and verify at least 25%
rolling availability and at least 10% weekly availability before starting. If lower, wait for the provider's
reported reset. This availability bar is a conservative admission rule, not a per-episode cost estimate.
The previous unintended overrun is an incident, not authorization for more requests in that trial.

## Acceptance, fixed before outputs

Both complete narrations must independently meet all of these:

1. Zero material invented events, actor attributions, metrics, motives, causal mechanisms, or transformations
   of unknown outcomes into established facts. Use the original frozen fact sheet.
2. No collection/methodology/source recital in place of the actual review.
3. Direct address to the person, two selected moments accurately covered, and an actionable closing experiment
   with its observable next-run check. No unrelated question or philosophical epilogue after that close.
4. Measured duration no more than **150 seconds** per audio. This is an acceptance limit, not a claimed exact
   NotebookLM duration control.
5. Full local ASR with end-to-end timestamp coverage and an independent semantic review. Regex scans alone
   cannot pass it. State transcript-versus-sound review scope; do not claim a complete listening pass.
6. At least **8/10 each** using the original five 0–2 metrics: factual support, coaching usefulness, concision,
   natural address and usable closing experiment. Factual and other hard vetoes override the numeric total.
7. Exactly one recorded adapter POST per requested audio, with no hidden retry/recovery/CDP path. The adapter
   must pass offline adversarial transport tests before either live request.

Record every result and raw per-case score, including failures. One generation per case cannot establish a
credible population noise floor. If either fails, keep publication held and report the specific failure;
do not loosen a gate after seeing output. A pass supports an explicitly experimental public preset, not a
promise that any input will be narrated accurately or that all hosts/platforms were live-tested.
