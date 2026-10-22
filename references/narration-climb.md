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

### v0–v2 (as recorded in the runtime round READMEs, 2026-10-21)

| Round | Generations | Scored | Accepted | Opening ok | Failure types | Harness errors |
|---|---|---|---|---|---|---|
| v0 baseline | 6 | 4 | 0 | 0/4 | opening, strengthened:blame_shift, strengthened:other, strengthened:unmeasured_as_measured | 2 (ambiguous send, artifact `failed`) |
| v1 affirmative source | 6 | 4 | 0 | 0/4 | opening, strengthened:other, strengthened:proposal_as_result, unsupported | 2 (same) |
| v2 first-sentence focus | 6 | 5 | 0 | 5/5 | strengthened:interval_as_labor, strengthened:other, strengthened:unmeasured_as_measured, unverified | 1 (ledger n=18, artifact `07c51059` ended `failed`) |

Under the keep rule no variant was kept (v1 and v2 each added a failure type absent from the baseline) and none
gained; incumbent v0. v3 (no-overview focus, committed in c29ccba) was prepared but never kicked off. 18 of 24
generations used.

## Protocol amendment (owner rulings), 2026-10-21

Recorded before any further generation. Everything above this heading, including the v0–v2 results, is unchanged.

The owner (Amrit) ruled, 2026-10-21:

> 20:52: "You are doing too many generations per epoch. Let's do one at a time."

> 20:53: "Be reasonable considering that this is not our platform. This is Google. It feels relatively opaque.
> We're looking for that pareto minimum."

Reading: the goal is the smallest set of changes that buys most of the fidelity, not a fact-perfect renderer.
Product reliability comes from the per-episode gate (`check-narration` rejects a bad episode; the local report is
always the fallback), not from Google's output. What changes from here:

1. **v3 is superseded.** It is never kicked off; its prepared folders stay as they are, unused.
2. **Checker gap fixed before scoring anything new.** A sentence the checker labels `greeting` that is
   mechanically a title or greeting line (for example Brief's "This is the brief on your human AI teamwork.",
   which it speaks right after the opening quote) no longer makes an episode `unverified` when it is left
   without a claim. The test is lexical, not the model's role alone, so a content sentence mislabelled
   `greeting` mid-narration still makes the output invalid. The two v2 `unverified` episodes are rescored by
   re-validating their recorded roles and claims (no new model call) into new files; the original receipts and
   `score.json` files are kept.
3. **Start point: v2's opening fix.** Owner direction. It cured the opening on 5/5 episodes (v0/v1: 0/8); the
   failure types that kept it from the incumbent under the keep rule were the checker fault in (2) and the
   eight-minute interval claim, which is the same failure the 2026-10-19 Brief study and this study's scorer
   sanity check found with the baseline renderer.
4. **At most 4 more generations (ledger n=19–22), one per round, strictly sequential.** Each round: one
   generation of the current variant on one case, then download, transcribe, score; only then the next
   change, committed with its code before its generation. Case rotation: A, C, B, A. Round folders are
   `rN/case-X/rep-1` under the same climb root. Same fixed settings, scorer, acceptance bar (checker
   `accepted`, opening ok, at most 150 s) and quota gate as above.
5. **Change choice.** Each change targets the most frequent failure type remaining in scored episodes of the
   current variant's lineage (v0 and v2 share the main source). Round 1's change is chosen from the v0–v2
   failures before its generation.
6. **Gain and stopping.** A round's change shows a gain when its episode is accepted. Stop as soon as a change
   shows no gain, or when the 4 generations are used. A failed generation (no downloadable audio) is a harness
   error: it uses budget, says nothing about the change, and the next round runs the same variant on the next
   case. No change is made after the last generation.
7. **What ships.** v2's opening fix becomes the bundled Brief default whatever the rounds show. A later change
   ships only if its round showed a gain. Audio stays experimental and is gated per episode: an episode that
   `check-narration` does not accept is never delivered; the user is offered one regeneration or the local
   report.

With one generation per round every result is an anecdote, not a rate. The amendment trades statistical power
for the owner's stated priority: little platform use and a working per-episode gate.

### Checker fix and v2 rescore (amendment item 2)

`claim_check._validate` excuses an uncovered `greeting` that is a title or greeting line by its text (at most 12
words, no digits, a title or greeting form) among the first five sentences. Replaying all 13 recorded receipts
through the new validation reproduced every label and role and changed two decisions, both v2 Case B, from
`unverified` to `accepted` (97.2 s and 85.2 s, opening ok, no flagged claim). Every other decision is unchanged;
v2 Case A rep 1 and Case C rep 1 had the same uncovered title line but stay `rejected` on their flagged claims.
The checker-evaluation round had no `unverified` decision, and the change only removes coverage problems, so
none of its 54 decisions can change. v2 after rescore: 2 of 5 scored episodes accepted (v0: 0/4, v1: 0/4).

### Amended rounds (2026-10-22)

| Round | Ledger | Variant | Case | Outcome | Seconds | Opening | Flagged claims |
|---|---|---|---|---|---:|---|---|
| r1 | 19 | v2 focus + “no durations, time, damage or effort saved” | A | harness error: ambiguous kickoff (exit 2), reconciled to one matching artifact, which ended `failed` | — | — | — |
| r2 | 20 | same as r1 (item 6: a failed generation says nothing) | C | rejected | 106.7 | ok | `strengthened:unmeasured_as_measured`: “you absolutely protected the real data” |

r2 did not repeat v2 Case C's flag (“No rerun occurred.”), but voiced the prevented-damage claim that the added
sentence names. The episode was not accepted, so the change showed no gain and the study stopped (item 6) at ledger
n=20, 2 of the 4 amended generations used. The no-durations sentence does not ship. What ships is v2's opening fix
as the bundled Brief default (item 7), and the per-episode gate in `SKILL.md`.

**Over the whole study (20 kickoffs).** 14 produced audio and were scored. All 6 that did not produce audio were
ambiguous single-send kickoffs (exit 2). Each was reconciled read-only to exactly one matching artifact, which stayed
`in_progress` for about two hours and then ended `failed`. None was resent.

| Lineage | Scored | Accepted | Opening ok | Episodes with a factual flag |
|---|---:|---:|---:|---:|
| Old Brief focus (v0, v1) | 8 | 0 | 0 | 6 |
| First-sentence opening (v2, shipped default) | 5 | 2 | 5 | 3 |
| First-sentence + no-durations sentence (r2) | 1 | 0 | 1 | 1 |

The opening fix is the one clearly helpful change (0 of 8 openings to 6 of 6). The factual flags that remain are
led by one family: a time saving, prevented damage or an interval voiced as a measured result (6 of the 10 flagged
episodes; the other 4 strengthened a different claim, such as a proposal voiced as a result). One prompt sentence
aimed at that family did not stop it in its one scored episode. With the shipped defaults, read the accepted rate as about 2 in 5 with Brief on these fictional cases. That is an anecdote-sized
estimate, not a rate to promise. The gate, not the renderer, makes delivered audio trustworthy.
