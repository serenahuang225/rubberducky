# Photon messaging handoff

The bridge that continues a paired learner is Photon Beta (2.0), package `@photon-ai/api` at `https://api.photon.codes`, as documented at https://photon.codes/docs/beta. It does not use the Stable Spectrum packages named below. Those Stable notes remain the historical assignment record.

# Stable Photon messaging continuation

## Goal and current status

Implement the approved optional **Stable Spectrum cloud TypeScript bridge** so an explicitly
paired messaging channel can continue a short concept discussion through the same scoped
Python tutoring/history services as the app. Own **VAL-INTEGRATION-004**.
Read the [index](../README.md), [backend](../../../backend/README.md) and
[working-tree rules](../working-tree/README.md) first.

This handoff is documentation, not implementation authorization. The mission is paused.
Feature `photon-stable-messaging-continuation` says `in_progress`, but worker
`b87a9b2c-734f-433e-aec1-5e4b18a6f262` was intentionally interrupted at2026-10-18
01:08:18Z. Its28-record transcript ends with “Request cancelled/interrupted by user.”
It contains context/SDK/source reading only: no source write, install, test, staging,
commit or EndFeatureRun. There is no Photon handoff, bridge package, migration, route,
production settings or CLI in the inspected repository. Do not assume either completed
implementation or a live worker from the queue label. Existing dirty tutor/chat/question
changes are not attributable to this worker.

## Already implemented / do not rebuild

- FastAPI token-derived learner scope, one-time local pairing, sessions, bounded graph/memory
  retrieval, current-source permissions, policy/coordinator, verified work and revisions/
  idempotency/cancellation are real. Reuse these rather than create a second chatbot/history.
- Local admin pairing is not yet channel pairing. `pair --learner` issues a short-lived code;
  `POST /pairing/redeem` returns a scoped credential. A phone/address alone is not authorization.
- Readiness scratch (not shipped production dependencies) has exact
  `@spectrum-ts/core@12.11.0` and `@spectrum-ts/imessage@12.11.0`.
  Its import probe checked `Spectrum` and `imessage` exports with outbound blocked and
  no SDK instantiation. It did not send, receive, connect or prove delivery.
  `@spectrum-ts/imessage-local` was explicitly absent.
- Shared redaction and SDK-fixture patterns already exist. Do not rebuild an assurance system.

## Relevant code and interfaces

| Existing path | Use |
| --- | --- |
| [pairing](../../../backend/app/learner/pairing.py), [auth dependencies](../../../backend/app/api/deps.py) | LearnerScope, credential/code validation, ScopedRepo; no request-supplied learner switching |
| [pairing routes](../../../backend/app/api/pairing.py), [sessions](../../../backend/app/api/sessions.py) | Fictional bootstrap/redeem/revoke and own-session lifecycle |
| [coordinator](../../../backend/app/tutor/coordinator.py), [tutor routes](../../../backend/app/api/tutor.py) | Shared execute_turn, short reserve/infer/recheck/commit, actual revision/idempotency behavior |
| [tutor schemas](../../../backend/app/schemas/tutor.py) | CheckInRequest/WorkRequest/HelpRequest; input-mode and disclosure semantics |
| [context](../../../backend/app/inference/context.py), [graph context](../../../backend/app/graph/context.py) | Bounded own source-linked history, not lifetime transcripts |
| [repository](../../../backend/app/db/repositories.py), [memory updates](../../../backend/app/learner/memory_updates.py) | Scoped reads, validated memory effects |
| [config](../../../backend/app/config.py), [CLI](../../../backend/app/cli.py), [main](../../../backend/app/main.py) | Shared integration points; coordinate before editing |
| [scope tests](../../../backend/tests/test_scope_auth.py), [turn races](../../../backend/tests/test_turn_races.py) | Existing route inventory/isolation and exactly-once fixtures |

**Planned**, not current: a minimal separate `integrations/photon/` package with its own locked
TS dependencies/tests, normalized channel events, channel pairing/linkage and shared Python
service access. Exact module/route names are implementation choices. Do not claim that directory
or command exists until delivered.

Selected Stable configuration: `SPECTRUM_PROJECT_ID`, `SPECTRUM_PROJECT_SECRET`,
host `https://spectrum.photon.codes`. Use the actual installed Stable SDK imports/protocol.
Do not mix Beta `photonhq-api`/`photon_api`, bearer-token/`pho_prj` examples, or stale template
names with this contract. No local Mac Messages provider, database, Apple automation or
Full Disk Access. Ordinary read-only official SDK documentation research fits a subsequently
assigned implementation task; it does not need separate approval. Live SDK activation/outward
actions, spend and installs beyond the agreed scope still require approval. No official docs
were fetched for this documentation request.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] Obtain implementation assignment and confirm current tree/ownership. Reuse the worker's
   reading, but inspect exact current interfaces before editing; dirty files are changing
   independently. Agree on shared authorized service boundary with voice owner.
2. [ ] Create minimal separate TS package using Stable cloud SDK and a reproducible lock.
   Readiness packages are scratch only. Routine dependency setup and local checks may be part
   of the implementation assignment within agreed scope and standing boundaries; this docs
   request runs neither. Report unavailable dependencies when resolving them would exceed
   that scope or violate download/resource restrictions.
3. [ ] Define bounded normalized inbound/outbound events and local fixture transport.
   Validate IDs/text/channel identity and provider direction; reject malformed inputs safely.
4. [ ] Implement explicit one-time authorized channel pairing, replay/wrong-identity rejection
   and correct learner/session binding. Do not silently redeem arbitrary addresses into
   existing histories or return another learner's sources.
5. [ ] Route an authorized synthetic continuation through shared scoped Python tutoring/
   history with bounded earlier source IDs. Demonstrate a source-grounded instructional
   difference versus a matched cold learner, not only a name greeting or separate transcript.
   Preserve conservative evidence/assessment rules for text arriving from a channel.
6. [ ] Dedupe inbound IDs, block self echoes, preserve logical turn/retry identity and handle
   outbound failure/retry without duplicate tutor/evidence effects. Do not promise exactly-once
   provider billing/delivery.
7. [ ] Add disabled/configuration/status and opt-out/error behavior with no import/startup send.
   Keys/configuration alone never activate. Scrub errors and bound context/output/time.
8. [ ] Exercise real SDK transport/type contracts using fake delivery, plus Python service/
   scope integration. Extend existing package gate entrypoints to cover the new bridge,
   coordinating shared script/config edits.
9. [ ] Document a **supported** outward SDK connection or required future approved HTTPS
   ingress. A private Mac loopback route is not a live webhook. Do not silently provision
   either ingress or delivery; keep real inbound/outbound unverified.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

**VAL-INTEGRATION-004 remains pending.** Required fixture population:

| Fixture | Expected result |
| --- | --- |
| Authorized one-time pairing | Exact channel maps to the consenting learner; shared bounded tutor/history path |
| Replayed/wrong pairing | No reuse or learner-switching/history disclosure |
| Unpaired inbound | No protected continuation |
| Duplicate inbound | One logical turn/evidence effect |
| Self-echo | No loop or new learner turn |
| Malformed inbound | Bounded sanitized rejection, no partial effects |
| Outbound failure/retry | Honest failure/retry, no duplicated tutor work |

Bridge must typecheck against the Stable SDK, default disabled, and show zero real sends/
personal-DB access. Compilation/transport fixtures are not live delivery. No new production
dashboard, public service or proof infrastructure is required.

## Verification commands and evidence

**Not run here.** There is currently no valid `npm --prefix integrations/photon ...` command.
The implementing agent must record actual package scripts/path and add them to existing gates,
not copy an invented executable from this document.

After assignment, existing backend gates from repository root:

```sh
cd /Users/huangrh/workspace/rubberducky
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 backend/.venv/bin/python -m pytest backend/tests/test_scope_auth.py backend/tests/test_turn_races.py -q
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
```

Add focused new bridge/Python fixtures first; current tests alone cannot pass004.
Use migrated temporary SQLite; no browser/HTTP listener/live SDK connection is needed.
Capture exact TS commands/exits, redacted event/request shapes, pairing/dedup counts,
bounded source IDs and zero-outbound assertions. Historical scratch files:
`/private/tmp/rubberducky-readiness/photon-stable/package.json`,
`import-check.mjs`, and `photon-stable-import-results.json` in its parent readiness directory.
Read them if present; **do not rerun** the probe as part of this docs request.

## Ownership, dependencies, parallelism and stop conditions

Own only bridge/channel linkage and targeted tests after assignment. Serialize config/CLI,
route inventory, migration/model and gate-script changes with voice/modeling/delivery owners.
No UI changes are necessary for this assignment. Separate worktree/branch avoids accidental
staging but does not grant permission to copy dirty source or dependency trees.

Stop and report exact missing input if stable dependencies cannot be made available within
the assigned setup scope, SDK transport is uncertain, shared dirty service code needs another owner,
or real delivery requires ingress/credentials/recipient approval. Never resolve those gaps
with Beta/local Messages, public exposure or live “smoke sends.”

## Not authorized / deferred

No browser/pane/services, messages/calls, personal messages, external activation/spend,
line purchase, deployment, public ingress, secret-file access, environment dump, source
implementation or commit during the documentation task. Future <=$5 Photon cap is not
permission or evidence of entitlement. Voice and external modeling remain separate assignments.

## Copyable assignment prompt

> After confirming I authorize offline implementation, complete
> `photon-stable-messaging-continuation` in `/Users/huangrh/workspace/rubberducky`.
> Read this README, index, backend and working-tree guides. Interrupted workerb87a9b2c
> only explored; do not treat its queue label as a running worker or adopt external dirty
> question/chat code. Use Stable `@spectrum-ts/core` + `@spectrum-ts/imessage`, explicit
> one-time channel pairing and shared scoped bounded Python tutor/history. Cover the
> VAL-INTEGRATION-004 fixture matrix with outbound blocked. No Beta/local Messages,
> sends, ingress, services, browser, secrets, purchases or deployment. Coordinate shared
> files and stop on missing approval/dependency/ownership. Commit only if separately asked.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include Stable SDK versions, planned-vs-present package/scripts, pairing/scope/dedup outcomes,
source-grounded continuation evidence, real-send count0, and unverified ingress/delivery status.
