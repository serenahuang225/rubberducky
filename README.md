# Rubberducky

Rubberducky is an iPad-first math tutor that helps learners think a problem through instead of
handing over answers. The client is an Expo (SDK 57) React Native app that runs in Expo Go on an
iPad and as a web build of the same components. The backend is a Python 3.12 FastAPI service that
runs on your Mac.

This is an early prototype. The shared client runs the first unit's full learning loop: first-run
onboarding (appearance and teaching style are independent choices), a short check-in and goal, one
concise teaching move at a time on a nearly white shared whiteboard, typed/confirmed work
submissions with bounded verification, partial hints with visible tutor marks, grounded feedback,
assistance-aware fresh transfer problems and a short concept explanation. A "Finish for today"
control ends the session; the next session's instruction adapts to the earlier saved evidence.
"Still thinking" is a local acknowledgement only, and "Help me" stays reachable beside the typed
input. The default tutor is a deterministic mock, labeled as such everywhere ("Demo mode" in the
client, `is_mock` in the API). No language model is downloaded or contacted, and every external
integration is disabled until you activate it explicitly.

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
| `TUTOR_LOCAL_DEVICE` / `_DTYPE` | `cpu` / `float32` | `cpu`, `mps` or `cuda`; `float32`, `bfloat16` or `float16` (not on CPU) |
| `TUTOR_LOCAL_ALLOW_DOWNLOAD` | `false` | Without it, weights load from the local Hugging Face cache only |
| `TUTOR_LOCAL_CONTEXT_WINDOW_TOKENS` / `_MAX_NEW_TOKENS` | `8192` / `512` | Prompt plus output ceiling and output ceiling |
| `TUTOR_LOCAL_MAX_QUEUE` / `_TIMEOUT_SECONDS` | `2` / `120` | Turns allowed to wait behind the running one; per-call deadline |
| `TUTOR_REMOTE_TIMEOUT_SECONDS` / `_MAX_ATTEMPTS` / `_BACKOFF_SECONDS` | `30` / `3` / `0.5` | Remote deadline (all attempts), attempts and base backoff |
| `TUTOR_REMOTE_MAX_OUTPUT_TOKENS` / `_MAX_REQUEST_CHARS` | `512` / `32000` | Remote output and request-size ceilings |
| `TUTOR_ENDPOINT_BASE_URL` / `_MODEL` / `_API_KEY` / `_STREAMING` | unset / unset / unset / `true` | OpenAI-compatible server (`.../chat/completions`) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_WORKSPACE_ID` | unset | Claude; no default model is guessed. A key that is not scoped to one workspace must send the `wrkspc_` id |
| `TUTOR_MEDIA_FIXTURES_ENABLED` | `true` | Shows the labeled simulated voice and photo fixtures in the app; real capture is unaffected |

## Optional voice and camera

Voice and camera are off until the learner opens the "Voice and camera" panel and presses a start
button. Nothing asks for a permission, opens a device or calls the media routes before that.
Typing and the board always work without media. A denied or missing device, a backgrounded app,
Stop, an interruption, new work, a new problem, mute and text-only mode all release the device and
cancel any speech. A speech or caption callback that arrives after that is ignored.

- `GET /media/capabilities` reports what the server can do. It accepts text from the
  browser's speech recognizer and does not receive the audio. Photo perception is **not
  configured**. An open microphone is "listening" only when this browser can actually
  transcribe (Safari and Chrome). Expo Go has no speech engine, so the microphone can be on
  there without being called listening. A student-facing or work-facing camera choice is the
  learner's.
- `POST /sessions/{id}/media/events` accepts bounded, uncertain events: at most 262144 bytes and
  2048 px per image edge, 500 characters of transcript, 3 image events per minute and 12 per
  session, and 120 events per minute and 500 per session overall. Excess, stale (old session
  revision) and foreign-session events are rejected. Interim transcripts stay provisional; a final
  transcript is idempotent. A recognized transcript or photo reading is a candidate that the
  learner edits and confirms before it is used. Digital strokes stay authoritative. Nothing infers
  emotion, identity or disability.
- Raw audio, video and image bytes are not stored or logged by default. Only a size and an
  optional width and height leave the device for a photo.
- The simulated voice sequence and photo events (interim, revised interim, final, duplicate final,
  late interim) are deterministic fixtures, labeled "simulated" in the app. They are not live
  transcription, and the deterministic speech events are not live acoustic barge-in.
- Logs and error bodies share one redaction path (`backend/app/redaction.py`). Request-validation
  failures return the same `error.v1` envelope as other errors, keep safe field-level diagnostics
  and never echo the submitted input.

## Tutor language-model providers

The default is `TUTOR_PROVIDER=mock`, a labeled deterministic tutor that is not a language model.
With `TUTOR_PROVIDER=claude` and `EXTERNAL_INTEGRATIONS_ENABLED=true` in the file loaded by
`TUTOR_ENV_FILE`, the opening screen accepts a typed question, a text file, a screenshot, or a photo from the iPad camera.
Claude reads it and the reply is shown in the prompt and as a note on the board. The picture
is sent for that turn and is not stored. The built-in algebra unit is still available as
"Use a practice problem".
Every provider, mock or not, only *proposes* a draft. The coordinator commits it only when it is a
complete, valid draft for the current turn and session revision; a truncated, malformed, stale or
rejected draft fails the turn with no tutor text, drawings, hints or memory written. A provider
failure never switches to another provider, and there is no paid fallback.

**Local Transformers (`TUTOR_PROVIDER=transformers`).** Opt-in and CPU-first. Nothing is imported
or downloaded at startup, health or readiness (`/health/model` reports `disabled`, `not_loaded`,
then `ready`). With `TUTOR_LOCAL_MODEL_LOAD_ENABLED=true`, the first turn loads the model once per
process on a dedicated worker thread, so the event loop and health stay responsive; later turns
reuse it. One generation runs at a time, at most `TUTOR_LOCAL_MAX_QUEUE` more wait, and any further
turn is refused at once. A deadline or cancel stops generation between tokens and a late result is
discarded, never committed. Loading is cache-only and also switches the Hugging Face Hub offline
while it runs; `TUTOR_LOCAL_ALLOW_DOWNLOAD=true` is the only way weights are fetched, and it is
not set by default. Decoding is greedy (no sampling), `trust_remote_code` is off, and a request
whose prompt plus output ceiling exceeds the configured window is refused rather than truncated.
An unavailable `cuda`/`mps` device or half precision on CPU is a typed `device_unavailable` error.

| | |
| --- | --- |
| Candidate (as of 2026-10-17) | `HuggingFaceTB/SmolLM2-135M-Instruct` |
| Pinned revision | `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| License | Apache-2.0, as published on the model card; confirm it when you download |
| Weight memory (estimate) | about 135M parameters: roughly 0.54 GB in `float32`, 0.27 GB in `bfloat16`, plus runtime overhead. Not measured here |
| Context | The 8192-token default is a configured ceiling, not read from the model. Check the model's `config.json` for the pinned revision before raising it |
| Limits | A 135M model gives weak, sometimes off-plan tutoring; the coordinator's validation, not the model, enforces what the learner sees. Tests do **not** run these weights: they use instrumented loaders and a tiny random-weight model, so no pretrained quality, latency or memory is claimed |

To use it, download the weights yourself first (this is the one step that touches the network):

```sh
HF_HOME=~/.cache/huggingface backend/.venv/bin/python -c "from huggingface_hub import snapshot_download as d; d('HuggingFaceTB/SmolLM2-135M-Instruct', revision='12fd25f77366fa6b3b4b768ec3050bf629380bac')"
TUTOR_PROVIDER=transformers TUTOR_LOCAL_MODEL_LOAD_ENABLED=true  # then start the API
```

**Remote providers (`endpoint`, `claude`).** Disabled until `EXTERNAL_INTEGRATIONS_ENABLED=true`
*and* the provider is configured; a selected but disabled provider answers turns with
`503 provider_unavailable`. Readiness is `disabled`, then `unverified` (never "ready", because
nothing contacts the provider at startup). Keys are read only server-side from the environment,
never returned by the API and never put in events or errors. The label and `/health/model`
`transmission` field say where learner context goes: `remote_provider` (sent to Anthropic or a
remote server) or `loopback` (an `http://127.0.0.1` server on this machine). A non-loopback endpoint
must use `https`, and redirects are not followed so a key cannot leave the configured host.

Both adapters use one overall deadline per turn, a bounded number of attempts (only transient
failures such as 429, 5xx and dropped connections are retried, honoring `Retry-After` within the
deadline), and an output-token ceiling. Streams may arrive in arbitrary fragments; a stream that
ends before its completion marker is retried and never committed. A completed but malformed,
oversized, truncated or stale answer is rejected without a second call. The OpenAI-compatible
adapter uses `httpx`; Claude uses the official `anthropic` SDK, which in the installed version
runs on `httpx2`. Their tests use in-process transport fixtures with outbound sockets blocked,
so they establish request shapes and failure handling, not live provider behavior or quality.
Live calls are deferred and unverified.

The frontend finds the API at `EXPO_PUBLIC_API_BASE_URL` if set. Otherwise the web build uses
`http://127.0.0.1:3100`, and Expo Go uses the Mac's LAN address that served the bundle, on port 3100.

## Running

Ports: API **3100**, web **3101**, Expo native development server **8081**.

```sh
# API on loopback. TUTOR_ENV_FILE loads .env.local (Claude key and model). Without it the
# tutor stays the scripted mock and cannot read a question the learner brings.
TUTOR_ENV_FILE=.env.local PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3100

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
### Persona rule, comfort override and accessibility preferences

- `GET|PUT /me/tutor-configuration`: the first selection records server UTC time. A *different*
  appearance or personality is accepted only at or after `last_changed_at + 604800 s`
  (equality counts); earlier it is `409 persona_change_locked` with `Retry-After` and the exact
  next UTC instant, and nothing (including a bundled comfort value) is written. Re-sending the
  current pair is a no-op that never starts or resets the wait, before or after eligibility.
  Competing requests use an atomic compare-and-swap, so only one can consume an eligibility.
  Responses carry `outcome`, `persona_locked`, `server_now` and `next_change_available_at`.
  Client clocks, headers and time zones are ignored.
- `PUT /me/comfort-override` (`none | neutral_supportive | reduced_sass`): immediate, applies to
  the next tutor turn, never locked, and writes only `comfort_override`/`comfort_updated_at`.
- `GET|PATCH /me/accessibility-preferences` (`animation`, `sound_enabled`, `haptics_enabled`,
  `text_only`, `captions_enabled`): partial, never locked, stored as learner preferences
  (`a11y_*`) and independent of the persona row.

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

## Photon messaging

`integrations/photon` is an optional Photon Beta (2.0) bridge. It uses `@photon-ai/api`
against `https://api.photon.codes`, not the Stable Spectrum packages. It stays off unless
`PHOTON_MESSAGING_ENABLED=true` and these are set: `PHOTON_API_KEY` (bearer `pho_sk_...`),
`PHOTON_PROJECT_ID` (`pho_prj_...`), `PHOTON_AGENT_HANDLE` (the assigned iMessage line), and
`PHOTON_TEST_SENDER` (the human identity allowed to text that line). A phone number does not
select a learner. The first text from that sender is the pairing code from
`python -m app.cli pair`; later texts continue that learner's session, including the previous
question and knowledge graph inside the tutor. Nothing is sent when the bridge is disabled,
and this repository does not assign a line or buy a number.

```sh
npm --prefix integrations/photon install
npm --prefix integrations/photon test
```

## Chalk

The repository also contains a Chalk project scaffold created with `chalk init`:

- `chalk.yaml` names the Chalk project and its environments.
- The root `pyproject.toml` and `uv.lock` hold the Chalk project's Python dependencies, managed with
  [uv](https://docs.astral.sh/uv/). They are separate from the tutor backend's dependencies.
- `AGENTS.md` gives coding agents Chalk-specific instructions.

The tutor uses Chalk (`chalkcompute`) only for an optional tutoring-evaluation adapter, which is
disabled by default. Nothing is deployed to Chalk unless you run Chalk commands yourself.

A labeled fictional walkthrough of Chalk, Factory Droid, and Daytona runs entirely on this
machine. It scores scripted tutor replies, shows an explanation written in the repository, and
runs the local trusted checks. Nothing is uploaded, and no sandbox is created.

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.cli demo
```

The same walkthrough is `GET /demo/integrations` while demo bootstrap is enabled, and in the
app under Settings, “Fictional demos”.

Docs: https://docs.chalk.ai

---

## Agent handoff — start here for remaining work

**This is an additive documentation handoff, not permission to resume the paused mission,
browser testing, live integrations or current development services.** The existing README
above is preserved verbatim; its manual setup/live-provider/LAN examples are not current
agent execution authorization.

- **[Remaining-work index, assignment map and all37 pending assertions](docs/agent-handoff/README.md)**
- **[Backend setup, isolated database, module/API flow and commands](backend/README.md)**
- **[Frontend setup, shared-client flow, scripts and service safety](frontend/README.md)**
- [Working-tree ownership and interrupted-worker recovery](docs/agent-handoff/working-tree/README.md)

Snapshot at `904d965`: learning-loop is closed/validated33/33; formal total is33 passed/
37 pending. Agency implementation is mostly complete, not formally finished. Factory/Daytona
adapters/native component and Chalk evaluator are implemented; learner manipulative wiring,
Photon messaging/LiveKit voice, remaining media validation, external modeling integration,
delivery and actual user-iPad acceptance remain. The interrupted Photon worker only explored;
its `in_progress` label does not mean a live worker or finished bridge.

**Browser work is USER-PAUSED.** Do not start/stop/adopt user3100/3101/8081 services or use
proposed3103. Future resumed mission tests use approved isolated API3102/separate DB and
owner-coordinated web3101 with explicit override; see the index before any action.
GRU/shared-dataset/LoRA implementation belongs to another agent: receive its commits/results,
do not duplicate it. Historical tests are not fresh certification of current dirty UI, and
fixtures are not live perception/delivery, trained-model quality, learning gains or physical
iPad/Pencil evidence. Each assignment includes concrete scope, prerequisites, existing
acceptance behavior, future verification and a copyable agent prompt.
