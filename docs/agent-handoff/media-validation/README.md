# Optional media validation and integrated recovery

## Goal and current status

Complete the remaining **visible shared-client** optional-media/recovery journey, preserving
implemented code and accepted evidence. Feature `optional-media-controls-and-private-event-flow`
owns **VAL-MEDIA-001/002/003, VAL-REL-004, VAL-CROSS-002, VAL-BOARD-010,
VAL-PERSONA-006/007**. All eight remain formally pending.
Read the [index](../README.md), [frontend](../../../frontend/README.md),
[backend](../../../backend/README.md) and [working-tree rules](../working-tree/README.md).

**BLOCKED: USER-PAUSED BROWSER TESTING.** Do not invoke a browser, interact with the pane,
start test services, stop listeners, retry the failed worker/model request, or implement fixes
for this docs task. Browser pause retains acceptance scope; it is neither a pass nor cancellation.

## Already implemented / do not rebuild

- Media code is committed at `9b3eba0`, `bb9def1`, `076b548`: explicit optional capture controls,
  lazy platform drivers, bounded uncertain events/candidates, transcript finality, scope/epoch/
  generation cancellation, speech/captions, fixtures and shared redacted `error.v1` including422.
- Backend turn/source cancellation, outbox retries and progressive-reveal/accessibility
  implementation already exist. Turn-races' actual visible interrupt-and-continue,
  lost-ack/typed retry and fresh-problem/support-fading checks completed at `fa8eceb`/`d7481ff`.
  Agency client keyboard/radio, persona lock/re-entry, memory/session/profile removal,
  questionable-reasoning wording and mid-reveal cover flows completed in `artifacts/lac2-*`.
  Do not reopen entire campaigns; formal milestone validation still applies.
- **Accepted partial media evidence:** `artifacts/media-01..05` shows default/no unsolicited
  media calls/capture, capabilities unavailable honesty, explicit mic start and stop with typed
  input still available. It does not finish the eight assertions.
- Historical media853 backend/409 frontend and type/lint/build/Expo summaries are not fresh
  gates on current externally changed UI.

## Relevant code and interfaces

| Path | Responsibility |
| --- | --- |
| [useMedia](../../../frontend/src/media/useMedia.ts), [voiceSession](../../../frontend/src/media/voiceSession.ts) | Session/generation/epoch/attempt-scoped candidate/speech lifecycle |
| [capture controller](../../../frontend/src/media/captureController.ts), [speech controller](../../../frontend/src/media/speechController.ts) | Action permission/release, stop and late callback rejection |
| [default services](../../../frontend/src/media/defaultMediaServices.tsx), [media services](../../../frontend/src/media/mediaServices.ts) | Lazy native/web drivers; do not eagerly import SDKs |
| [panel](../../../frontend/src/components/MediaPanel.tsx), [workspace](../../../frontend/src/screens/WorkspaceScreen.tsx) | Learner controls, captions/candidate/submit/status; dirty external UI ownership |
| [fake media](../../../frontend/src/testing/fakeMedia.tsx), [screen media tests](../../../frontend/src/screens/WorkspaceScreenMedia.test.tsx) | Explicitly simulated deterministic fixtures |
| [workspace state](../../../frontend/src/state/useWorkspace.ts), [progressive reveal](../../../frontend/src/state/useProgressiveReveal.ts) | Logical retry IDs/current-turn fences; cancellation integration |
| [media API](../../../backend/app/api/media.py), [service](../../../backend/app/multimodal/service.py), [limits](../../../backend/app/multimodal/limits.py) | Scoped bounded events/capabilities, provisional/final/idempotent behavior |
| [redaction](../../../backend/app/redaction.py), [errors](../../../backend/app/api/errors.py) | Shared logs/error/422 sanitization, never echo submitted input |
| [media tests](../../../backend/tests/test_media_events.py), [redaction tests](../../../backend/tests/test_redaction.py), [race tests](../../../backend/tests/test_turn_races.py) | Existing actual backend behavior and SDK/error boundaries |

Media image limits:262144 bytes,2048px edge,3/minute,12/session; all events120/minute,
500/session; transcript500 chars. Events are revision/session scoped; foreign/stale/excess
are rejected, not truncated. Default raw media is neither stored nor logged. Candidate/final
transcript is not automatically assessed work: learner edits/confirms explicitly.
Opening-question screenshot/Claude intake is separately dirty work, not evidence of live
camera perception. Digital geometry remains authoritative.

### Recovered worker61bd67fe: reuse cautiously, not formal passes

At2026-10-17T23:07:47.154Z an Anthropic model request returned400 invalidRequest;
available error was only400 Bad Request. Root cause is unknown; no screenshot causation,
quota failure, or product defect is established. It ended without handoff.

Transcript/screenshots `artifacts/media2-00` through `media2-24` support these **partial,
simulated** observations: provisional/revised/final voice, ignored duplicate-final/late-interim,
candidate edited/copied as typed draft before explicit submit, simulated speech/captions,
a later successful Stop, new-problem cancellation, mute/text-only unchanged synthesis counters,
captions-off speech, memory navigation stopping speech, a confirmed help-record deletion
followed by a speaking current turn, uncertain photo edited/copied and weak-cue clarification.

But the worker's owned API3102 PID28659/web3101 PID28831 did not receive documented clean
script shutdown. Runtime cleanup SIGKILLed28659; both are absent in recovery records.
A new **unowned**3101 PID30467 appeared. Later screenshots' API-target provenance is unresolved.
Do not mark those results formal passes or assume they all used isolated3102.

Nonpassing/incomplete evidence:
- First Stop missed already-finished speech; later Stop succeeded.
- First draw-during-speech still showed speaking; a later registered stroke alone does not
  prove cancellation.
- A delay shim held **request sending**, not an already-reserved server turn. “Thinking”
  persisted and later speech occurred; that neither proves reserved-turn cancellation nor
  diagnoses a product bug. Use the existing real coordinator/reservation fixture pattern.
- Correction-specific cancellation, denial/missing-device fixtures, controlled full recovery
  journey and final console/a11y were unfinished.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] **Wait for explicit browser resumption** and shared UI ownership resolution. No readiness
   probe while paused. Confirm required3101 service ownership/new exact permission; both prior
   API17085 and web27683 one-time stop permissions are consumed.3103 is not approved.
2. [ ] Once resumed, use authoritative mission `services.yaml` `test_api` on
   `127.0.0.1:3102` with fixed
   `/Users/huangrh/.factory/missions/3062e91c-42f0-46d7-97f1-1b984bb59bfd/runtime/test-api-3102.db`.
   Settings/migrate/seed/serve must share clean mock/disabled env. Use derived
   `start-test-api.sh`/`stop-test-api.sh`, `start-web.sh`/`stop-web.sh`, not legacy extractor/
   api3100/harness/reset recipes. Web3101 explicitly targets3102; pairing/CLI use same DB.
3. [ ] Reconcile actual bundle/API/DB identity and owned services before accepting recovered
   media2 evidence. Reuse unaffected accepted media-01..05; rerun only ambiguous/affected
   gaps, not every historic test.
4. [ ] Use agent-browser skill and supplied **visible** Factory pane. Verify actual screenshot
   and input readiness with one ordinary retry. If hidden,0×0, rAF/screenshots/input blocked
   or target lost, stop immediately for user help. No continuing7-command batch, DOM-only
   hidden work, headless launch or protected-CDP discovery.
5. [ ] Demonstrate labeled simulated transcript sequence and uncertain photo: edit candidate,
   explicit confirm/copy-to-draft, then intentional submit through verification. Interim,
   duplicate final and late interim create no extra assessed work. Weak cues clarify; no
   emotion/identity/disability/fatigue inference becomes fact/mastery.
6. [ ] Verify **actual** mute/text-only sound suppression, captions on/off, preference persistence
   independent of persona lock and truthful avatar states/unavailable labels. Preserve essential
   readable instruction and zero disabled haptic calls/unsupported no-op evidence.
7. [ ] Finish integrated interruption: speech Stop plus student work, explicit interrupt,
   new problem, relevant source correction and deletion; no late speech/caption/drawing/
   memory restart, authoritative current scene preserved, following current turn succeeds.
   Pair backend/component late-callback tests with actual visible flow; reserve the delayed
   server turn before releasing its old result. No production fault/debug endpoint.
8. [ ] Controlled disconnect/lost response: preserve unsaved work, use real Retry (`save-retry`
   for scene saving; current source may change placement), reconcile authoritative revisions
   exactly once, finish typed feedback → meaningfully fresh transfer → end/return session.
   Show honest wait/reconnect/error/caption states, disabled live integrations throughout.
9. [ ] Fresh-document **labeled page-level** NotAllowedError/NotFoundError permission fixtures
   for denial/missing device; keep text/board useful, indicators off/resources released.
   Do not blindly repeat the historical mid-flow mutation. Fixture grant/denial is not actual
   iPad OS permission evidence. Background release has platform/component plus later device
   coverage.
10. [ ] Capture final console/a11y/contrast/focus for affected controls and ordinary bounded
    event/revision/source comparisons. Run applicable current-source focused/gate checks after
    assignment; preserve failures with their actual owner. Return before any required edit
    to external dirty source rather than silently fixing it.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

| ID | Required remaining/combined behavior |
| --- | --- |
| VAL-MEDIA-001 | Mic/student/work camera default off, action-only permission, orientation/indicators/stop/release in granted/denied/missing/background fixtures; honest transmission/unavailable fallback |
| VAL-MEDIA-002 | Finite size/count/rate/session/revision boundary rejection; digital geometry authoritative; uncertain edited/confirmed input only assessed after explicit work; weak cues clarify |
| VAL-MEDIA-003 | Interim/revised/final/duplicate/late/failure sequence stays scoped; one final effect; stop/interrupt prevents stale speech/tools/memory; usable captions/text/mute |
| VAL-BOARD-010 | All named work/interrupt/new-problem/source-change triggers invalidate affected output and late callbacks; no current scene/dependent-state mutation; next current turn succeeds |
| VAL-PERSONA-006 | Actual persisted motion/sound/haptics/text-only/caption preferences suppress disabled calls without losing content or touching persona timestamp |
| VAL-PERSONA-007 | Accessible seven states match lifecycle; mute/text-only/unavailable never fabricate listening/speaking/understanding; simulated labels |
| VAL-REL-004 | Shared canary redaction in provider/media/tutor/optional-integration failures and422; no credential/raw-payload leaks in logs/errors/storage/build; authorized bounded source context |
| VAL-CROSS-002 | One bounded denied/unavailable + disconnect/retry → feedback/transfer/return journey retains committed work/evidence once with truthful disabled/mock statuses |

Ordinary tests, source IDs and screenshots suffice. Do not build an artifact signing, audit,
historical replay or new proof subsystem. Live STT/perception/acoustic barge-in is deferred.
Physical acceptance belongs to final **VAL-IPAD-001**, not this browser leaf.

## Verification commands and evidence

Future after assignment; **not run for this handoff**:

```sh
cd /Users/huangrh/workspace/rubberducky
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 backend/.venv/bin/python -m pytest backend/tests/test_media_events.py backend/tests/test_redaction.py backend/tests/test_turn_races.py -q
npm --prefix frontend test -- --runInBand src/media src/screens/WorkspaceScreenMedia.test.tsx
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
npm --prefix frontend run typecheck
npm --prefix frontend run lint
```

Use [index gates](../README.md) for milestone validation, serial/two threads; no repeated
training/install. Build-canary scan must not print canary values/real secrets. Evidence report
must distinguish fresh actual exits, historical checks, accepted partial screenshots,
provenance-uncertain media2 captures, fixture speech and native/live gaps.

Secondary references: mission `library/media-recovery.md`, `library/user-testing.md`,
`library/test-api-setup.md`; worker transcript
`/Users/huangrh/.factory/sessions/-Users-huangrh-workspace-rubberducky/61bd67fe-818f-467d-b015-e2d9430e18b4.jsonl`.
Artifacts are under `/Users/huangrh/workspace/rubberducky/artifacts/`; read only relevant
authorized synthetic evidence, never raw learner media.

## Ownership, dependencies, parallelism and stop conditions

One visible browser validator only, serial API/CLI when sharing the DB. Coordinate with
interactive-wiring and current UI owner before changes/restarts; no concurrent heavy
training/simulator/native compilation. Own only remaining media evidence/necessary assigned
media fixes. Formal agency scrutiny/user testing remain the delivery/validator owner's job.

Stop on pause, hidden/lost pane, unowned occupied port, uncertain API target, credentials/
raw-data exposure, conflicting dirty file or repeated model/runtime failure. Return the exact
gap; do not diagnose unknown historical400s or retry-loop them.

## Not authorized / deferred

No browser/service/readiness commands now, live recognition/calls/messages, hidden bypass,
new ports, listener adoption/kill, secret files, production fault controls, wholesale code
rewrite, fabricated acceptance or commits from documentation. No weakening of the eight
claims and no physical/device result inferred from browser fixtures.

## Copyable assignment prompt

> This assignment is blocked until I explicitly resume browser testing and3101 ownership is
> resolved. Then finish only the retained media leaf's remaining gaps using this README,
> index/module/working-tree guides. Preserve9b3eba0/bb9def1/076b548 and accepted media-01..05.
> Reconcile media2 API provenance; use clean isolated3102/fixed DB and owned web3101, supplied
> visible pane, no user3100/8081 or unowned3101 changes. Complete candidate edit/confirm,
> actual mute/text-only/captions/status, reserved-turn/late-callback interruption with next
> current turn, correction/deletion, disconnect/retry→transfer→return, labeled fresh-document
> denial/missing fixtures, console/a11y. No live perception/acoustic/device claim, hidden bypass,
> new port or conflicting UI edits. Return promptly on readiness/ownership blockers.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include all eight ID mappings, actual API/DB/bundle provenance, simulated-vs-live labels,
trigger/late-callback/following-turn outcomes, accepted/recovered/new evidence distinctions,
owned service cleanup status and remaining physical/live/formal validation gaps.
