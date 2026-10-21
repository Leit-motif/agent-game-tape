# Narration hill-climb — fixed before any generation

> **In short**
>
> - **Question:** can the two levers this package controls, the narration source it uploads and the focus
>   prompt, make Gemini Notebook (formerly NotebookLM) episodes pass the claim checker often enough to call
>   audio reliable?
> - **Design:** three fictional cases, two generations per case per variant, Brief / short / English held
>   fixed, at most 24 generations in total. One change per round, scored by `check-narration` and measured
>   duration.
> - **Integrity:** this protocol, the cases, the variant code and the bar are committed before the first
>   generation. Results are appended under the line at the end, never edited into the rules.

Tracking issue: [#5](https://github.com/Leit-motif/agent-game-tape/issues/5). This study follows the
hill-climbing method: eval and thresholds first, one change per round, every output kept.

## Question

Starting from the current renderer and bundled Brief focus (the baseline), does a change to the narration
source or the focus prompt raise the share of episodes that pass the per-episode bar below?

## Fixed settings (not tuned)

- Format `brief`, length `short`, language `en`, web research off, one source per notebook.
- One new notebook per generation. Upload and kickoff through `scripts/notebooklm.py start` with the
  single-send adapter; download through `wait --download`.
- The uploaded source is always passed as `--source` so its file name (`01-game-tape.md`) is identical in
  every arm. The baseline source is byte-identical to `game_tape.narration(bundle, review, 'prose')`.

## Cases and truth

All entirely fictional; no private transcripts.

| Case | Defined in | Frozen facts |
|---|---|---|
| A — filter regression, conditional publish | `examples/make_demo.py` | `examples/fact-sheet.md` |
| B — phone latency, commit vs restart | `examples/make_demo.py` | `examples/fact-sheet.md` |
| C — sample migration, delegated fix (new) | `tests/fixtures/narration-climb/case-c.json` | `examples/fact-sheet.md` |

Case C was written for this study, against the current review contract and before any narration of it
existed. Every arm scores against the same frozen `evidence.json` and `review.json` of its case; a variant
changes only what is uploaded, never what the checker compares against.

## Scorer

Per episode, in `examples/narration_climb.py score`:

1. Duration measured with `ffprobe` on the downloaded file.
2. Full-file local ASR: `whisper --model small --language en --output_format json` (the install and model
   the 2026-10-19 Brief study used).
3. `game_tape.py check-narration` with the tested model (`claude-opus-5-5`), one run, against the frozen
   evidence and review. Its pre-registered evaluation: 48/48 labelled failures caught, 0/969 false flags,
   stable verdicts ([checker evaluation](checker-eval.md)).

Sanity check before this commit: on the two 2026-10-19 Brief transcripts this scorer rejected both, with
Case A's presupposed time saving and eight-minute rollback flagged and both openings failed, matching the
labelled truth; a fresh whisper run covered each full file (last segment within 0.6 s of the end).

**An episode is accepted** when all three hold: the checker decision is `accepted`, the opening check is
ok, and the measured duration is at most **150 seconds**.

Failure types recorded per episode: each `strengthened:<slug>`, `unsupported`, `opening`, `duration`,
`unverified`. A failed or ambiguous generation (no downloadable audio) is a harness error: it counts against
the budget, is reported, and is excluded from the accepted-rate denominator.

Guardrail, reported for every episode: **coverage** — the checker's sentence roles include every selected
moment and the experiment.

## Variants and rounds

Each variant is 3 cases × 2 reps = 6 generations. Round order is fixed now:

| Round | Change (one per round) | Source | Focus |
|---|---|---|---|
| v0 | Baseline: current main renderer and bundled Brief focus | `main` | `bundled` |
| v1 | H1 source: the spoken source keeps only affirmative content. Outcome sentences that contain a negation or a stated interval, the `causal_basis` audit line, and clock times are left to the local report. | `affirmative` | incumbent |
| v2 | H2 opening: the focus names the literal first sentence (`You said, “<first quote>”`) instead of “Begin with the first decision”. | incumbent | `first-sentence` |
| v3 | Reserved: one source-or-focus change chosen from the v0–v2 failures, written into `v3/README.md` with its code before its first generation. Skipped if no failure type remains. | | |

"Incumbent" is the best variant so far under the keep rule. The v1 and v2 definitions are the code in
`examples/narration_climb.py` at the commit that adds this file.

## Decision rules

Let *k* be a variant's accepted episodes out of its scored episodes (normally 6).

- **Keep (becomes incumbent):** *k* ≥ the incumbent's *k*, no failure type absent from every baseline
  episode, and coverage not lower than the incumbent's by 2 or more episodes. Ties go to the later round.
  A **gain** is *k* strictly greater than the incumbent's.
- **Winner (changes the shipped defaults):** the final incumbent beats the baseline by at least **3
  accepted episodes of 6** (+50 points), has no failure type absent from every baseline episode, and does
  not lose coverage by 2 or more episodes. Anything less is noise at this sample size and the defaults stay.
- **Noise floor and headroom:** with 6 episodes per arm, one episode is about 17 points and a 95% interval
  on a difference of proportions spans roughly ±50 points; +3 of 6 is the smallest gain treated as real, and
  it is directional, not significant. If the baseline accepts 4 or more of 6, the headroom is under the
  smallest detectable gain; the study then reports that and stops without declaring a winner.
- **Audio reliability:** audio may drop the experimental label only if the winner accepts at least 5 of 6
  with no factual failure in any episode. Otherwise audio stays experimental whatever the winner.

## Budget and stopping

- **Cap: 24 generations** (4 variants × 6). Stop at the cap. Every kickoff counts, including failed ones.
- Stop early at 3 consecutive rounds without a gain, or when v3 has no failure type left to target.
- Quota only, no money, nothing purchased. Before each round read `nlm usage`: proceed only with at least
  25% rolling and 10% weekly remaining; otherwise wait for the reported reset.
- Canary: the first generation of the study (v0, case A, rep 1) must download, transcribe and score
  end to end, and its recorded artifact must show `brief`/`short`, before the remaining 23 can start.
- Never blind-retry a kickoff. An ambiguous kickoff stops that run until read-only reconciliation of the
  exact notebook; zero immediate matches is not permission to resend.

## Records

Runtime outputs stay outside the repository, under one climb root with `vN/case-X/rep-R/` folders holding
the run, `notebooklm-state.json`, `audio.m4a`, `asr/audio.json`, `narration-check.json` and `score.json`.
Each round has `vN/README.md` with the change, why, the diff and a `suspicious` note when a score jumps more
than the change explains. No output is deleted or replaced, and no favourable rep is selected.

## Limits

Three fictional cases and two reps per case: every number is directional. All cases are scored every round
and there is no held-out split; a winner could still overfit these cases. Rounds run sequentially, so
renderer drift over the study day is confounded with round. The checker judges a transcript, not sound;
ASR errors can look like narration errors. A passing episode is not proof the next one will pass.

---

## Results

Appended after each round.
