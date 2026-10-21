# Behavioral release gate

This is the test a change to the narration or audio step must pass before it ships. Passing unit tests
shows the code works; it does not show that Gemini Notebook (formerly NotebookLM) narrated an episode
accurately. This protocol checks the audio itself: fixed fictional cases, facts written down before any
generation, zero-tolerance gates for invented facts, and a small scored comparison. The first trial run
under it failed; the results are in [validation.md](validation.md).

*Naming note:* NotebookLM was renamed Gemini Notebook. The protocol text below is kept as written, so it
uses the earlier name.

This protocol is fixed before generating revised candidate episodes. Historical observations diagnose
failures; they are not a controlled A/B and cannot establish causation.

## Scope and budget

- Work locally until the release gate passes. Do not change anyone's installed workflow or schedule.
- No paid model/API credits. Use existing subscriptions and NotebookLM quota; stop on quota failure.
- Maximum four new NotebookLM audio generations in this evaluation: two paired source cases × baseline/candidate.
- A single pair is a canary. Run the second pair only if the transport, selected sources and focus are confirmed.
- Keep each pair's verified facts, coaching conclusions, format, language, and length setting fixed. Change
  only the source renderer (fielded audit versus narration-ready prose) in round one. Focus-prompt changes
  and format/length changes require separate later experiments, not a bundled 'prompt improvement'.
- Use fictional scenarios for public examples. Private historical audits and transcripts never enter git.

## Test cases and truth

Use two synthetic workstreams, each with a human steering quote, subsequent agent action, and explicit
verification evidence. Include one successful steering move, one costly move with measured rework, one
unchecked outcome, and one tempting but unsupported causal interpretation. Write the facts and forbidden
claims before generating audio. Preserve chronology and latest explicit human intent.

Deterministic regressions must cover: user versus tool/agent authorship; Codex duplicate event streams;
subagent exclusion; valid human messages beginning with Markdown; half-open date boundaries and daylight
saving; missing/malformed evidence; exact quote provenance; invalid rule ids; quiet days; duplicate moments;
unknown outcome versus failed outcome; local evidence excluded from upload; changed sources on resume;
concurrent publication; uncertain remote writes; generation completed versus audio quality accepted.

## Hard gates (zero tolerance)

1. Every quoted human call is a substring of a cited human-authored event, not a selected agent label.
2. Every selected moment names a supplied rule and cites subsequent evidence. Structural validation does not
   prove semantic relevance or causation: a separate reader must check those against the original record.
3. The upload is an explicit allowlist of narration sources, not a recursive directory or raw session dump.
4. A full-episode transcript exists before editorial acceptance. 'Opening checked', 'prompt accepted', and
   'generation completed' each mean only that; none implies full-audio acceptance.
5. No materially unsupported fact, invented metric, motive, or claim that unchecked work failed.
6. No source-collection recital or framing the sole listener as a third-person case study.
7. Exactly one actionable experiment closes the episode, tied to reviewed evidence and an observable next-run check.

## Directional comparison (small sample)

Score each audio transcript blind to arm on: factual support (0–2), coaching usefulness (0–2), concision
(0–2), natural address (0–2), and usable closing experiment (0–2). Judge against the frozen fact sheet,
not which arm sounds more polished. Separate stylistic mentions from material factual failures.

Candidate release needs all hard gates, no guard metric regression, and at least a two-point aggregate
improvement over baseline across the two pairs. Otherwise keep the latest artifact local, report the failure,
and revise only a failure the eval can observe. Stop after two renderer revisions or the generation cap,
whichever comes first. Do not relabel cases or loosen gates to publish.

This sample cannot measure a credible population noise floor or prove a general improvement. Report raw
per-case scores, repetitions (one per arm/case), headroom to the ten-point ceiling, and stochastic limitations.
Do not claim statistical significance. A passing candidate supports an experimental public release, not a
promise that NotebookLM follows a script or a guaranteed duration.

## Controls to measure separately

Source word budget and moment count are hard inputs, not guarantees of spoken duration. Keep requested
minutes (a target), actual duration (measured), and maximum accepted duration (a release check) distinct.
Style and duration targets are soft with NotebookLM; exact wording, fixed voices, and seeded reproducibility
must not be advertised without a supported interface and a live proof.
