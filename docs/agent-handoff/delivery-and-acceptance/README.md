# Delivery guide, results and native acceptance

## Goal and current status

Finish the approved reproducible learning/build guide, truthful results/inventory, formal
validation and late-final **actual iPad** acceptance. Feature
`delivery-guide-results-and-native-acceptance` owns **VAL-DOCS-001/002 and VAL-IPAD-001**.
It also coordinates formal scrutiny/user testing of implemented-but-pending agency/provider/
Chalk behaviors; implementation completion is not assertion acceptance.
Read the [index](../README.md), [backend](../../../backend/README.md),
[frontend](../../../frontend/README.md) and [working-tree guide](../working-tree/README.md).

This requested handoff writes documentation only. The root README is externally dirty and
must keep its entire existing text, with additive handoff links only. These new module/task
READMEs do not themselves pass DOCS assertions: fresh executable checks, external results,
final research/model cards, formal validation and user device outcomes remain outstanding.
No tests/build/browser/training/live/device checks were run for this docs task.

## Already implemented / do not rebuild

- Closed learning-loop validated33/33. Preserve its scope/evidence. Agency implementation:
  adaptive policy/wait, memory correction/deletion, persona cooldown/preferences, providers,
  turn recovery, accessibility/progressive reveal and media controllers already exist.
- Media visible completion remains [paused](../media-validation/README.md); Factory learner
  reachability remains [pending](../interactive-wiring/README.md). Independent
  [Photon](../photon-messaging/README.md)/[voice](../livekit-voice/README.md) need implementation
  after explicit assignment. Do not treat “continue independent work” in older mission text
  as permission from a documentation request.
- Factory/Daytona `348eca4`, repairs `1a9ade2`/`2c63001`, Chalk evaluator `b76811e` are retained.
  No live verification, hard Factory spend cap or guaranteed sandbox deletion claim.
- [Modeling](../modeling-integration/README.md) is externally implemented. Receiver integrates/
  tests/reviews delivered work only; missing commits/results block, not invite duplicate
  GRU/dataset/LoRA development.
- Root/module setup, actual scripts and source interfaces are documented. No production
  account/compliance, public deployment, useful tuned model or learning gains are established.

## Relevant code and interfaces

Use this bottom-up reading order; all paths are current:

1. [schemas](../../../backend/app/schemas/), [ORM](../../../backend/app/db/models.py),
   [migrations](../../../backend/migrations/), [seed](../../../backend/app/db/seed.py):
   typed versions/UTC/provenance/missingness → persisted scoped records.
2. [graph](../../../backend/app/graph/), [tracing](../../../backend/app/tracing/):
   curriculum DAG separate from personal evidence; explicit BKT/eligibility/replay.
3. [verification](../../../backend/app/verification/), [policy](../../../backend/app/pedagogy/policy.py),
   [context](../../../backend/app/inference/context.py): bounded mathematics, uncertain diagnosis,
   source-linked retrieval rather than lifetime transcripts.
4. [coordinator](../../../backend/app/tutor/coordinator.py),
   [validation](../../../backend/app/tutor/validation.py),
   [evidence](../../../backend/app/tutor/evidence.py): reserve → infer → recheck → atomic commit.
5. [scene](../../../backend/app/whiteboard/scene.py),
   [App](../../../frontend/App.tsx),
   [workspace state](../../../frontend/src/state/useWorkspace.ts),
   [canvas](../../../frontend/src/components/WhiteboardCanvas.tsx): actual learner flow,
   author-safe durable scene/outbox and current-turn rendering.
6. [media](../../../frontend/src/media/), [backend media](../../../backend/app/multimodal/),
   [interactives](../../../backend/app/interactives/),
   [evaluation](../../../backend/app/tutoring_eval/): optional bounded paths with honest limits.
7. [tests](../../../backend/tests/), shared frontend tests and the pending assignment READMEs:
   evidence of executed behavior, not inferred educational efficacy.

### The three meanings of “model”

| Meaning | Here | Not a claim |
| --- | --- | --- |
| Data/schema model | Pydantic contracts and SQLAlchemy rows validate/store records | Not learned intelligence |
| Statistical learner model | BKT; externally delivered GRU predicts eligible next-response correctness | Not a permanent diagnosis or calibrated mastery; GRU probability is not BKT latent state |
| Language model | Mock is deterministic, Transformers/endpoint/Claude generate proposals; LoRA is a shared experimental adapter | Not an authority over verification/policy or a proven useful tuned tutor |

Explain BKT equations/handparameters/eligibility explicitly, frozen-base LoRA versus GRU,
and how provider drafts remain proposals. Do not conflate test counts with model metrics.

### Annotated end-to-end trace to complete with actual IDs

Use a fresh fictional learner, not private history. This is the trace format/expected dataflow,
not an invented execution transcript:

| Stage | What to explain / actual evidence to record |
| --- | --- |
| Raw input | Typed confirmed `2x + 3 = 14` on `2(x + 3)=14`; learner/own session/attempt, logical key and expected revision; never grade raw ink |
| Validated observation | Work/step source ID, provenance submitted, finite evidence kind/confidence/missingness; bounded verifier outcome distinct from pedagogical diagnosis |
| Retrieved sources | Own bounded graph/memory IDs, support/contradiction and omissions; no future/deleted/superseded current-evidence citations |
| Policy | Tentative first-term distribution difficulty/copying alternative; smallest diagnostic grouping hint, not complete answer |
| Proposed scene | Bounded tutor highlight/bracket/actions with role/author/turn/revision; validate full draft before release |
| Feedback | Concise source-grounded public utterance, expected learner action, honest hint/disclosure and assistance state; no hidden reasoning |
| Committed evidence | Accepted turn/status/revision/epoch, scene operation IDs, eligible assessment versus assisted practice, notes' sources/version; BKT update only if independently eligible |
| Return/repair | Restart/new-session retrieval changes instruction; corrected/deleted sources recompute/invalidate dependent state and late turn; distinguish lineage from active citation |

Record actual IDs from CLI/API, not guessed UUIDs. Include one central design decision per
layer and a command/interaction that demonstrates it.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] Confirm delivery assignment/permissions, current HEAD and dirty ownership. Retain root
   README manual setup verbatim for this additive handoff; later broad docs edits need owner
   agreement. The11-path limit applies only to this handoff-writing task. The future delivery
   assignment may create/update ordinary in-scope architecture/research/build guides and
   model cards as part of the already approved deliverable.
2. [ ] Gather Photon/voice results and remaining UI/browser permissions; receive actual external
   modeling commits/cards/commands. Inventory implemented/partial/deferred/unverified/pending
   separately, not one “done” column.
3. [ ] Finish source-grounded architecture/research/build narrative using the module order,
   three models and trace above. Date official model selections/license/resource estimates;
   retain unmeasured quality caveats and the SQLite-vs-untested-Postgres distinction.
4. [ ] As part of the delivery assignment, execute the clean temporary-DB CLI/API commands below
   and delivered external train/checkpoint/prep/LoRA commands within standing boundaries.
   Capture exact exits, seed counts, actual source IDs, artifacts/metrics and failures.
   No credentials, downloads or private data.
5. [ ] Run focused affected checks then complete current package/milestone gates, including any
   newly delivered bridge/voice checks. Report current failures with owners. Do not conceal
   compiler failure through shell piping or claim old counts certify new HEAD.
6. [ ] Coordinate formal **learner-agency scrutiny and user testing** and integration/experiment
   validation, reusing unaffected evidence. Every one of the37 pending assertions is mapped
   in [index](../README.md); do not limit final review to the six queue entries.
7. [ ] After explicit browser resumption, finish media and manipulative visible evidence through
   approved owned3102/3101 topology. No user listener/data changes without new exact permission.
8. [ ] Prepare compatible Expo Go/private-LAN pairing/QR instructions and ask the user to perform
   the final actual-iPad checklist below. **Pause for participation and actual outcomes**.
   Missing device/input coverage remains pending, not a retry feature or invented pass.
9. [ ] Publish final honest inventory/results/card links and unresolved follow-ups. No completion
   seal/audit/replay proof subsystem or waived acceptance to make the report green.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

**VAL-DOCS-001:** root links accurate setup/architecture/bottom-up guide/inventory; Python3.12/
Node22/Expo57/Go, locks/secrets/migrate/fictional seed, manual loopback3100/3101 and deliberate
LAN8081 versus current mission3102 safety, unverified PostgreSQL and Xcode limitation.
Actual fresh-DB graph/history/replay/tutor/GRU/eval/example-dryrun/LoRA commands execute with
no credentials/downloads; annotated evidence trace, three models and actual gate results.
External commands remain blocked until delivered; do not invent them.

**VAL-DOCS-002:** dated relevant official/paper citations with relevance/limits, matching cards
for every **actually trained** GRU/LoRA artifact: synthetic/random-base status, provenance,
seed/split, config/license/base revision, checkpoint, actual metrics/resources/limitations.
Selected language-model IDs/licenses/resources/configuration and unmeasured quality remain
honest. Software checks ≠ educational results; no novelty/sponsor/competition/learning gain.

**VAL-IPAD-001:** user-assisted actual compatible iPad/Expo Go/trusted-LAN input/history/
orientation/reload/background/reconnect/media permission/indicator/stop checks. Available
Pencil/mouse/palm outcomes cannot come from browser synthetic pointer tests. Unsupported
haptics may safely no-op; missing participation/input remains unresolved.

Formal review also covers completed implementation owners' still-pending:
VAL-BOARD-009/011; VAL-TEACH-004..008; VAL-PERSONA-002..005; VAL-MEM-004/005;
VAL-PROVIDER-002/003; VAL-REL-002/003; VAL-INTEGRATION-003. Reuse existing specific evidence
and perform normal scrutiny/user testing rather than reimplementing these behaviors.
Media owns the integrated remaining audio/cross-flow claims, not this doc writer.

### Research and model-source work

Explain research relevance, not paper-name decoration: BKT uncertainty/assistance eligibility;
DKT/GRU causal inputs and leakage; scaffolding/assistance dilemma/self-explanation; weak
multimodal-affect inference limits; tutoring evaluation including **MathTutorBench and MRBench**.
Find/verify exact paper dates/URLs through ordinary read-only research within the delivery
assignment; no new web research ran for this handoff. Do not fabricate a citation, benchmark
score or reviewed paper conclusion.
Existing official references to consult:

- https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html
- https://huggingface.co/docs/transformers/chat_templating
- https://huggingface.co/docs/peft/en/tutorial/peft_model_config
- https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct
- https://docs.sympy.org/latest/modules/parsing.html (explain why this app avoids untrusted parsing)
- https://docs.expo.dev/versions/v57.0.0/

SmolLM2 candidate: `HuggingFaceTB/SmolLM2-135M-Instruct`,
revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, Apache-2.0 per metadata; about135M
parameters/~0.54GB float32 parameters **estimate**, not measured peak/latency/quality.
Pretrained weights were not run in adapter tests. Endpoint/Claude model IDs stay configurable;
no live access/quality claim from defaults. Cards cannot be written as if external training
already exists. Readiness random-base probes are not the missing product model cards.

## Verification commands and evidence

### Fresh-DB existing CLI (future, not executed for docs)

Run only after assignment; this is an isolated administrative check with no server:

```sh
cd /Users/huangrh/workspace/rubberducky
RUN_DIR="$(mktemp -d /tmp/rubberducky-delivery.XXXXXX)"
cli() {
  env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$PWD/backend" TUTOR_ENV_FILE="" TUTOR_PROVIDER=mock \
    EXTERNAL_INTEGRATIONS_ENABLED=false TUTOR_LOCAL_MODEL_LOAD_ENABLED=false \
    TUTOR_LOCAL_ALLOW_DOWNLOAD=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    "$PWD/backend/.venv/bin/python" -m app.cli \
    --database-url "sqlite:///$RUN_DIR/tutor.db" "$@"
}
cli migrate
cli seed
cli seed
cli graph validate
cli graph context --learner ada --concept concept.distribution --max-evidence 2 --format text
cli history --learner ada
cli tracing fixture
cli tracing replay --learner bkt-fixture --format text
cli tracing state --learner bkt-fixture
cli memory context --learner ada --concept concept.distribution --assemble --context-window 2048 --max-output-tokens 256
cli interactives status
cli interactives prevetted --component distribution
cli evaluation cases
cli evaluation run --candidate fixture:good
cli evaluation chalk-plan --candidate fixture:good
```

Record actual output/exit at each step, not a shell's final status as proof of all preceding
success. Keep functions/variables in the same shell, use `--database-url` before subcommand.
No destructive DB reset. `pair` is optional/private and not needed for the in-process example.

### Actual mock tutor through FastAPI without a listener (future)

There is no tutor-turn CLI in current source. A clean in-process TestClient around the **actual
app** exercises the documented API rather than inventing a CLI or binding protected ports:

```sh
cd /Users/huangrh/workspace/rubberducky
env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD/backend" TUTOR_ENV_FILE="" TUTOR_PROVIDER=mock \
  EXTERNAL_INTEGRATIONS_ENABLED=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  backend/.venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from app.config import Settings
from app.db.migrate import upgrade_to_head
from app.db.database import Database
from app.db.seed import seed_database
from app.main import create_app

def result(response):
    response.raise_for_status()
    return response.json()

with TemporaryDirectory(prefix="rubberducky-turn-", dir="/tmp") as directory:
    url = "sqlite:///" + str(Path(directory) / "turn.db")
    upgrade_to_head(url)
    database = Database(url)
    with database.transaction() as db:
        seed_database(db)
    database.dispose()
    settings = Settings(database_url=url, tutor_provider="mock",
                        external_integrations_enabled=False,
                        tutor_local_model_load_enabled=False,
                        tutor_local_allow_download=False)
    with TestClient(create_app(settings)) as client:
        paired = result(client.post("/demo/bootstrap", json={"display_name": "Fictional trace"}))
        client.headers["Authorization"] = "Bearer " + paired["access_token"]
        result(client.put("/me/tutor-configuration",
                          json={"appearance": "animal", "personality": "gentle"}))
        session = result(client.post("/sessions", json={}))
        path = "/sessions/" + session["id"]
        state = result(client.get(path + "/state"))
        opening = result(client.post(path + "/check-in",
            headers={"Idempotency-Key": "delivery-checkin-001"},
            json={"expected_revision": state["session"]["revision"],
                  "energy": "ready", "use_practice_problem": True}))
        state = result(client.get(path + "/state"))
        turn = result(client.post(path + "/work",
            headers={"Idempotency-Key": "delivery-work-001"},
            json={"expected_revision": state["session"]["revision"],
                  "text": "2x + 3 = 14", "input_mode": "typed"}))
        print({"opening_status": opening["status"], "turn_id": turn["turn_id"],
               "status": turn["status"], "utterance": turn["utterance"]})
        scene = result(client.get(path + "/scene"))
        print({"scene_revision": scene["scene_revision"],
               "object_ids": [obj["id"] for obj in scene["objects"]]})
        history = result(client.get("/me/history"))
        print({"history_sections": sorted(history)})
PY
```

This source-checked recipe was **not executed** by the docs writer. Validate it on current
source when assigned and record failures honestly; do not call it existing evidence. It
keeps tokens only in memory and prints fictional turn/scene metadata, not credentials.
Expand the actual trace with relevant source IDs/eligibility through existing interfaces,
not a new proof subsystem.

### Remaining command gaps and gates

GRU train/reload/eval, reviewed-example validation/prep/dry-run, teacher transport and
LoRA smoke/reload/matched-eval commands must come from external delivery and be documented
literally, including artifact paths. The existing `evaluation --responses-file` accepts
external outputs but is not a training command.

Run full gates from the [index](../README.md) after focused checks and integration.
Latest historical backend1074/mypy134/Ruff pass atb76811e and frontend461 at1a9ade2 are
not fresh results. Historical standalone tsc exited2; current UI changed. Expo SDK check is
not Expo Doctor/native compile/physical proof. Record exact exits and scoped failures, no
invented historical statuses.

### User-assisted iPad checklist — must wait for real outcomes

First ask for device/iPadOS/Expo Go version and available Pencil/mouse. Explain trusted private
Wi-Fi, no tunnel/public deployment and honest unavailable live media. Use a separately agreed
fictional DB/learner and approved service ownership, never silently adopt current listeners.
Manual developer route after explicit coordination: API on the Mac's private interface3100,
Expo from `frontend/` on LAN8081, Go QR code; explicit
`EXPO_PUBLIC_API_BASE_URL=http://<Mac-private-LAN-IP>:3100` if needed. iPad localhost is not
the Mac. Do not print environment/secrets/pairing tokens.

Record each item as pass/fail/not available/pending with actual user observations:

- [ ] Compatible Go opens the actual shared app; service/provider/mock labels truthful.
- [ ] Available touch/Pencil/mouse dot/drag, intended board scroll suppression and controls
  scrolling; second contact/palm does not splice ink. Missing input device stays unresolved.
- [ ] Erase, student undo/redo, grouped tutor undo preserve other-author work.
- [ ] Portrait/landscape between and during strokes: geometry preserved/cancelled safely.
- [ ] Reload/re-entry preserves committed scene; background/reconnect/retry preserves work,
  honest pending/error status and no stale reply/speech revival.
- [ ] Action-only mic and student/work camera permission, clear orientation/indicator/Stop,
  denial fallback and background release; text/board always usable without understanding.
- [ ] Sound mute/text-only/captions/reduced motion; unsupported haptics no-op without blocking.

Capture dated user results/device/input capabilities and available screenshots, not private
raw media. Real STT/perception/phone delivery remains deferred even on the physical device.
No user/device input means pause final acceptance; browser/package success cannot pass IPAD001.

## Ownership, dependencies, parallelism and stop conditions

Delivery coordinates existing owners, not a catch-all implementation team. Serialize shared
README/CLI/config/gate changes. One browser validator after authorization; no concurrent
heavy training/native compilation. Receive external model results before promising completed
model cards or reproducibility. Ask user for device participation at late final only.

Stop on absent experiment delivery, paused/hidden browser, unowned occupied ports, conflicting
dirty work, secrets/private data or unavailable device. Report exact gap/next owner instead
of auto-retrying, taking over implementation, inventing results or relaxing acceptance.

## Not authorized / deferred

No source implementation, installs/tests/training/services/browser/live activation, staging
or commits from this documentation request. This task's output-path limit does not restrict
ordinary in-scope documentation work in the future delivery assignment.
No public deploy/EAS build, Xcode upgrade, line purchase, paid
fallback, sponsor affiliation, competition eligibility, calibrated-mastery or learning-gain
claim. No new audit/replay/certificate/completion system.

## Copyable assignment prompt

> Complete the assigned `delivery-guide-results-and-native-acceptance` task, including
> appropriate local checks and read-only research within standing boundaries.
> Read index/module/task/working-tree guides. Preserve existing root README and
> user work; distinguish implementation, formal passes, fixtures, deferred live paths and
> pending device results. Reuse completed modules. Receive external GRU/dataset/LoRA code/
> cards/results, never implement missing pipelines. Execute documented isolated-DB paths/
> applicable fresh gates within the assignment, complete source-grounded architecture/research/
> three-model/annotated trace docs and honest model cards. Browser remains paused until
> explicitly resumed and ownership resolved. Prepare actual Expo Go user checklist and
> pause for physical outcomes before claiming VAL-IPAD-001. No invented results or scope.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include pending-ID disposition, fresh vs historical gates, actual seed/trace/source data,
external checkpoint/card/metric links and limits, approved service/browser ownership, dated
physical results or exact user participation needed. No blanket completion if any required
assertion remains pending.
