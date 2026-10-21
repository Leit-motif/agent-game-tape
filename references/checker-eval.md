# Narration-checker evaluation — fixed before any checker run

This protocol, the labelled cases and the round-1 checker (prompt, schema and code) are committed together
before the checker is run on any case. Results are appended below the line, never edited into the rules.

## Question

Does [`check-narration`](narration-check.md) reliably flag the strength changes that full-episode QA
found in real narrations, without flagging faithful claims, and give the same verdict on repeated runs?

## Cases and truth

Labels were written by hand from the frozen [fact sheet](../examples/fact-sheet.md), the
[validation record](validation.md) and its independent review, before any checker output existed.

**Brief study (real NotebookLM output, fictional cases).** The two 2026-10-19 Brief transcripts are runtime
outputs and stay outside git. Their labels are in `tests/fixtures/narration-eval/brief-study-truth.json`
with the SHA-256 of each transcript file. Labelled failures: Case A's presupposed time saving (A-F1) and
eight-minute rollback (A-F2), and both openings. Labelled supported claims: six in Case A and nine in Case B,
including Case B's unknown running outcome and its confirmed commit versus reported restart. Sentences that
neither source judged (for example advice, analogies and Case A's closing "will ensure" line) are unlabelled.

**Synthetic set (fictional, committed).** `tests/fixtures/narration-eval/synthetic-cases.json`: faithful base
narrations for Case A and B; ten single-sentence perturbations, one for each taxonomy slug except `overlap_as_parallel`
(neither case has overlapping workers) and `other`; one methodology-preamble opening per case; and faithful paraphrases with hard
negatives that sit next to each failure mode. Every unperturbed sentence is labelled supported, except
title or greeting lines and inserted preamble sentences.

An independent audit of every label, before freezing, led to rewording nine synthetic sentences that it found
wrong or arguable, and to dropping two arguable Brief labels: Case B's "4.2 seconds on the phone and just 0.3
seconds locally" (it loses the end-to-end versus handler-only boundary) and Case A's "massive" rewrite.

| Set | Cases | Failure items | Supported items |
|---|---:|---:|---:|
| Brief study | 2 | 4 (2 claims, 2 openings) | 13 |
| Synthetic perturbations | 10 | 10 | 180 + 10 openings |
| Synthetic opening preambles | 2 | 2 openings | 38 |
| Synthetic faithful narrations | 4 | 0 | 78 + 4 openings |
| **Total per run** | **18** | **16** | **323** |

Expected decisions: 14 `rejected`, 4 `accepted`.

## Scoring

A run is one independent checker call per case. Each labelled item is located by its quote in the
sentence list the checker produced.

- A failure item is **caught** if any claim covering one of its sentences is `strengthened:*` or `unsupported`.
  An expected opening failure is caught if the receipt's opening check fails.
- A supported item is **falsely flagged** if any claim covering one of its sentences is `strengthened:*` or
  `unsupported`. An expected valid opening is falsely flagged if the opening check fails.
- An `unverified` run misses every failure item in its case and fails stability.
- Flags on unlabelled sentences are recorded with their text and adjudicated in the report. They are not in
  the bar. Taxonomy agreement with `expected_type` is reported as a secondary number, not gated.

`scripts/narration_eval.py` computes these from the receipts and writes raw rows to `rows.jsonl`.
Each round runs, from a clean tree whose commit is recorded in `summary.json`:

```bash
python3 scripts/narration_eval.py --runs 3 --jobs 4 --out /private/eval/round-N \
  --cases tests/fixtures/narration-eval/brief-study-truth.json \
  --cases tests/fixtures/narration-eval/synthetic-cases.json \
  --external brief-case-a=/private/brief/case-a/audio.json --external brief-case-b=/private/brief/case-b/audio.json
```

## Pass bar (fixed)

Over three runs per case with `claude-opus-5-5` through the local Claude CLI subscription:

1. 100% of labelled failure items caught in every run.
2. Zero false flags on labelled supported items in any run.
3. Each case's decision identical across its three runs, with no errors or `unverified` runs.

All three must hold on the full set in the same round.

## Iteration

At most three rounds in total, each on the full set and each with three runs per case. Between rounds only the
checker (prompt, schema, deterministic code) may change. Cases, labels, quotes and this bar are frozen: a
suspected label error is reported as such, still counts in that round, and is not corrected here. Each failure
is recorded with a root-cause bucket: semantic miss, semantic over-flag, opening-role error, sentence or
alignment error, invalid backend output, transport error, or run-to-run instability.

## Limits

Small labelled set, one renderer, two fictional scenarios: results are directional, not a population
reliability estimate, and there is no held-out set. Iterating on the full set can overfit; a later round's
pass is a development result. The Deep Dive renderer-trial transcripts (17–18 minutes) are not scored here.
No sound is reviewed. Unit tests use a fake backend and say nothing about model behaviour.

---

## Results

Appended after each round.

### Round 1 — checker at `a35d01e`: failed the bar by one run

| Measure | Result |
|---|---|
| Labelled failures caught | 47/48 (16/16, 15/16, 16/16 per run) |
| False flags on labelled-supported items | 0/969 |
| Strength-change type matched | 36/36 |
| Decisions correct | 53/54; 17 of 18 cases stable |
| Errors | 0 |

Both real Brief transcripts were rejected in all three runs: Case A 9/9 failures caught, Case B 3/3, no false
flags. All four faithful-paraphrase cases were accepted in all runs. The single miss: `b-opening-preamble`
run 2 returned `unverified` instead of `rejected`. Its roles were valid and the opening check correctly
found the preamble (s2, s3), but the model left methodology sentence s2 without a claim, so coverage
validation marked the whole output invalid before the opening rejection could apply. **Bucket: invalid
backend output** (decision precedence), not a semantic miss.

Round-2 change: coverage gaps alone no longer hide an established rejection. When the only validation problems
are uncovered sentences and the roles are valid, a failed opening or a flagged claim still rejects, and the
gaps are listed. A coverage gap can never lead to acceptance; with no established failure it stays `unverified`.

### Round 2 — checker at `416a878` (clean tree): **passed the bar**

| Measure | Result |
|---|---|
| Labelled failures caught | 48/48 (16/16 in every run) |
| False flags on labelled-supported items | 0/969 |
| Strength-change type matched | 36/36 |
| Decisions correct | 54/54; all 18 cases stable |
| Errors / `unverified` | 0 / 0 |

Both real Brief transcripts were rejected in every run for the reasons the human review found; all four
faithful paraphrases were accepted in every run. No round-2 receipt contained an uncovered sentence, so the
round-2 code path was not exercised: this pass also reflects run-to-run variation, and the round-1 failure
mode would now reject instead of returning `unverified`. One unlabelled flag appeared on Case A (round 1:
three), on a sentence the frozen labels left out as borderline; it does not affect the bar.

**What this establishes:** on this small, fully seen set (two fictional scenarios, one renderer, Brief
length), the checker separates labelled strength changes and preambles from faithful narration with no
false flags and stable verdicts. Directional, development-set evidence: no held-out set, no private sessions,
no Deep Dive-length transcripts, no sound. Treat a rejection as actionable and an acceptance as strong but
not proof; new failure types should be added as cases before they are trusted.
