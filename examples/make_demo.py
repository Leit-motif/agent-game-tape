#!/usr/bin/env python3
"""Create two entirely fictional evidence/review pairs; no account or network access."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from game_tape import fingerprint, save


def event(id, role, minute, text):
    return {'id': id, 'session': id.split('-')[0], 'harness': 'synthetic', 'source': 'fictional.jsonl',
            'line': minute, 'timestamp': f'2030-04-10T09:{minute:02}:00+00:00',
            'role': role, 'text': text, 'truncated': False, 'in_window': True}


def cases():
    rules = json.loads((ROOT / 'references' / 'rules.json').read_text())
    a_events = [
        event('a-1', 'human', 0, 'Before changing the rest, show that the new filter preserves the failing example.'),
        event('a-2', 'assistant', 2, 'I will run the small regression first rather than rewrite the pipeline.'),
        event('a-3', 'tool', 4, 'Regression: original failing example preserved. Existing cases: 12 passed. No rewrite performed.'),
        event('a-4', 'human', 10, 'Yes, publish the page once the preview check passes.'),
        event('a-5', 'assistant', 12, 'Published. I checked that the page loads, but I did not run the requested motion preview.'),
        event('a-6', 'tool', 18, 'Preview check: motion missing. Rollback finished at 09:18. Visitor logs: unavailable.')]
    a_review = {'status': 'reviewed', 'moments': [
        {'title': 'A small check kept the rewrite off the table', 'workstream': 'filter', 'human_event': 'a-1',
         'human_quote': 'Before changing the rest, show that the new filter preserves the failing example.',
         'action': 'The assistant ran the small regression rather than expanding into a pipeline rewrite. The result preserved the originally failing example and reported twelve existing cases passing.',
         'outcome': 'The record confirms the targeted check and that no rewrite was performed. It does not measure how long a rewrite would have taken, so there is no measured time saving to claim.',
         'lesson': 'The repeatable move is to make one concrete example the first checkpoint, then widen the work only if that check establishes a need.',
         'rule_id': 'R2', 'verdict': 'good call', 'responsibility': 'human',
         'causal_basis': 'The instruction asked for the regression first, and the next assistant action followed that sequence.',
         'assurance': 'verified', 'evidence': [{'event': 'a-3', 'quote': 'Regression: original failing example preserved. Existing cases: 12 passed. No rewrite performed.'}]},
        {'title': 'Publication crossed an explicit condition', 'workstream': 'page', 'human_event': 'a-4',
         'human_quote': 'Yes, publish the page once the preview check passes.',
         'action': 'The assistant published after checking only that the page loaded. Its own message admits that it skipped the requested motion preview. A later preview found missing motion and recorded a completed rollback at 09:18.',
         'outcome': 'Eight minutes elapsed between the conditional approval and the rollback record. That is an elapsed interval, not measured labor or a proven public outage. Visitor logs are unavailable, so visitor exposure remains unknown.',
         'lesson': 'You had already supplied the condition. The process change is for the assistant to make that condition a blocking release check, rather than require you to repeat it more forcefully.',
         'rule_id': 'R3', 'verdict': 'agent failure', 'responsibility': 'agent',
         'causal_basis': 'The condition was explicit; the assistant reported skipping it. The record does not explain why it skipped the check.',
         'assurance': 'verified', 'evidence': [{'event': 'a-5', 'quote': 'I did not run the requested motion preview.'}, {'event': 'a-6', 'quote': 'Preview check: motion missing. Rollback finished at 09:18. Visitor logs: unavailable.'}]}],
        'blind_spots': ['This fictional record contains no visitor logs or measurement of human labor.'],
        'experiment': {'change': 'For the next release, have the assistant record a passing preview check before publication can proceed.', 'next_check': 'In the next release record, look for the preview result before the publication event; if it is absent, keep the release blocked.', 'moment_numbers': [2]}}
    b_events = [
        event('b-1', 'human', 0, 'Skip the cache experiment for now. First check the slower request from the phone.'),
        event('b-2', 'assistant', 3, 'The phone request measured 4.2 seconds end to end. The old local handler measurement was 0.3 seconds and excluded network travel.'),
        event('b-3', 'tool', 5, 'Phone end-to-end: 4.2s. Local-handler-only: 0.3s. No component-level network trace captured.'),
        event('b-4', 'human', 12, 'Ship only after the end-to-end phone check is in the release record.'),
        event('b-5', 'assistant', 15, 'The patch is committed and I restarted the service. I have not checked the phone after the restart.'),
        event('b-6', 'tool', 16, 'Commit recorded: demo123. Post-restart phone check: not recorded.')]
    b_review = {'status': 'reviewed', 'moments': [
        {'title': 'Changing the measurement before changing the system', 'workstream': 'latency', 'human_event': 'b-1',
         'human_quote': 'Skip the cache experiment for now. First check the slower request from the phone.',
         'action': 'The assistant followed your newer instruction to measure the phone request instead of pursuing the cache experiment. The tool result records 4.2 seconds end to end on the phone and 0.3 seconds for the local handler alone.',
         'outcome': 'These are different measurement boundaries. The record contains no component-level network trace, so it cannot establish which component accounts for the difference or how much a cache would improve it.',
         'lesson': 'The useful move was to resolve the measurement mismatch before optimizing a component. Judge subsequent work against your updated instruction, not the superseded cache idea.',
         'rule_id': 'R4', 'verdict': 'good call', 'responsibility': 'human',
         'causal_basis': 'The recorded action follows the explicit newer instruction. No speed improvement was demonstrated.',
         'assurance': 'verified', 'evidence': [{'event': 'b-3', 'quote': 'Phone end-to-end: 4.2s. Local-handler-only: 0.3s. No component-level network trace captured.'}]},
        {'title': 'A commit does not certify the running experience', 'workstream': 'release', 'human_event': 'b-4',
         'human_quote': 'Ship only after the end-to-end phone check is in the release record.',
         'action': 'The assistant reported a commit and a service restart, while explicitly saying that it had not checked the phone afterward. The tool result confirms a recorded commit and a missing post-restart phone check.',
         'outcome': 'The commit is recorded. The restart remains an assistant report, and the phone experience after it is unverified. Neither successful deployment nor failed deployment follows from this evidence.',
         'lesson': 'Keep artifact evidence and live-experience evidence separate. Your release condition is still outstanding; a missing check does not tell you whether the patch works.',
         'rule_id': 'R6', 'verdict': 'unclear', 'responsibility': 'unknown',
         'causal_basis': 'The running outcome and the cause of the missing check are not established in the record.',
         'assurance': 'unknown', 'evidence': [{'event': 'b-5', 'quote': 'I have not checked the phone after the restart.'}, {'event': 'b-6', 'quote': 'Commit recorded: demo123. Post-restart phone check: not recorded.'}]}],
        'blind_spots': ['The fictional record lacks a post-restart phone test and a component-level network trace.'],
        'experiment': {'change': 'In the next patch review, keep the commit receipt and the post-restart phone result as two separate acceptance checks.', 'next_check': 'Verify that both receipts are present before marking the running experience accepted; preserve unknown status when either receipt is absent.', 'moment_numbers': [2]}}
    for name, events, review in [('case-a', a_events, a_review), ('case-b', b_events, b_review)]:
        yield name, {'schema': 'agent-game-tape/evidence-v1', 'window': ['2030-04-10T00:00:00+00:00', '2030-04-11T00:00:00+00:00'], 'timezone': 'UTC', 'rules': rules, 'rules_sha256': fingerprint(rules), 'previous_review': None, 'coverage': [{'harness': 'synthetic', 'available': True, 'files': 1, 'events': len(events)}], 'events': events}, review


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    for name, bundle, review in cases():
        folder = Path(a.out) / name
        if folder.exists():
            raise SystemExit(f'refusing to overwrite {folder}')
        save(folder / 'evidence.json', bundle)
        save(folder / 'review.json', review)
        print(folder)


if __name__ == '__main__':
    main()
