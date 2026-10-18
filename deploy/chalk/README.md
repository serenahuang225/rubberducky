# Chalk demo deployment

[Open the demo options](https://srnb0d1efa84-rubberducky-demo.mdwje5.svls.customers.gcp.chalk.ai/demo-login).

The `rubberducky-demo` Chalk Scaling Group serves the Expo web export and FastAPI together.
The browser uses `/api`, so this release needs neither Vercel nor a separate frontend domain.
Deployment files are local source in this directory; the hosting service is already running.

## Two entry options

- **Try the scripted demo:** no passcode. A cookie selects a separate mock app and temporary
  SQLite database. It has no Claude/xAI key in its app settings and cannot resolve credentials
  issued by the protected app. Preview history resets when the container is replaced.
- **Unlock Claude:** passcode sign-in selects the Claude app. Its learner database is restored
  and checkpointed using the `rubberducky-demo-data` volume.

The page's demo-options link switches modes. The wrapper saves browser credential slots per
mode, so changing modes does not reuse a credential against the other database. The hosted
release includes named partner chat labels, the quiet-hint countdown/bar, and the shaded
selected-tool circle. Other working-tree UI/backend changes are not automatically deployed.

## Secrets and access

Chalk secrets are injected by reference:

- `RUBBERDUCKY_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY`.
- `RUBBERDUCKY_DEMO_ACCESS_PASSWORD` → `DEMO_ACCESS_PASSWORD`.

The operator's ignored `.env.local` supplies `ANTHROPIC_MODEL` and, when needed,
`ANTHROPIC_WORKSPACE_ID` to the deploy script. It must also contain the API-key setting for
its configuration check, but the runtime key comes from the Chalk secret. The script does
**not** automatically upload or rotate secrets. Keep them synchronized when rotating a key.
No `.env` file, local learner database, or access-password file is uploaded into the image.

The existing passcode is stored locally in the ignored, owner-only `.env.demo-access` file.
Do not print it in logs or commit it. For a new installation, generate a strong passcode of
at least 20 characters and store it in the local file and the named Chalk secret. Use a
secret-input interface or pipe to `chalk secret set NAME`; never put secret values in command
arguments. Update the Chalk password secret and redeploy to invalidate existing sign-ins.

Claude access uses a Secure, HttpOnly, SameSite=Strict cookie valid for 12 hours. The server
limits login POSTs to 20 per minute and protected tutoring POSTs to 10 per minute across the
service. These in-process windows reset on restart and are request limits, not a dollar cap.
The health endpoint is public; scripted requests route exclusively to the mock application.
Factory, Daytona, LiveKit, and xAI speech remain disabled. Use fictional learner information.

## Build and deploy

Use a reviewed source snapshot and a clean web export. The deploy script uploads backend
source/migrations, the exported web files, and the wrapper files; it does not commit or push.
The local Python running it needs `chalkcompute` and authenticated Chalk deployment access.
The deployed image excludes the large local training/model packages.

From the repository root:

```sh
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_BASE_URL=/api npm --prefix frontend run build:web -- --clear
# First installation only; reuse the existing volume for redeployments:
chalk volume create chalk://rubberducky-demo-data
backend/.venv/bin/python deploy/chalk/deploy.py
```

Do not run `volume create` again for an existing installation. Provision the two named secrets
before the first deployment. The API database is migrated and seeded idempotently at startup.

`DEMO_SOURCE_ROOT=/absolute/path/to/reviewed-snapshot` makes the deploy script take backend
source and `frontend/dist` from that snapshot. Wrapper scripts and local operator settings
still come from this repository. This option was used for the recent UI releases to avoid
publishing unrelated working-tree changes. Build that snapshot's web export first.

**Before replacing an existing service, stop it** so two revisions cannot write competing
SQLite checkpoints. The current operational flow deletes the exact existing demo service and
then recreates `rubberducky-demo`; this causes a brief outage. Retain its data volume and
secrets. Confirm the exact service before deletion and do not touch evaluation services.

## Persistence and cost

The service uses one 500m CPU / 1Gi replica and one Uvicorn worker. It stays running and incurs
Chalk hosting charges; protected Claude requests also incur provider usage charges.

SQLite runs on local disk. The protected app serializes mutating requests, copies the database
with SQLite's backup API to the data volume, and executes the volume commit control file
before returning a normal mutation response. A crash before commit may lose an unacknowledged
request. Only the protected database is checkpointed; the preview database is disposable.
Do not add replicas or overlapping revisions. For production concurrency, use a tested
managed-database design rather than treating these snapshots as a multi-writer database.

To stop hosting without deleting stored learner data:

```sh
chalk scaling-group delete --name rubberducky-demo
```

This retains the separately managed volume and secrets. Do not delete the volume unless its
data is no longer needed.

## Verification and recovery

```sh
backend/.venv/bin/python -m pytest deploy/chalk/test_access.py -q
backend/.venv/bin/python deploy/chalk/smoke.py https://srnb0d1efa84-rubberducky-demo.mdwje5.svls.customers.gcp.chalk.ai
```

The smoke command reads the local access-password file, creates a fictional learner/session,
and makes one **billable Claude own-question request**. It is not an offline health check.
Never use its result to claim a fresh full backend/frontend test pass.

During this session, live checks verified blocked anonymous Claude access, passcode sign-in,
a committed Claude own-question turn, free scripted practice, isolation between learner
credentials, server hint timing, and delivery of the released UI bundles. Browser appearance
and actual iPad/Pencil behavior still need separate checks. See the root README for known
whole-tree typecheck limitations.
