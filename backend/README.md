# Thinking-partner backend

Python 3.12 / FastAPI / SQLAlchemy / Alembic. SQLite stores scoped learners, sessions,
evidence, memory, and the whiteboard. Start with the [root guide](../README.md) or
[hosted deployment guide](../deploy/chalk/README.md).

## Configuration and startup

Settings are defined in [app/config.py](app/config.py). Process variables take precedence;
`TUTOR_ENV_FILE=/absolute/path/to/.env.local` explicitly loads a private file. The root `.env`
is not automatically loaded. Never dump configuration values or put credentials in client code.

Useful settings:

- `DATABASE_URL`: defaults to `sqlite:///./data/tutor.db`, relative to the process directory.
- `TUTOR_PROVIDER`: `mock` by default; `claude`, `endpoint`, and `transformers` are optional.
- `EXTERNAL_INTEGRATIONS_ENABLED`: false by default; required for remote providers.
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, optional `ANTHROPIC_WORKSPACE_ID`: Claude settings.
- `TUTOR_CORS_ORIGINS`: allowed browser origins; defaults to loopback web port 3101.
- `DEMO_BOOTSTRAP_ENABLED`: permits new fictional learners; true by default.
- `XAI_SPEECH_ENABLED` and `XAI_API_KEY`: optional hold-to-talk, also requiring external enable.
- Factory, Daytona, Chalk evaluations, local loading, and downloads have independent gates.

The hosted wrapper explicitly enables Claude behind its passcode and creates a second,
isolated mock app for public scripted practice. Those are deployment overrides, not defaults.

From the repository root, after installing backend dependencies:

```sh
export PYTHONPATH="$PWD/backend"
export TUTOR_ENV_FILE="$PWD/.env.local"
backend/.venv/bin/python -m app.cli migrate
backend/.venv/bin/python -m app.cli seed
backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3100
```

Migrations create/update schema; do not replace them with `create_all` or rewrite old migrations.
Seeds are fictional and idempotent. Keep the same database URL and process working directory
for CLI and API operations. PostgreSQL configuration exists but has not been validated here.

## Request and state flow

1. `POST /demo/bootstrap` creates a new fictional learner. `pair --learner ada` issues a
   one-time code for an existing local learner; `POST /pairing/redeem` exchanges it for a
   credential. The API stores credential hashes and derives scope from the bearer token.
2. `POST /sessions` starts a session. `GET /sessions/{id}/state` supplies the current revision.
3. `POST /sessions/{id}/check-in`, `/work`, and `/help` require `expected_revision` and an
   `Idempotency-Key`. Retries reuse the same key and body; changed content under that key is
   a conflict. Foreign records do not expose another learner's history.
4. `app.tutor.coordinator.execute_turn` reserves a turn, builds bounded context and policy,
   infers outside the transaction, validates, and rechecks scope/revision/cancellation before
   committing. A failed provider does not silently switch to a different provider.
5. Claude brought-question intake uses `CheckInRequest.question_text` and the dedicated
   brought-question path. Later typed work continues the stored question. Not every kind of
   turn uses an identical context builder or token budget.
6. `GET /sessions/{id}/events` is polling, not client SSE. Scene operations have a separate
   monotonic scene revision and operation ID; student history and grouped partner-mark undo
   preserve authorship. Unconfirmed ink is not automatically graded as handwriting.
7. Memory routes expose sources, uncertainty, correction, and removal. The graph and BKT
   estimates are evidence-derived context, not calibrated claims about a learner's ability.

Routes above are unprefixed for standalone FastAPI. The Chalk demo mounts them under `/api`.
`GET /health` checks liveness; `/health/model` inspects configuration without a provider call.

## Local administration and offline checks

The CLI uses direct local database access; it is not a learner authentication endpoint.
Use a fresh database for experiments and tests, not a user's working database. The database
argument is a top-level option before the subcommand:

```sh
export PYTHONPATH="$PWD/backend"
backend/.venv/bin/python -m app.cli --database-url sqlite:////tmp/rubberducky-check.db migrate
backend/.venv/bin/python -m app.cli --database-url sqlite:////tmp/rubberducky-check.db seed
backend/.venv/bin/python -m app.cli --help
```

Available command families include `learners`, `pair`, `revoke`, `history`, `graph`, `memory`,
`tracing`, `interactives`, `evaluation`, and `demo`. Use each command's `--help` for supported
flags. Offline integration examples:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.cli interactives status
PYTHONPATH=backend backend/.venv/bin/python -m app.cli interactives prevetted --component grouping
PYTHONPATH=backend backend/.venv/bin/python -m app.cli evaluation run --candidate fixture:good
PYTHONPATH=backend backend/.venv/bin/python -m app.cli evaluation chalk-plan --candidate fixture:good
PYTHONPATH=backend backend/.venv/bin/python -m app.cli demo
```

`interactives status` is configuration-only. `generate --confirm-live` can contact Factory and
Daytona when configured; the flag is not a hard cost cap. The recorded live attempt failed at
Factory and never created a Daytona sandbox. The hosted service leaves both integrations off.
Chalk evaluation live runs are separate from hosting and require their own configuration.

## Modules

- `api`, `schemas`, `db`: HTTP contracts, scope, persistence, and migrations.
- `learner`, `graph`, `tracing`: identity, sourced memory, curriculum retrieval, and NumPy BKT.
- `tutor`, `pedagogy`, `verification`, `inference`: turn coordination, policy, bounded algebra
  verification, mock/local/endpoint/Claude adapters, and brought-question inference.
- `whiteboard`: validated partner tools, scene operations, and author-safe history.
- `multimodal`: bounded session/revision events and uncertain capture candidates.
- `speech`: xAI recording transcription and speech of committed partner replies.
- `interactives`: constrained Factory generation, trusted Daytona checks, and fallback specs.
- `tutoring_eval`, `demos`: fictional replay scoring, optional Chalk evaluation, and walkthroughs.
- `experiments`: offline GRU, reviewed shared-example preparation, and tiny LoRA plumbing;
  see [experiment commands and model cards](../docs/experiments.md).

## Checks and limits

```sh
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
```

The working tree changes independently of the hosted release. Earlier test totals are
historical; run applicable checks on the revision being reviewed. A fixture pass does not
verify a live service, trained-model quality, learning gains, or physical device behavior.
Raw media is not stored by default; retained submitted text/evidence is distinct from raw media.

## Watch backend and model activity live

Start the backend normally, then in another terminal from the same directory run:

```sh
tail -F data/logs/activity.jsonl
```

The file is created on the first HTTP request. Each JSON line has a UTC timestamp,
request ID, and event name. `http.started` / `http.completed` show incoming traffic,
route templates, HTTP status, and elapsed milliseconds. `provider.request` shows the
Claude or endpoint model, attempt, and request size; `provider.delta` shows streaming
progress as character counts; response events include token counts when available.
Retries and failures are recorded too. Claude image/board-reading calls use
`operation: complete_blocks`. These events show provider activity, not hidden model reasoning.
The `X-Request-ID` response header matches the file so you can trace a browser request.

Files rotate at 5 MB, retaining three backups. The default path is relative to the
backend process working directory, and `data/` is gitignored. Set
`TUTOR_ACTIVITY_LOG_PATH=/absolute/path/activity.jsonl` to choose another location,
or set it to an empty string to disable logging. Use one file per server process
when running multiple workers. Logging records metadata only: prompts, generated text,
request bodies, headers, query strings, credentials, and media are excluded.
The log follows work handled within HTTP requests, including work propagated into
worker threads; standalone CLI jobs are not captured.
