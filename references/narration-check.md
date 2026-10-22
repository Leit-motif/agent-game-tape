# Claim-level narration check

An audio episode can sound right and still get facts wrong. `game_tape.py check-narration` reads a complete
ASR transcript of the episode, splits it into sentences, and checks every factual claim against the run's
`evidence.json` and `review.json`. It writes a receipt that lists each claim, the evidence it relies on, and
a decision: `accepted`, `rejected` or `unverified`.

`accepted` means this checker found no flagged claim and the episode opened on the first selected moment.
It does not mean a person listened to the sound or that the transcript is complete. The checker never
accepts audio on its own authority.

```bash
python3 scripts/game_tape.py check-narration --run /private/run \
  --transcript /private/run/audio.json --out /private/run/narration-check.json
```

The transcript is usually ASR of a Gemini Notebook (formerly NotebookLM) episode, but any narration of the
same review can be checked.

Exit status: 0 accepted, 1 rejected or unverified, 2 usage or input error.

## Pipeline

1. **Sentences (deterministic).** ASR segments are joined and split into sentences. Each sentence gets
   the start of its first overlapping segment and the end of its last; no sub-segment precision is claimed.
2. **Claims and roles (semantic).** One backend call receives the numbered sentences, every evidence event,
   the selected moments, the experiment and the strength-change taxonomy. It returns a role for each
   sentence and atomic consequential claims, each tied to sentence ids, evidence ids and a label.
3. **Validation (deterministic).** Sentence ids, evidence ids, labels and taxonomy slugs must exist. Every
   sentence must be covered by a claim, except greetings before the first other sentence and a title or greeting
   line among the first five sentences (Brief often speaks its title right after the opening quote). That line is
   recognised from its text, not from the model's role alone: at most 12 words, no digits, and a title or greeting
   form such as "This is the brief on …" or "Welcome …". A `supported` claim must cite evidence.
   Malformed or incomplete backend output makes the decision `unverified`, never `accepted`.
4. **Opening (deterministic over roles).** Greetings and pure connective tissue may come first. The first
   other sentence must have role `moment:1`, the first selected decision. Methodology, source-collection,
   overview or any other role there fails the opening.
5. **Decision.** `rejected` if any claim is `strengthened:*` or `unsupported`, or the opening fails.
   `unverified` if the backend output is invalid. Otherwise `accepted`.

## Labels

- `supported`: the cited evidence or reviewed text entails the claim at the same strength. Paraphrase,
  rounding-free restatement and omission are allowed.
- `strengthened:<type>`: a real fact restated more strongly than the record allows.
- `unsupported`: an event, metric, motive, cause or actor the record does not contain.
- `non-factual`: advice, proposals, framing, encouragement and questions. Advice narrated with a measured
  benefit is not non-factual: it is `strengthened:proposal_as_result`.

Evidence ids are the event ids in `evidence.json` plus `review:m<N>` (moment N's reviewed text),
`review:experiment` and `review:blind_spots`.

Sentence roles: `greeting`, `methodology`, `moment:<N>`, `experiment`, `other`.

## Strength-change taxonomy

From [full-episode QA](audio-qa.md):

| Slug | Strength change |
|---|---|
| `report_as_fact` | assistant report → established fact |
| `absent_cost_as_zero` | absent evidence of cost → zero cost |
| `unmeasured_as_measured` | no measurement → a measured cost, saving or benefit |
| `unverified_as_failed` | unverified deployment → failed (or successful) deployment |
| `interval_as_labor` | elapsed interval → wasted labor, task duration or continuous outage |
| `overlap_as_parallel` | overlapping workers → every second spent in parallel |
| `commit_as_restart` | commit receipt → proof a running service restarted |
| `invented_dependency` | adjacent qualifications → an invented dependency |
| `invented_internals` | inadequate verification → a made-up explanation of model internals |
| `blame_shift` | agent execution failure → an indictment of the human's instruction |
| `proposal_as_result` | proposed advice → a measured or observed result |
| `other` | any other strength change; the rationale must name it |

## Receipt

`agent-game-tape/narration-check-v1` records the decision and reasons; SHA-256 hashes of the transcript
file, evidence, review, prompt and raw backend response; the backend name, model and model status; every sentence with
timestamps; every claim row (sentence ids, start, end, text, label, evidence ids, moment, rationale); the
opening result; and the limits below.

## Model

The checker uses the tested model (`claude-opus-5-5`, set in `scripts/models.py`) by default. Its evaluation
results were measured with that model only. `--model` selects another one:

```bash
python3 scripts/game_tape.py check-narration --run /private/run \
  --transcript /private/run/audio.json --out /private/run/narration-check.json --model OTHER_MODEL
```

The receipt records `backend.model` and `backend.model_status`. `model_status` is `tested` for the tested
model and `unvalidated` for anything else. With an unvalidated model the command also prints a warning:
checker results were validated only with the tested model, so treat that receipt as unvalidated.

## Backends

The default backend runs the local Claude CLI (`claude -p --model MODEL`) in safe mode (no CLAUDE.md,
memory, skills, plugins or hooks) with a minimal system prompt, tools disabled, no session persistence and
structured JSON output. It removes `ANTHROPIC_API_KEY` from its environment so it uses the existing
subscription login rather than a paid key. Tests use an offline fake backend. A backend is any object with
`name`, `model` and `complete(prompt, schema) -> dict`.

## Limits

The semantic step is a model judgment and can vary between runs. On its pre-registered evaluation the
checker caught 48 of 48 labelled failures, flagged 0 of 969 faithful claims, made 54 of 54 correct
decisions, and gave the same result for all 18 cases across 3 runs. Read that as directional: it is a small
fictional development set with two scenarios at Brief length and no held-out set. Details are in
[the checker evaluation](checker-eval.md). Sentence-level timestamps are as coarse as the ASR segments. A
transcript cannot reveal sound quality, and ASR errors can look like narration errors. An `accepted` receipt
does not replace the editorial receipt in [full-episode QA](audio-qa.md).
