# Rubberducky

Rubberducky is a math thinking partner with a shared whiteboard, conversation, and
learner-specific evidence, memory, and concept graph. The client is an Expo React Native app
for web and iPad; the backend is FastAPI with SQLite. Choose Vincent, Zeeshan, Tony, Janelle,
or Mary as your thinking partner. Their name appears beside their chat replies.

## Try the hosted demo

[Open Rubberducky](https://srnb0d1efa84-rubberducky-demo.mdwje5.svls.customers.gcp.chalk.ai/demo-login).

- **Try the scripted demo** needs no passcode. It uses the deterministic mock, a separate
  temporary database, and no paid provider. Its history resets when the container is replaced.
- **Unlock Claude** uses the demo passcode and supports bringing your own question. Its
  learner history is checkpointed to a dedicated Chalk volume.
- **Demo options** lets you switch modes. Browser credentials are kept separately for each.

Both the web export and API run on the Chalk `rubberducky-demo` Scaling Group. Vercel is not
used. API requests on this deployment use `/api`; the same routes on the standalone backend
have no `/api` prefix. See [deployment and operations](deploy/chalk/README.md).

The demo passcode is in the local, ignored `.env.demo-access` file. Never commit that file,
provider keys, pairing codes, or learner tokens. Use fictional learner information in the demo.

## What is implemented

- Brought questions through Claude: typed text, text files, and supported photo/screenshot
  intake. Follow-up work continues the active session with its stored question and context.
- A scripted algebra practice flow that works without a model or API key.
- A shared whiteboard with student pen/eraser, undo/redo, and separate undo for partner marks.
  The selected pen or eraser has a shaded circle in the vertical toolbar.
- Server-owned scene revisions, learner scope, idempotent turns, and a durable client stroke
  outbox. Raw ink is not automatically treated as verified mathematical work.
- A quiet hint countdown and progress bar using the server's timestamps. At the deadline it
  offers a hint using the thinking partner's name; it does not send a paid request or speak
  automatically. “Still thinking” can extend the waiting period.
- Source-linked memory inspection/correction/deletion, a curriculum and learner knowledge
  map, bounded context retrieval, and a NumPy BKT baseline.
- Teaching-style and accessibility preferences, interruption/cancellation, and optional
  device media controls.
- Offline fictional walkthroughs of Chalk, Factory Droid, and Daytona, available in Settings.
- Offline GRU, reviewed shared-example preparation, and random-base LoRA experiments.

Implementation and the hosted release are distinct: the working tree also contains ongoing
whiteboard, typography, and UI changes. The last UI releases were built from an isolated source
snapshot plus the partner-name, countdown, and selected-tool changes; uncommitted work is not
implicitly deployed.

## Integration status

**Claude:** a protected own-question turn was verified on the hosted demo. The server-side key
is injected from a Chalk secret. The scripted option never routes requests to that Claude app.

**Factory Droid and Daytona:** generation/check adapters and trusted release gates exist. The
one live attempt on 18 October 2026 returned `generation_failed` and used the labeled pre-vetted
fallback. Daytona was not reached and no sandbox was created. They are disabled on the hosted
demo. Offline learner-explanation wiring exists in `agent/interactive-wiring` and
`pr/learner-explanations`; it is not mounted in this checkout's learner UI.

**Photon:** this checkout's `integrations/photon` still uses Stable Spectrum packages. Beta
work using `@photon-ai/api` is on `pr/photon-beta` and `pr/photon-on-master`. Neither a live
Beta connection nor real-message delivery is verified, and Photon is not deployed with the
demo. See [Photon handoff](docs/agent-handoff/photon-messaging/README.md).

**Voice:** xAI hold-to-talk code is present but disabled on the hosted demo. LiveKit/Deepgram/
Photon calling is a separate, unfinished integration. Do not describe the demo as live voice chat.

**Chalk:** hosts the demo and also has a separate optional tutoring-evaluation adapter.
Scoring fictional replay cases does not train a model or establish improved learning.

## Repository map

- [Backend guide](backend/README.md): API, configuration, database, commands, and checks.
- [Frontend guide](frontend/README.md): app flow, web/iPad development, timing, and media.
- [Deployment guide](deploy/chalk/README.md): Chalk service, secrets, persistence, and shutdown.
- [Experiments](docs/experiments.md): reproducible offline commands and historical smoke results.
- [Remaining work](docs/agent-handoff/README.md): integration gaps and verification boundaries.
- [Product scope](project_description.md): intended experience and architectural boundaries.
- `AGENTS.md` and `.agents/`: Chalk development guidance and skills; not runtime app code.

## Local setup

Use Python **3.12** and Node **22**. Run these commands from the repository root:

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
npm --prefix frontend ci
```

`backend/requirements.lock` targets macOS arm64/CPython 3.12. On another platform use the
pinned `backend/requirements.in` or generate a platform-specific lock. Model-training
packages are large; installation does not download pretrained weights. The root Python
project and `.venv` belong to the separate Chalk scaffold; do not mix them with `backend/.venv`.

The backend reads process variables. To opt into a private file, set `TUTOR_ENV_FILE` to its
absolute path. It never automatically reads the repository-root `.env`. See `.env.example`.
Do not place secrets in `EXPO_PUBLIC_*`; those values are compiled into the client.

For local Claude, set these privately:

```dotenv
TUTOR_PROVIDER=claude
EXTERNAL_INTEGRATIONS_ENABLED=true
ANTHROPIC_API_KEY=<your key>
ANTHROPIC_MODEL=<model available to your key>
ANTHROPIC_WORKSPACE_ID=<workspace id when required by your key>
```

For scripted local practice, use `TUTOR_PROVIDER=mock` and leave external integrations off.
Other optional providers are `endpoint` and `transformers`; local model loading and downloads
require their own flags. Keys alone do not enable providers.

Initialize a local database and start the API:

```sh
export PYTHONPATH="$PWD/backend"
export TUTOR_ENV_FILE="$PWD/.env.local"
backend/.venv/bin/python -m app.cli migrate
backend/.venv/bin/python -m app.cli seed
backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3100
```

In another terminal, from the repository root:

```sh
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:3100 npm --prefix frontend run web
```

Web uses port **3101** and the API uses **3100**. Coordinate occupied ports; do not stop an
unrelated process. A developer's local `.env.local` is not automatically copied into Chalk.

## Learner identity and continuity

`POST /demo/bootstrap` creates a new fictional learner and returns its credential once; it
does not attach existing history. Pair to an existing local learner with:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.cli pair --learner ada
```

Redeem the short-lived code once with `POST /pairing/redeem`. Later API requests send the
resulting bearer credential. The server derives learner scope from it; a phone number, caller
ID, or user-supplied record ID is not authentication. Pairing CLI and API must use the same
database. Local pairing does not issue a credential for the hosted database.

`execute_turn` reserves, infers, validates, and commits a scoped turn. Clients use the active
session's `expected_revision` and reuse the same idempotency key only for the same logical
request/body. The backend loads its stored question, bounded history, graph, and evidence;
clients do not maintain a separate authoritative transcript. Details are in the backend guide.

## Verification

From the repository root:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
npm --prefix frontend test -- --runInBand
npm --prefix frontend run typecheck
npm --prefix frontend run lint
EXPO_NO_DOTENV=1 npm --prefix frontend run build:web
npm --prefix frontend run check:expo
backend/.venv/bin/python -m pytest deploy/chalk/test_access.py -q
```

Use the backend mypy configuration; the root configuration is for Chalk. These are commands
to run, not a claim that every current gate passes. On 18 October 2026, the focused waiting/
chat checks passed (9 tests), the gate checks passed (3 tests), and the isolated release web
build succeeded. A full frontend typecheck reported an unresolved `global` reference in
`WorkspaceScreenMedia.test.tsx`. The earlier 65-test backend health/turn run predates subsequent
working-tree edits. No new full-suite or physical iPad pass is claimed by this documentation.

Live checks confirmed the two entry options, a scripted turn, protected Claude configuration,
a committed own-question Claude turn before subsequent UI releases, and delivery of the latest
UI bundles. API/build evidence does not establish physical iPad/Pencil behavior or learning gains.
