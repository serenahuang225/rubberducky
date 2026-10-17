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
the only tested database.

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
