# Rubberducky

Rubberducky is an iPad-first math tutor that helps learners think a problem through instead of
handing over answers. The client is an Expo (SDK 57) React Native app that runs in Expo Go on an
iPad and as a web build of the same components. The backend is a Python 3.12 FastAPI service that
runs on your Mac.

This is an early prototype. Right now the project contains the runnable skeleton: typed backend
configuration, health and model-readiness endpoints, and a minimal status screen. The default tutor
is a deterministic mock, labeled as such everywhere. No language model is downloaded or contacted,
and every external integration is disabled until you activate it explicitly.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/app/` | FastAPI application (`app.main:app`), typed settings in `app/config.py` |
| `backend/tests/` | Backend tests (pytest) |
| `backend/pyproject.toml` | Tutor backend dependencies and pytest/mypy/Ruff configuration |
| `backend/requirements.lock` | Hash-pinned Python lock (macOS arm64, CPython 3.12) |
| `frontend/` | Expo app, `package-lock.json`, Jest/ESLint/TypeScript configuration |
| `pyproject.toml`, `uv.lock`, `chalk.yaml` | The Chalk project scaffold (see [Chalk](#chalk)) |

## Requirements

- Python **3.12** (not 3.13/3.14).
- Node.js **22** (`frontend/package.json` declares `>=22 <23`). Newer Node releases are not
  supported by the selected tooling. You do not need to change your global Node; put a Node 22
  `bin` directory first on `PATH` for the commands below.
- For the iPad: Expo Go for SDK 57, on the same trusted Wi-Fi network as the Mac.

Do not use globally installed legacy `expo-cli` or `react-native` commands. Every frontend command
runs the project-local Expo CLI through npm.

## Setup

From the repository root:

```sh
# Backend environment (tutor-owned, separate from the Chalk scaffold's root .venv)
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock

# Frontend dependencies (with Node 22 on PATH)
npm --prefix frontend ci
```

The tutor backend always uses `backend/.venv`. The root `.venv` belongs to the Chalk scaffold (it is
managed by uv from the root `pyproject.toml`); do not install tutor packages into it.
`backend/.venv` may also be a symlink to an existing Python 3.12 environment; it is git-ignored
either way.

`backend/requirements.lock` pins exact versions and wheel hashes for macOS on Apple silicon. On
another platform, install from `backend/requirements.in` (same versions, without hashes) or
regenerate a lock for that platform. The PyTorch and Transformers wheels are large, so check free
disk space first. Installing packages does not download any model weights.

`backend/requirements-optional.in` holds the optional PostgreSQL driver. SQLite is the default and
the only tested database. For PostgreSQL, install that driver, set
`DATABASE_URL=postgresql+psycopg://user:password@host/dbname` and run the same `app.cli migrate`;
this path is documented but untested.

## Configuration

The backend reads settings from process environment variables (see `.env.example`). It never reads
the repository-root `.env` file. To load a file, point `TUTOR_ENV_FILE` at it, for example
`TUTOR_ENV_FILE=.env.local`. `.env.local` is git-ignored; keep real credentials there and never in
`EXPO_PUBLIC_*` variables or client code.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TUTOR_PROVIDER` | `mock` | `mock`, `transformers`, `endpoint` or `claude` |
| `EXTERNAL_INTEGRATIONS_ENABLED` | `false` | Required before any remote provider is used |
| `DATABASE_URL` | `sqlite:///./data/tutor.db` | SQLAlchemy database URL |
| `TUTOR_CORS_ORIGINS` | `http://127.0.0.1:3101,http://localhost:3101` | Allowed web origins |
| `DEMO_BOOTSTRAP_ENABLED` | `true` | Allow `POST /demo/bootstrap` to create new fictional learners |
| `PAIRING_CODE_TTL_SECONDS` | `600` | Lifetime of one-time pairing codes (60 to 3600) |
| `TUTOR_LOCAL_MODEL_LOAD_ENABLED` | `false` | Opt-in for lazy local model loading |
| `TUTOR_LOCAL_MODEL_ID` / `_REVISION` | SmolLM2-135M-Instruct, pinned revision | Local model selection |

The frontend finds the API at `EXPO_PUBLIC_API_BASE_URL` if set. Otherwise the web build uses
`http://127.0.0.1:3100`, and Expo Go uses the Mac's LAN address that served the bundle, on port 3100.

## Running

Ports: API **3100**, web **3101**, Expo native development server **8081**.

```sh
# API on loopback
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3100

# Web build of the client on loopback
cd frontend && EXPO_NO_DOTENV=1 npx expo start --web --localhost --port 3101
```

Check the API:

```sh
curl http://127.0.0.1:3100/health        # application liveness
curl http://127.0.0.1:3100/health/model  # tutor model readiness, reported separately
```

Always start Expo from `frontend/` with `EXPO_NO_DOTENV=1`. Expo otherwise loads `.env` files from
its project root, and the repository-root `.env` is not meant for the client.

`/health/model` only inspects configuration. It never loads a model or contacts a provider.

### Database, fictional seeds and pairing

The schema is created only by Alembic migrations (`backend/migrations/`), never `create_all`.
Run these from the repository root before starting the API (the manifest's API start runs both):

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.cli migrate   # upgrade to head; safe to repeat
PYTHONPATH=backend backend/.venv/bin/python -m app.cli seed      # insert missing fictional records
```

Seed records are invented demo content with fixed IDs and `provenance: "fictional_seed"`. Events
created through the running API are `provenance: "submitted"`. Re-seeding inserts nothing new.

Every learner is a labeled fictional demo learner. A device gets a credential in one of two ways:

- `POST /demo/bootstrap` with `{"display_name": "..."}` creates a new, empty fictional learner and
  returns a bearer token once. It never returns or links existing history. Disable it with
  `DEMO_BOOTSTRAP_ENABLED=false`.
- For a seeded learner with fictional history (`ada` or `ben`), issue a one-time code locally and
  redeem it from the device:

  ```sh
  PYTHONPATH=backend backend/.venv/bin/python -m app.cli pair --learner ada
  curl -X POST http://127.0.0.1:3100/pairing/redeem -H 'Content-Type: application/json' \
    -d '{"code": "<code from the pair command>"}'
  ```

Send the token as `Authorization: Bearer <token>`. The server stores only its SHA-256 digest.
Learner scope always comes from the token. No route takes a learner ID, and a record owned by
another learner returns the same `404 not_found` as a record that does not exist.
`POST /auth/revoke` revokes the current token; `app.cli revoke --learner <id>` revokes all of a
learner's tokens. Errors use `{"schema_version": "error.v1", "error": {"code", "message"}}`.

`app.cli history --learner <id|ada|ben>` prints a learner's recent records with provenance. It is
a local administrative tool: it reads the database file directly with no credential check, so it
offers nothing beyond file access and is not exposed over HTTP. Devices use `GET /me/history`.

This is a private local prototype, not a production account or authentication system.

### Concept graph and graph context

The curated algebra curriculum is stored as rows in `concepts` and `prerequisite_edges`:
multiplication → grouping → distribution → simple linear equations, plus equality operations →
simple linear equations. Learning objectives include a procedure, a transfer check and a
concept-explanation objective ("explain why 2(x + 3) equals 2x + 6"). `app/graph/curriculum.py`
loads these rows into a NetworkX DAG for cycle checks, prerequisite traversal and bounded
neighborhoods. No language model is involved.

Personal evidence is stored separately in `evidence_links`. Each link says that one of a
learner's observations `supports` or `contradicts` one of that learner's tentative hypotheses,
with a strength value. Links have no concept-to-concept fields, so they can never add a
curriculum prerequisite.

```sh
CLI="env PYTHONPATH=backend backend/.venv/bin/python -m app.cli"
$CLI graph validate                                          # DAG check, isolated concepts, order
$CLI graph prerequisites --concept concept.linear_equations  # all prerequisites with hop counts
$CLI graph neighborhood --concept concept.distribution --max-hops 1
$CLI graph add-edge --prerequisite concept.linear_equations --concept concept.grouping
#   -> rejected: prerequisite cycle; stored edges are unchanged (use --dry-run to only validate)
$CLI graph context --learner ada --concept concept.distribution --max-evidence 2 --format text
```

`graph context` selects a bounded context for one learner: the target concept, prerequisites and
dependents within `--max-hops` (capped by `--max-nodes`), the learner's non-retracted hypotheses
on those concepts, and recent evidence links (`--max-evidence`, optional `--max-age-days`). The
evidence budget alternates between supporting and contradicting links, newest first, so a small
budget keeps both sides. The output lists every selected concept, edge, hypothesis, link,
observation and underlying source record ID, the confidence and alternatives of each hypothesis,
and how many candidates the budget left out. `--now` fixes the reference time for reproducible
output. Like `history`, this is a local administrative command.

Devices use `GET /graph/context?concept_id=...` with the same bounds as query parameters. The
learner scope comes from the bearer token, so another learner's request returns the same shared
curriculum and none of the first learner's evidence.

### Memory layers and bounded tutor context

Learner memory is kept in six separate layers: raw evidence (attempts, steps, observations,
hints, assessments), derived beliefs (hypotheses and mastery estimates with source IDs and
algorithm/parameter versions), editable preferences (`updated_by` learner or operator), temporary
session context, source-linked episodic notes (review date, expiry, correction state) and the
persona configuration. Session context such as "tired today" applies to its own session only.
Starting a new session or ending the session expires it, and the next context asks the tutor to
check again instead of treating it as a fact.

A provider can only *propose* memory updates: a session-context entry for the current session,
an episodic note, or a review flag on an existing note. `app/learner/memory_updates.py` checks
the whole batch (schema, learner, cited sources, session scope, expiry windows, evidence kind and
confidence) before writing anything. One bad proposal rejects the batch. Proposals cannot name a
table, change preferences, persona, evidence or curriculum, or cite another learner's records.

`app/inference/context.py` builds the context a provider would see. It contains the bounded graph
context, a few recent observations from a fixed window, current session context, usable notes,
preferences and persona. It never includes the lifetime transcript. The context is serialized
and measured. When it is over budget, free text is removed first and then low-priority items are
dropped. Source IDs, polarity and status (curriculum, observed, verified, self-report, inference,
derived estimate, learner setting) always remain. Omissions are counted, and a context that
cannot fit is reported as `insufficient`. `app/inference/request.py` applies the provider's
window, output reservation and character limit to the final assembled request. The default
token counter counts UTF-8 bytes, which is an upper bound for byte-level BPE tokenizers.

```sh
$CLI memory layers --learner ada
$CLI memory context --learner ada --concept concept.distribution --max-chars 1500 --format text
$CLI memory context --learner ada --concept concept.distribution --assemble \
    --context-window 2048 --max-output-tokens 256
$CLI memory propose --learner ada --file proposals.json --turn-id turn-1 --dry-run
```

Devices use `GET /memory/layers` and `GET /memory/context?concept_id=...`. As with every
learner route, the scope comes from the bearer token.
### Knowledge tracing (NumPy BKT) and history replay

`backend/app/tracing/` implements Bayesian Knowledge Tracing as small NumPy functions
(`bkt.py`): predicted correctness `p(1-s) + (1-p)g`, the correct/incorrect posteriors and the
learning transition `posterior + (1-posterior)T`. The predictor always predicts before it
observes. Its response probability (`p_correct`, target `next_independent_response_correct`) is
reported separately from its latent knowledge estimate (`latent_knowledge`). Guess and slip
describe uncertainty in a single response; they are not labels for the learner.

Parameters must be finite and in `[0, 1]`, with `p_guess + p_slip < 1`. Parameter sets are
immutable and versioned. The default `bkt-handset.v1` (`p_init=.2, p_learn=.1, p_guess=.25,
p_slip=.1`) is hand-chosen and uncalibrated. If a response has zero probability under the
current state (for example `p=0, g=0` and a correct answer), the predictor records
`impossible_observation` and does not update. It never produces NaN.

Only independent, verified, non-explanation assessments update BKT. Hinted, answer-revealed,
step-level, self-report and unknown-outcome evidence is kept and reported with a reason. One
problem counts at most once per concept. Replay recomputes from raw observations starting at
`p_init` and replaces the derived rows (`bkt_counted_opportunities`, `mastery_estimates`) for
that learner and parameter version, so repeated replays never duplicate anything.

```sh
CLI="env PYTHONPATH=backend backend/.venv/bin/python -m app.cli"
$CLI tracing fixture                                   # fictional 'bkt-fixture' learner
$CLI tracing replay --learner bkt-fixture --format text  # two counted opportunities -> 0.82
$CLI tracing state --learner bkt-fixture               # persisted ledger and estimate
$CLI tracing parameters add --parameter-version bkt-handset-no-learn.v1 --p-init 0.2 \
  --p-learn 0 --p-guess 0.25 --p-slip 0.1 --description "No-learning comparison"
$CLI tracing replay --learner bkt-fixture --parameter-version bkt-handset-no-learn.v1  # 81/106
$CLI tracing readiness --learner bkt-fixture           # qualitative bands, no probabilities
```

`--dry-run` computes without persisting, and `--state-out file.json` saves the predictor
snapshot. Devices use `GET /tracing/readiness`, which returns only qualitative bands
(`not_enough_evidence`, `emerging`, `developing`, `strong_so_far`) and a separate
independent-transfer status. It never returns a mastery score.
### Whiteboard scene operations and author-safe history

The board is a durable logical-coordinate scene (`1600x1200`, one fixed 3-unit student pen).
Tutor drawing proposals pass through six validated tools (`draw_path`, `draw_shape` with
circle/rectangle/line/bracket/arrow, `add_math`, `highlight`, `erase_tutor_object`,
`focus_region`) with finite bounds, point/payload budgets and tutor ownership checks; one bad
action rejects the whole turn draft before anything is committed. The student never gets a
brush or color choice: the server assigns pen width and the locked `student`/`tutor` color
roles, and every object carries id, author, semantic role, session, UTC time and optional
teaching step. Tutor objects are board state, never student work or assessment evidence.

Every visible change is one row in a per-session operation log with a monotonic
`scene_revision`. Clients commit one operation per finished stroke or history action:

- `POST /sessions/{id}/scene/operations` with `{"operation_id", "expected_scene_revision",
  "action"}`; actions are `add_stroke`, `erase_object` (own objects only), `undo`, `redo`
  and `undo_tutor_move`. Identical retries replay the stored outcome (`replayed: true`), a
  reused id with different content is `409 idempotency_conflict`, and a stale expectation is
  `409 revision_conflict`, so an offline outbox can resync and retry safely.
- `GET /sessions/{id}/scene` returns the visible objects, current scene revision, board/pen
  spec and the undo/redo/tutor-move availability flags.
- `GET /sessions/{id}/scene/operations?after_seq=N` is the replay feed a reconnecting client
  uses to catch up on missed operations in order.

Histories are author-safe: student undo/redo walk only the student's own strokes and erases,
while `undo_tutor_move` reverses one whole tutor teaching move (every object from that turn)
as a group, leaving student objects and the student's history position untouched. Erased or
undone objects stay hidden after a reload or restart; the operation log is authoritative and
`scene_objects.deleted_at` is the materialized visibility updated in the same transaction.

The client holds up its end with a durable per-session outbox and scene cache
(`frontend/src/storage/outbox.ts`, `sceneCache.ts`, AsyncStorage on device and web). A finished
stroke that cannot reach the server is queued under its original operation id, stays on the
board as a faded dashed mark labeled "not saved yet", and is retried with the same id on
reconnect or the next app load, so a lost acknowledgement replays instead of duplicating.
History edits (erase/undo/redo/tutor-move undo) depend on current server state and are refused
honestly while offline rather than queued. The last committed server snapshot is cached so
re-entry paints real work immediately, and the board ignores input until its first real layout
measurement so an early stroke can never be squashed into a corner. The board always says when
work is unsaved; quiet means saved.
### iPad over trusted Wi-Fi (Expo Go)

Only do this on a private network you trust. There is no public tunnel.

```sh
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 3100
cd frontend && EXPO_NO_DOTENV=1 npx expo start --lan --port 8081
```

Scan the QR code with the iPad camera to open the project in Expo Go. The status screen should say
"Tutor service connected". If it does not, check that the Mac firewall allows ports 3100 and 8081.
A standalone native build is not part of this route: Expo SDK 57 needs Xcode 26.4 or newer to
compile natively, and Expo Go does not.

## Checks

Run from the repository root with Node 22 on `PATH`:

```sh
backend/.venv/bin/python -m pytest backend/tests -q && npm --prefix frontend test -- --runInBand
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app && npm --prefix frontend run typecheck
backend/.venv/bin/python -m ruff check backend && npm --prefix frontend run lint
npm --prefix frontend run build:web
npm --prefix frontend run check:expo
```

mypy must use `--config-file backend/pyproject.toml`. The root `pyproject.toml` belongs to the Chalk
scaffold and sets `ignore_errors = true`, which would make the check meaningless.
`check:expo` verifies SDK dependency compatibility. `expo-doctor` additionally reports the Xcode
version limitation described above.

## Chalk

The repository also contains a Chalk project scaffold created with `chalk init`:

- `chalk.yaml` names the Chalk project and its environments.
- The root `pyproject.toml` and `uv.lock` hold the Chalk project's Python dependencies, managed with
  [uv](https://docs.astral.sh/uv/). They are separate from the tutor backend's dependencies.
- `AGENTS.md` gives coding agents Chalk-specific instructions.

The tutor uses Chalk (`chalkcompute`) only for an optional tutoring-evaluation adapter, which is
disabled by default. Nothing is deployed to Chalk unless you run Chalk commands yourself.

Docs: https://docs.chalk.ai
