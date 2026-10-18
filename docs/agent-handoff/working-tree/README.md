# Working-tree safety and interrupted-worker recovery

## Goal and current status

Let multiple agents finish independent assignments **without losing, adopting, staging or
committing user/other-agent work**. This is coordination documentation, not permission to
start implementation, resume the mission, run services/tests, stage or commit.
Read the [handoff index](../README.md) and root [AGENTS.md](../../../AGENTS.md).

Initial read-only documentation snapshot:

- Repository `/Users/huangrh/workspace/rubberducky`, branch `master`.
- HEAD `904d9657f9546d56cb68066599a2cdb88aa6890f`.
- `git diff --cached --name-only` later in this docs session returned no paths: index empty
  at that observation. Recheck before any later staging; never assume persistent ownership.
- Source was changing independently during documentation. The list below is a **snapshot**,
  not a claim those files will remain dirty or belong to the interrupted Photon worker.

Initial `git status --short` before new handoff docs (paths only, no source/secret contents):

```text
 M .env.example
 M README.md
 M backend/app/config.py
 M backend/app/inference/claude.py
 M backend/app/multimodal/service.py
 M backend/app/pedagogy/messages.py
 M backend/app/tutor/brought_question.py
 M backend/tests/test_remote_adapters.py
 M backend/tests/test_tutor_policy.py
 M frontend/src/api/client.ts
 M frontend/src/screens/WorkspaceScreen.tsx
?? .DS_Store
?? .agents/
?? .chalkignore
?? .helix/
?? .vscode/
?? .zed/
?? AGENTS.md
?? chalk.yaml
?? frontend/src/components/TutorChat.test.tsx
?? frontend/src/components/TutorChat.tsx
?? frontend/src/components/tutorChat.ts
?? logo.jpg
?? pyproject.toml
?? uv.lock
```

During the docs session a later status no longer listed dirty
`backend/app/pedagogy/messages.py`/`backend/tests/test_tutor_policy.py`, and the untracked chat
helper appeared as `frontend/src/components/chatMessages.ts` instead of `tutorChat.ts`.
These are observed concurrent changes, **not changes made by this documentation task**.
Confirm the latest owner/files before acting; do not try to restore this historical list.
New `backend/README.md`, `frontend/README.md`, `docs/agent-handoff/` and root README append
are the documentation writer's only authorized edits.

## Already implemented / do not rebuild

Factory's26-file partial index/canary story is historical: initial code committed `348eca4`,
repairs `1a9ade2`, cleanup diagnostics `2c63001`. No pending staged canary fix remains.
Chalk committed `b76811e`; current HEAD also includes UI commit `904d965`.
Do not re-stage those old handoff files, retry Shield unchanged, bypass hooks or reconstruct
historic red/green evidence.

Learning-loop is closed; completed agency/provider/client foundations are not abandoned
because formal assertions remain pending. Media worker recovery found screenshots/runtime
helpers, **not source edits**; existing dirty UI remains external/user ownership.

## Relevant code and interfaces

| Paths / area | Ownership rule / likely coordination |
| --- | --- |
| Root `README.md` | Existing external text preserved entirely; docs handoff additive section only |
| `.env.example`, backend config/Claude/tutor/media/tests | External/user dirty work; changes not attributable to Photon; coordinate owner before overlapping edit |
| Frontend API/workspace/TutorChat/helper/tests | Active external UI work; media/wiring must not overwrite/stage it |
| Root AGENTS/Chalk pyproject/uv/chalk config/editor dirs/logo | User scaffold, many untracked; do not adopt/stage |
| `.DS_Store` | Unrelated untracked file; leave alone, not a cleanup assignment |
| Root `.venv` | User Chalk environment; do not modify/install/copy |
| `backend/.venv`, `frontend/node_modules` | Existing local dependency environments; not source handoff or worktree-copy material |
| `data/`, mission runtime DBs, local credentials/media/artifacts | Do not read private stores or copy into branches/reports; use explicit approved isolated DB |
| Future Photon/voice modules | Only assigned owner; serialize shared config/CLI/routes/migrations/locks/gates |
| External experiment worktree | Other agent owns implementation; receive intended commits/results, never edit/copy its dirty tree |

### Photon partial-worker recovery

Exact transcript:
`/Users/huangrh/.factory/sessions/-Users-huangrh-workspace-rubberducky/b87a9b2c-734f-433e-aec1-5e4b18a6f262.jsonl`.
28 records; tool calls read mission/library/source/SDK scratch; last source reads at
2026-10-18T01:08:10.598Z, then user cancellation/interruption at01:08:18Z.
No source writes, install, tests, stage/commit or handoff call. No worker-owned partial source
or leftover service is established. `features.json` still `in_progress` is a stale execution
label, not a reason to signal a process or call StartMissionRun. Do not replay its commands.
The [Photon assignment](../photon-messaging/README.md) carries remaining implementation scope.

Media worker61bd67fe left partial evidence with API-target uncertainty; its owned services
were absent after runtime cleanup. New unowned3101 listeners are not its resources. See
[media](../media-validation/README.md), not old PID-based permission.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] At any future assignment, capture fresh `git status --short --branch`, HEAD,
   staged path list and changed-path ownership without dumping environment/source secrets.
2. [ ] Get explicit owner agreement for overlapping files/hunks. Dirty does not mean abandoned;
   untracked does not mean agent-generated. Do not infer ownership from filename/topic alone.
3. [ ] Agree on base commit and separate branch/worktree location per implementation agent.
   Example **only after authorization**, with a chosen unused location/branch:
   `git -C /Users/huangrh/workspace/rubberducky worktree add -b agent/photon /tmp/rubberducky-photon 904d9657f9546d56cb68066599a2cdb88aa6890f`.
   This does not include current dirty changes: ask owner for intended committed prerequisites.
4. [ ] Do not copy `node_modules`, `.venv`, dotenv, databases, raw media or whole dirty working
   trees. Use approved isolated environments/locks and discuss dependency reuse/resource
   constraints. Routine local setup/tests/research can fit a bounded implementation assignment;
   installs beyond agreed scope and restricted downloads are not implicitly authorized.
5. [ ] Allocate disjoint modules/tests; serialize shared CLI/config/route inventory/schema/
   migrations/locks/gate edits. Coordinate minimal interfaces before implementation.
6. [ ] Receiver reviews delivered commit diff/status; integrate only intended work with
   provenance after permission. Missing/conflicting delivery goes back to owner, not a reset,
   stash or wholesale cherry-pick over dirty files.
7. [ ] Before any separately authorized commit, review staged diff and status for unrelated
   hunks/data/secrets. Stage only owned explicit paths/hunks; shared config needs hunk precision.
   Use configured identity and normal hooks/Shield. No `git add .`, `git add -A`, identity
   override, hook bypass, auto-merge/push or history rewrite.
8. [ ] Report own file/commit/evidence ownership, inherited failures and next owner. Preserve
   uncommitted user changes and leave docs uncommitted for this request.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

No standalone new VAL assertion belongs to coordination. It supports existing delivery/
reproducibility **VAL-DOCS-001/002**, without adding audit certificates or proof requirements.
Required outcome: only authorized docs change now; future agents preserve unrelated source/
index/user files and return real blockers. Branch/worktree isolation is workflow guidance,
not a new product feature or acceptance system.

Root README baseline before docs: **29742 bytes**,
SHA256 `07e8c18605554124ae6cf29079b1b4e7f7caeebee70fbe35619f63003c3edeec`.
Documentation writer must verify those original bytes remain an exact prefix after additive
entry-point append. Do not stage this user's existing README changes with a docs request.

## Verification commands and evidence

Read-only future status checks from any directory:

```sh
git -C /Users/huangrh/workspace/rubberducky status --short --branch
git -C /Users/huangrh/workspace/rubberducky rev-parse HEAD
git -C /Users/huangrh/workspace/rubberducky diff --cached --name-only
git -C /Users/huangrh/workspace/rubberducky diff --stat
```

Do not print source hunks likely to contain real keys; `.env`/`.env.local` and environment
dumping are out of bounds. The docs writer performs lightweight local markdown/path and
README-prefix checks only, no package validators/browser/services/training/live network.
Status movement caused by others must be reported as such, not silently “repaired.”

## Ownership, dependencies, parallelism and stop conditions

User/orchestrator owns scope and cross-agent coordination; each agent owns only assigned
contributions. Two agents cannot safely stage different hunks of a shared index without
serialization; use separate worktrees, reviewed commits and explicit integration permission.
Separate worktree does not grant service/port/secret/spend authority.

Stop on unknown owner, unexpected staged changes, missing configured Git identity, Shield/
hook failure, insufficient disk/dependencies, branch/base conflict or edits needed outside
assignment. Return exact paths/action needed. Do not broaden scope to clean editor/scaffold/
cache files or fix unrelated compiler/style failures.

## Not authorized / deferred

No resets, stash/revert, checkout over dirty paths, destructive deletion, personal-data
inspection, `.env` reads, resource signaling, service adoption, mission-state edits, runner
resume, source implementation, staging or commits from the docs request. Never copy a stale
instruction's stop permission to a new PID; user3100/3101/8081 remain protected and3103 unapproved.

## Copyable assignment prompt

> Before touching code, read this working-tree README and handoff index, then capture current
> status/HEAD/staged paths. Preserve all external dirty/scaffold/environment/data files.
> Confirm ownership/base and use a separate coordinated branch/worktree without copying
> dependency trees, dotenv or databases. No reset/stash/revert/broad staging/hook bypass.
> Interrupted Photon worker only read files; do not adopt unrelated chat/question work or
> resume a runner. Serialize shared CLI/config/routes/migrations/locks/gates; stop on
> ownership or approval gaps. This docs request authorizes no source change, staging or commit.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include baseline/current HEAD, owned versus inherited dirty paths, index status, interrupted
worker disposition, observed concurrent changes and explicit approval/owner needed next.
