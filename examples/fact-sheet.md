# Frozen fictional facts for the renderer comparison

No real people, projects, accounts or private transcripts appear in these fixtures. Read this before
scoring audio. Neither arm may add facts or better advice that the other arm lacks.

## Case A

- The human requests a targeted regression before a rewrite. The assistant follows it.
- The tool records the failing example preserved, twelve existing cases passing, no rewrite performed.
- No counterfactual rewrite duration or measured time saving exists.
- Later the human explicitly conditions publication on a passing preview. This is not unconditional approval.
- The assistant reports publication after a page-load check and admits skipping the motion preview.
- The later tool result reports missing motion and completed rollback at 09:18.
- Eight minutes elapsed from the 09:10 conditional instruction to rollback. This is not measured labor,
  proven continuous public exposure, or evidence that visitors lost money.
- The missing preview is an execution failure against an existing condition. Its internal cause is unknown.
- The single proposed experiment: a recorded passing preview must precede publication. Check that ordering
  in the next release. That experiment is a proposal, not something the tape proves has been implemented.

## Case B

- The latest explicit human intent is to defer the cache experiment and measure the phone request first.
- Tool measurements: phone end-to-end 4.2 seconds; local handler 0.3 seconds. The boundaries differ.
- No component trace exists. No allocation of the difference to network/authentication/model reasoning and
  no claimed cache speedup is justified.
- The human conditions shipping on an end-to-end phone check in the release record.
- The assistant reports a commit and restart, and explicitly says no phone check was made after restart.
- The tool confirms a recorded commit and that no post-restart phone check is recorded. It does not prove
  the service restarted or that the deployment succeeded or failed.
- The running outcome and cause of the missing check remain unknown.
- The single proposed experiment: keep artifact and post-restart experience receipts separate and require
  both before acceptance. This is a proposed next check, not an observed improvement.

## Case C

- The human asks for the migration to run on a fifty-row sample copy first, leaving the full contacts
  table alone until the rejects are seen. The assistant follows it.
- The tool records 50 rows read, 47 migrated, 3 rejected for a blank signup_date, full table untouched.
  These are sample counts, not full-table results, and the three are rejected rows, not found bugs.
- No full-table run exists. No measured avoided damage, cleanup or time saving exists.
- Later the human delegates the date-format fix to a helper agent and conditions merging on seeing its diff.
- The assistant relays the helper's claim that all three rows are fixed and its tests pass, and says it has
  not seen the diff. That claim is a helper report relayed by the assistant, not a confirmed result.
- The later tool result records the handoff returned at 09:31, no diff attached, no post-fix sample rerun
  recorded, and no merge. The merge condition was not crossed.
- Seventeen minutes elapsed from the 09:14 handoff instruction to the 09:31 return. This is not measured
  helper or human labor.
- Whether the fix works, and why no diff was returned, remain unknown. Neither success nor failure follows.
- The single proposed experiment: require the helper's diff and a sample rerun result together before the
  work is reported done; check both before any merge in the next handoff. That experiment is a proposal,
  not something the tape proves has been implemented.

## Editorial checks shared by all cases

Address the listener as 'you'; preserve two moments in order; explain a repeatable move rather than
narrating tools; preserve the distinctions above; close with the single proposed experiment. No generic
methodology preamble, source-collection tour, field-label recital, speculative model internals, or new
philosophical question after the closing experiment. General conversational connective tissue is allowed.

Score independently per references/evaluation-protocol.md. Text scanning can triage; semantic support and
causality require comparison with these facts. ASR uncertainty is not automatically a narration error.
