# Full-episode QA

A Gemini Notebook (formerly NotebookLM) episode is generated from the narration, not read from it. Hosts
can drift: round a number up, invent a cause, or turn advice into a result. This page is how to check the
whole episode before calling it accurate.

"Generated" and "accepted" are separate. The publisher never accepts audio automatically. Keep its
metadata, the downloaded file, the full ASR transcript and a separate editorial receipt.

## Triage with code

1. Measure duration with `ffprobe`, not the requested length category.
2. Transcribe the complete file with an available local ASR tool, retaining segment timestamps if possible.
3. Run `game_tape.py audit-audio`. Its patterns flag obvious source recital, label read-outs, third-person
   framing and motive words. Its coverage flag is only a plausibility check of the last timestamp. It
   cannot prove every second was transcribed or that silence/music was interpreted correctly.
   Then run `game_tape.py check-narration` for a [claim-level receipt](narration-check.md) of every sentence.
4. Review the opening, middle, ending and everything between them. Preserve all outputs, including
   disappointing ones. Do not cherry-pick a polished regeneration and erase the failed artifact.

Example external tools (installed separately; these are not Python package dependencies):

```bash
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /private/run/audio.m4a
whisper /private/run/audio.m4a --model base --language en --output_format json --output_dir /private/run
```

## Semantic review

For each consequential spoken assertion, compare with the evidence behind `review.json`. Watch especially
for these strength changes:

- assistant report → established fact;
- absent evidence of cost → zero cost;
- no measurement → a measured cost, saving or benefit;
- unverified deployment → failed deployment;
- elapsed interval → wasted labor or continuous outage;
- overlapping workers → every second spent in parallel;
- commit receipt → proof a running service restarted;
- adjacent qualifications → an invented dependency;
- inadequate verification → a made-up explanation of model internals;
- agent execution failure → an unsupported indictment of the human's instruction.

Check quotation identity and numbers, later intent, uncertainty, decision coverage, repetition, natural
address, time allocated per moment, and whether the episode actually ends on the proposed experiment.
A generic motivational epilogue or a new philosophical question is not the requested closing drill.
Advice is a proposal; do not narrate its predicted benefit as a measured result.

Inspect disputed sound when ASR is uncertain. A second transcription can reduce a transcription ambiguity,
but it does not prove acoustic quality. State whether the review covered full narration text, actual sound,
or both. A transcript-only review must not claim a complete listening pass.

## Receipt and decision

Write a local `editorial-review.md` with:

- exact audio and transcript SHA-256 hashes, measured duration, and review scope;
- supported/unsupported consequential claims with timestamps and evidence ids;
- material failures, stylistic issues, and ASR uncertainty kept separate;
- actionability and whether the closing experiment is usable;
- `accepted`, `rejected`, or `unverified`, with the reason and the reviewer.

A material invented event, motive, metric, causal mechanism or actor attribution rejects the episode.
Stylistic preferences never reject an episode on their own; factual failures do. A clean regex scan or plausible transcript end
cannot certify accuracy. A short source packet and polite focus prompt reduce opportunities for drift;
they are not a substitute for this check.

Use [the fixed evaluation protocol](evaluation-protocol.md) when comparing variants. Keep the same facts,
selection, focus, source count, language and format while testing one renderer change. Report every case,
small-sample limitations and what was not checked. A passed local unit test is not evidence of how Gemini Notebook behaves.
