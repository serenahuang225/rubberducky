# Tutor backend

Python3.12 FastAPI application at `app.main:app`. Start with the
[handoff index](../docs/agent-handoff/README.md) and
[working-tree rules](../docs/agent-handoff/working-tree/README.md).
These are setup/reference instructions, **not authorization to resume the paused mission**.
No services, tests, installs or live calls were run for this documentation handoff.

## Environment and safe setup

Use `backend/.venv`, never the user's root Chalk `.venv`/uv project. On this machine it is
a symlink to an existing Python3.12 readiness environment; do not replace it. On a new,
authorized development checkout only:

```sh
cd /Users/huangrh/workspace/rubberducky
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
```

The hash lock targets macOS arm64 CPython3.12. Other platforms need a reviewed platform
lock or the exact-version `backend/requirements.in`; do not silently discard hash failures.
Large Torch/Transformers packages are dependencies, not permission to download model weights.
Optional PostgreSQL driver: `backend/requirements-optional.in`; SQLite is the tested store.
No Redis/graph database/server is needed.

`app/config.py` reads process environment only, unless explicitly opted into a file through
`TUTOR_ENV_FILE`. Do not inspect/load `.env` or `.env.local` during agent checks. A present
credential does not activate an integration. The root README includes manual developer/live
configuration examples; current agent permissions in the handoff take precedence.

| Setting group | Current behavior |
| --- | --- |
| `DATABASE_URL` | Defaults to `sqlite:///./data/tutor.db`; **override for every agent command** |
| `TUTOR_PROVIDER` | `mock` default; also `transformers`, `endpoint`, `claude` |
| `EXTERNAL_INTEGRATIONS_ENABLED` | false default; selected remote provider remains unavailable when disabled |
| Local model | load/download false; CPU float32, pinned SmolLM2 candidate; lazy first-use only |
| Local limits | context8192, new tokens512, queue2 behind one generation, timeout120s |
| Remote limits | overall30s, max3 attempts, backoff0.5s, output512 tokens, request32000 chars |
| Endpoint | explicit base/model/key; streaming true; remote HTTPS and disclosure, no redirects/fallback |
| Claude | explicit model/key; optional workspace ID, never a guessed live model |
| Factory/Daytona | individual enable flags false, plus global gate; explicit runtime/model/key/config |
| Chalk | individual enable false, explicit client ID/secret/environment; max40 rows,600s; judge separately gated/model required |
| Media | simulated fixtures enabled, real transcription/perception unconfigured; capture not automatic |
| Pairing/bootstrap | fictional demo bootstrap true; code TTL600s (60..3600) |
| CORS | loopback web3101 origins; no permission for public exposure |

Keep keys server-side, out of `EXPO_PUBLIC_*`, logs, command transcripts and commits.
Inspect names/types/defaults in [config](app/config.py), not real environment values.

## Fresh isolated database and existing CLI

Future local verification after assignment; commands deliberately use a new `/tmp` directory,
clean environment, disabled providers, and **do not open user data or bind a port**:

```sh
cd /Users/huangrh/workspace/rubberducky
RUN_DIR="$(mktemp -d /tmp/rubberducky-cli.XXXXXX)"
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
cli seed                    # idempotent; do not invent expected row counts
cli learners
cli graph validate
cli graph prerequisites --concept concept.linear_equations
cli graph neighborhood --concept concept.distribution --max-hops 1
cli graph context --learner ada --concept concept.distribution --max-evidence 2 --format text
cli history --learner ada
cli memory layers --learner ada
cli memory context --learner ada --concept concept.distribution --max-chars 1500 --format text
cli tracing fixture
cli tracing replay --learner bkt-fixture --format text
cli tracing state --learner bkt-fixture
cli tracing readiness --learner bkt-fixture
cli interactives status
cli interactives prevetted --component grouping
cli interactives generate --concept concept.distribution --misconception "Only multiplies the first term"
cli evaluation status
cli evaluation cases
cli evaluation run --candidate fixture:good
cli evaluation chalk-plan --candidate fixture:good
cli demo
```

Keep that shell and `RUN_DIR` for related invocations; fresh Execute calls do not inherit shell
functions. `--database-url` is a **top-level option before the subcommand**.
Migrate uses Alembic to current head `0012_duck_personalities`; do not use `create_all` or edit
old migrations. Seeds are fictional/idempotent and respect deletion tombstones.
History/graph/memory CLI is local administrative file access, not authenticated HTTP.
`pair --learner ada` prints a short-lived one-time code: handle privately, never paste
tokens/codes in reports. `history` supports ada/ben aliases; use `learners` to get the actual
UUID for the BKT fixture.

There is **no tutor-turn CLI, GRU train CLI, dataset pipeline or LoRA CLI in this snapshot**.
Do not invent flags. Use the actual API/coordinator for a tutor turn and integrate delivered
external experiment commands later; see [delivery](../docs/agent-handoff/delivery-and-acceptance/README.md).
Never add `--confirm-live` to “see if it works.”

## Module map

| Module | Responsibility / interface |
| --- | --- |
| [main](app/main.py), [api](app/api/) | App creation, lifespan recovery, scoped HTTP routes, shared `error.v1` and sanitized422 |
| [schemas](app/schemas/) | Versioned Pydantic contracts, UTC/confidence/missingness; not statistical models |
| [db](app/db/), [migrations](migrations/) | SQLAlchemy, composite learner FKs, SQLite transactions, Alembic, fictional seeds |
| [learner](app/learner/) | Pairing/scope, memory layers/proposals/inspection, correction/deletion/derived repair, persona/preferences |
| [graph](app/graph/) | NetworkX curated prerequisite DAG; separate personal support/contradiction links and bounded context |
| [tracing](app/tracing/) | NumPy BKT, eligibility ledger/replay/readiness and common predictor protocol |
| [verification](app/verification/) | Allowlisted bounded grammar constructs SymPy; no untrusted eval/parse_expr/sympify |
| [pedagogy](app/pedagogy/) | Deterministic plan, tentative diagnosis, scaffold/fade/transfer, respectful styles |
| [tutor](app/tutor/) | Reserve/infer/recheck/commit coordinator, evidence/state, waiting, epoch cancellation and question intake |
| [inference](app/inference/) | Bounded source-linked context/request, mock/local/endpoint/Claude, lazy loading/retry/deadline/cancel |
| [whiteboard](app/whiteboard/) | Six validated tool families,1600×1200 logical geometry,3-unit pen, author-safe operation log |
| [multimodal](app/multimodal/) | Uncertain bounded session/revision events, not live perception |
| [interactives](app/interactives/) | Constrained Droid generation, trusted Daytona checks, labeled release/fallback; CLI, not HTTP/UI wiring |
| [tutoring_eval](app/tutoring_eval/) | Seven-case/nine-turn causal fictional replay, rubric/Candidate, explicit Chalk adapter |
| [redaction](app/redaction.py), [tests](tests/) | Shared log/error redaction and actual module/SQLite/SDK fixture checks |

No production Photon bridge/voice worker or experiment package exists yet. Their assignments
describe planned work rather than pretending those paths/commands are present.

## Request, event and persistence flow

1. `POST /demo/bootstrap` creates a new empty **fictional** learner; existing seeded history
   requires `POST /pairing/redeem` with a one-time locally issued code. Only token hashes are
   stored. Normal routes derive learner scope from the bearer credential; foreign IDs return
   the same404 as missing. `POST /auth/revoke` revokes it.
2. Configure via `PUT /me/tutor-configuration`; independent comfort/accessibility routes do not
   consume the atomic server-UTC604800s durable-pair cooldown.
3. `POST /sessions` with `{}` starts a session. `GET /sessions/{id}/state` supplies current
   revision/problem. Check-in/work/help require `Idempotency-Key` and `expected_revision`.
   Example work body: `{"expected_revision":N,"text":"2x + 6 = 14","input_mode":"typed"}`.
   Unconfirmed ink only prompts confirmation, never creates a graded step.
4. [execute_turn](app/tutor/coordinator.py) reserves in a short transaction, builds bounded
   graph/memory context and policy/verifier plan, infers outside the transaction, then rechecks
   learner/session/revision/cancellation epoch before atomically committing a valid draft.
   One malformed/stale/unsafe draft commits no tutor text/tools/memory. Raw submitted evidence
   and provider proposals remain distinct.
5. `GET /sessions/{id}/events` is a bounded **polling** turn feed, not SSE. Remote provider
   streaming is adapter-internal; do not confuse it with learner HTTP streaming.
   `GET /sessions/{id}/turns/{turn_id}` inspects an outcome.
6. Scene `GET/POST /sessions/{id}/scene/operations` and scene snapshot preserve monotonic
   scene revisions and original operation IDs. Identical retries replay, changed content/key
   conflicts, student history and grouped tutor undo stay separate.
7. Interrupt body is `{"observed_epoch":N,"reason":"student_interrupt"}` on
   `POST /sessions/{id}/interrupt`; it replays by observed epoch, **not** a made-up
   `expected_epoch`/pending-turn field. Startup settles interrupted pending work honestly.
   Correction/deletion/new work/problem/session changes also fence stale effects.
8. Verified independent assessments alone enter BKT; hints/revelations/self-report/explanations
   are retained but not automatic mastery. Memory proposals need current own source IDs.
   Inspection/correction/session/profile deletion replay/invalidate derived dependencies;
   local active-store deletion is not secure disk/backup/vendor erasure.

Media `/media/capabilities` and scoped `/sessions/{id}/media/events` never make uncertain
recognition authoritative. Limits: image262144 bytes/2048px edge,3 images/minute and12/session;
all events120/minute and500/session; transcript500 chars. No default raw-media storage/logging.
Opening-question screenshot is a **different**, externally edited check-in path (schema
allows2200000 base64 chars), not the bounded media-event photo path. Preserve its owner;
do not conflate it with completed live camera/perception support.

## Testing and runtime limits

After an implementation assignment, run focused module tests, then applicable gates:

```sh
cd /Users/huangrh/workspace/rubberducky
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
```

Root mypy ignores errors: omitting the backend config gives a meaningless gate.
Tests use temporary migrated SQLite and intercepted provider transports. Claude SDK uses
httpx2; endpoint uses httpx. A tiny random Transformer test is not pretrained execution.
Historical `b76811e` checks:1074 backend tests/mypy134/Ruff exit0, **not fresh current gates**.

Do not start a server now. After explicit resumption, use mission `services.yaml` and its
derived `start-test-api.sh`/`stop-test-api.sh`, with fixed3102 DB and clean environment, then
owned web3101 with explicit API override. Owner/birth/UID/command/cwd checks govern shutdown.
Manual trusted-LAN API3100/Expo8081 is a separate user-assisted route, not permission to
adopt existing processes. PostgreSQL URL `postgresql+psycopg://...` uses the same migration CLI
after an authorized driver install; actual PostgreSQL deployment is **untested**.

## Remaining assignments and honest limits

- [Photon](../docs/agent-handoff/photon-messaging/README.md) and
  [voice](../docs/agent-handoff/livekit-voice/README.md): absent production implementation.
- [Interactive wiring](../docs/agent-handoff/interactive-wiring/README.md): backend release
  pipeline exists, learner mount absent. Credits monitoring is not a hard spend cap;
  sandbox deletion is attempted and failures logged, never guaranteed.
- [Media](../docs/agent-handoff/media-validation/README.md): retained implementation, paused
  visible validation; fixtures do not establish real STT/perception/acoustic barge-in.
- [Modeling](../docs/agent-handoff/modeling-integration/README.md): receive external code,
  do not duplicate implementation. Handset BKT is uncalibrated.
- Chalk deploy modules `chalk_functions.py`/`chalk_judge.py` **deploy on import**; only the
  gated adapter loader may import them. Local fixture reports have
  `trained_model_result=false`, `learning_gain_claim=false`; cloud enablement, shipping,
  judge-column/cost/latency remain unverified.
- [Delivery](../docs/agent-handoff/delivery-and-acceptance/README.md): fresh evidence,
  formal validation, guides/research/cards and actual iPad participation remain.
