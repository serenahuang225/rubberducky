# Factory / Daytona learner wiring and visible validation

## Goal and current status

Finish the **existing** approved learner-facing runtime explanation path:
release → parse → reachable native/shared-web manipulative → truthful feedback/source labels.
Feature `factory-daytona-learner-wiring-and-visible-validation` owns final
**VAL-INTEGRATION-001/002**, both pending.
Read the [index](../README.md), [frontend](../../../frontend/README.md),
[backend](../../../backend/README.md) and [working-tree](../working-tree/README.md) guides.

Adapters, trusted checks and isolated components are implemented; production reachability
and visible validation are not. Current source references to `ExplanationManipulative`/
`parseReleasedExplanation` are definitions/tests only. This documentation request does not
authorize wiring source or resuming the USER-PAUSED browser.

## Already implemented / do not rebuild

- `348eca4`: actual droid-sdk/installed CLI adapter, actual Daytona SDK transport boundary,
  bounded ExplanationSpec/ReleasedExplanation, trusted repository-owned invariant suite,
  labeled pre-vetted fallback, CLI, native grouping/distribution controls and fixtures.
  The earlier synthetic canary/26-file staged handoff was already resolved/committed.
- `1a9ade2`: Factory streamed reported-usage monitoring/interrupt, missing usage fail-closed;
  Daytona cleanup failures prevent generated release. No unresolved hardcap implementation
  or synthetic-canary retry remains.
- `2c63001`: combined cancellation + failed exact-ID deletion logs sanitized run label,
  created/deleted/remaining exact IDs and `cleanup_failed` before cancellation propagates.
  No raw SDK exception/secrets, no decoy deletion, no promise of remote deletion.
- Native component already supports genuine integer manipulation; never replace with generated
  HTML/JS/WebView/code execution or a static screenshot.
- Completed adapter/isolated-component evidence contributes to the assertions; it is not the
  missing reachable learner flow.

## Relevant code and interfaces

| Path | Existing contract |
| --- | --- |
| [schemas](../../../backend/app/schemas/interactives.py) | Versioned bounded ExplanationRequest/Spec and ReleasedExplanation |
| [pipeline](../../../backend/app/interactives/pipeline.py) | Validated candidate + trusted sandbox report gate; failure returns labeled fallback |
| [Factory runtime](../../../backend/app/interactives/factory_runtime.py) | Constrained Session/subprocess, bounded prompt/output/deadline, scrubbed env, usage watchdog |
| [Daytona checks](../../../backend/app/interactives/daytona_checks.py) | Private ephemeral SDK sandbox, repository trusted code, exact-ID cleanup/failure reporting |
| [trusted suite](../../../backend/app/interactives/trusted_checks.py), [fallback](../../../backend/app/interactives/fallback.py) | Independent local/sandbox invariant checks; generated self-check notes never approve |
| [CLI](../../../backend/app/interactives/cli.py), [status](../../../backend/app/interactives/status.py) | Existing release/status path, disabled/configured-unverified |
| [TS parser](../../../frontend/src/interactives/explanationSpec.ts) | Closed bounded spec; release source/fallback reason and created/deleted consistency |
| [component](../../../frontend/src/interactives/ExplanationManipulative.tsx) | `ExplanationManipulative({released, theme})`, native grouping/distribution UI |
| [component tests](../../../frontend/src/interactives/ExplanationManipulative.test.tsx), [fixtures](../../../frontend/src/interactives/fixtures/) | Real backend-release-shaped payloads from fixture transports, not live generated results |
| [workspace](../../../frontend/src/screens/WorkspaceScreen.tsx), [client](../../../frontend/src/api/client.ts) | Potential minimal integration seams; currently external dirty ownership |

Specs allow grouping/distribution, integer factor ranges1..12, bounded plain title/prompt/
caption and no code/URL/markup/unknown component. `parseReleasedExplanation(unknown)`
returns `{ok:true,value}` or safe `{ok:false,error}`.
`source` is `generated_verified` or `prevetted_fallback`; fallback names its reason.
Generated release requires every created sandbox ID in deleted IDs. “Verified” here is a
trusted release-check result, **not** live-provider, educational or guaranteed-cleanup status.

Factory Runtime merges subprocess environment: current adapter blanks non-allowlisted app
secrets and uses an empty temporary workdir, constrained tools/permissions/autonomy. Preserve
that isolation and do not send the app database. Reported credits are monitored and interrupt
once over limit; missing usage refuses release. **This is not a hard spend cap**:
installed SDK/CLI has no cap option and spend may occur between/before usage updates.
Later activation needs explicit approval aware of that limitation; do not invent a budget flag.

Daytona create ambiguity can be looked up by the unique run label then deleted by exact owned
ID. Network restrictions/account-tier support must not be overclaimed. Deletion is attempted
with explicit failure, not guaranteed. Cleanup failure remains a fallback/error, never success.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] Confirm implementation assignment and UI-owner agreement for any shared dirty files.
   Do not adopt Workspace/API/tutor edits by broad staging or rewrite.
2. [ ] Select the **minimal compatible application-facing path** that supplies a released
   explanation to a navigable learner control. Existing architecture choices are flexible:
   no mandatory new route, scene-object kind, job system or UI rewrite.
3. [ ] Parse the actual released payload with the existing parser before mounting the native
   component. Preserve current work, scene history, keyboard/typed route, wait/help and media
   cancellation. Handle malformed/unavailable payloads without losing the board.
4. [ ] Show source/fallback/disabled/unverified labels and useful bounded mathematical changes
   when the learner operates grouping/distribution controls. Never label fallback generated.
5. [ ] Keep trusted gate/disabled defaults intact. No direct generated candidate bypass, no
   generated self-tests approving themselves, no silent live call during ordinary tutoring.
6. [ ] Add focused API/state/component integration tests for actual reachable path, safe parse
   failure and truthful disabled/fallback behavior, reusing existing adapter suites.
7. [ ] Only after **explicit browser resumption**, owner-coordinated3101 and approved3102 DB:
   actual visible navigation → manipulate values → before/after math/diagram → source/fallback
   labels, error/disabled behavior and preserved student work. Record screenshots/commands.
8. [ ] Run applicable fresh frontend/backend checks and report final001/002 evidence to normal
   validation. Do not mark passed from CLI/tests alone.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

- **VAL-INTEGRATION-001:** actual production Droid SDK/CLI fixture invocation, bounded
  misconception/context/spec, constrained tools/workdir/deadline/output/cost behavior; reject
  unknown/code/oversize/timeout/cancel; genuinely interactive native grouping/distribution;
  trusted validation or labeled fallback. Repository development with Factory is not runtime
  integration. Required learner before/after interaction is still missing.
- **VAL-INTEGRATION-002:** real Daytona SDK transport fixtures cover pass, invariant failure,
  malformed report, creation failure, timeout, cancellation and exact created/deleted IDs;
  only trusted passing candidates release, unavailable uses fallback. Preserve completed
  explicit cleanup failure semantics; do not promise successful remote deletion on failure.

Existing release/SDK tests can be reused when unaffected. No new audit registry, attestation,
certificate, completion seal, guaranteed-spend/delete mechanism or scene architecture is required.
Live Factory/Daytona remains unverified and deferred.

## Verification commands and evidence

Not run here. After assignment, future commands from root (safe clean settings/isolated DB
wrapper in backend guide for CLI; **never use `--confirm-live`**):

```sh
cd /Users/huangrh/workspace/rubberducky
PYTHONPATH=backend backend/.venv/bin/python -m app.cli interactives --help
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 backend/.venv/bin/python -m pytest backend/tests/test_factory_runtime.py backend/tests/test_daytona_checks.py backend/tests/test_interactive_release.py -q
npm --prefix frontend test -- --runInBand src/interactives/ExplanationManipulative.test.tsx
npm --prefix frontend run typecheck
npm --prefix frontend run lint
```

Actual CLI options:

| Command | Options |
| --- | --- |
| `interactives status` | no network |
| `interactives prevetted` | `--component grouping|distribution` (default distribution) |
| `interactives validate` | `--spec-file <raw ExplanationSpec JSON>`; not the entire released wrapper |
| `interactives generate` | required `--concept concept.distribution|concept.grouping`, `--misconception`; optional `--context`, `--component`, `--confirm-live` |

Disabled `generate` returns labeled fallback; configured transport without confirmation
returns refusal/exit2. The confirmation flag is an execution capability, not permission.
No commands were run for docs. Historical repair: frontend461 pass, standalone tsc2 on
then-external WaitControls; do not assume present failure or hide it behind wrapper0.

Retain redacted SDK/spec/release outputs and exact command exits; add actual authorized
learner navigation and before/after captures. Source references and isolated fixtures alone
are not that visible evidence. Native/shared-web code is not physical iPad proof.

## Ownership, dependencies, parallelism and stop conditions

Independent inspection/isolated component test planning can occur without touching dirty UI.
Production wiring requires agreement with current workspace/API/state/tutor owners; serialize
with media validation and current chat/question work. No browser/server action while paused.
If ownership cannot be resolved, return exact conflicting files and proposed minimal seam.
If3101 is occupied, request owner coordination/new explicit approval, not3103 or port killing.
If a test would activate a service or spend credits, stop.

## Not authorized / deferred

No live Factory run, Daytona sandbox, paid inference, deployment, new ingress, secret reading,
browser/pane/services or code changes from this documentation request. No hard-spend-cap claim,
guaranteed remote cleanup claim, external UI adoption, training or extra assurance subsystem.
No new feature scope beyond existing001/002.

## Copyable assignment prompt

> Complete `factory-daytona-learner-wiring-and-visible-validation` only after I authorize
> implementation and shared UI ownership is resolved. Read this README/index/module/
> working-tree guides. Preserve348eca4/1a9ade2/2c63001; reuse existing released-spec parser
> and native manipulative through the smallest compatible reachable learner path.
> No mandated new scene kind/route, no generated code execution, no gate bypass or false
> fallback/generated/live label. Browser work remains paused unless explicitly resumed;
> no service/live/spend/secrets. Cover pending VAL-INTEGRATION-001/002 with retained adapter
> evidence plus authorized actual learner manipulation. Return blockers before conflicts.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Identify the real reachable control/data path, parser/release gate, mathematical before/after,
source/fallback labels, fresh compiler status, browser pause/resumption and all unverified live
behavior. Never report001/002 complete from an isolated component alone.
