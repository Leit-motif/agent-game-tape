# Validation status

**Not ready for public release yet.** Unit tests and source cleanup do not establish NotebookLM behavior.
This document reports what was actually tested, including negative results.

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

## Transport gate: failed stock client; narrow guard verified offline

The planned four-output renderer trial suffered a separate integrity incident: one failed stock CLI audio
kickoff left four remote artifacts in a new notebook. The outer runner did not retry. All unexpected
artifact ids were recorded for preservation instead of choosing a favorable output. The trial was not relabeled a valid four-output pass.

Pinned-source inspection and mocked transport tests confirm that the inspected 0.15.1 and 0.15.6 upstream
audio paths can replay mutations after some HTTP/RPC/auth failures; CDP is not a safe blanket workaround.
That demonstrates a replay mechanism, not the exact historical response sequence. The bundled narrow
single-dispatch adapter passed independent review and 21 tests, including exact-upstream mocked failure
scenarios. The combined package suite passed all 97 tests with upstream compatibility cases enabled; the
read-only runtime fingerprint probe passed without loading authentication. These checks make no live
single-send or Google-side exactly-once guarantee. No new generation was used to test the guard.

## Next fixed check: pending

The [separately preregistered brief-preset check](brief-validation-protocol.md) tests the same fictional
prose packets with Brief format and compatible short single-speaker focus. This is a preset bundle,
not an isolated causal attribution to format. It permits only two new generations after the write guard
and existing quota are ready. Each must pass the frozen factual/editorial gates, score at least 8/10,
and last no more than 150 measured seconds.

No result from that preset is claimed yet. The earlier failed study and its stopping rule remain intact.
See [the original protocol](evaluation-protocol.md), [frozen facts](../examples/fact-sheet.md), and
[full-episode QA](audio-qa.md). A future pass will support an explicitly experimental release, not a
promise that arbitrary session material is narrated accurately or that every host was live-tested.
