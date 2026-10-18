# Shared Expo iPad and web client

Expo57 / React Native0.86 / React19 / TypeScript. The same native components render in
Expo Go and React Native Web. Read the [handoff index](../docs/agent-handoff/README.md)
and [working-tree rules](../docs/agent-handoff/working-tree/README.md) first.
**Browser work is user-paused.** No commands below run as part of this documentation request.
A later bounded implementation assignment normally includes appropriate local tests/research/
setup within agreed scope; it does not lift the browser pause or permit starting/adopting
protected3100/3101/8081 services.

## Toolchain and setup

Node **22** (`>=22 <23`), not the host's unsupported newer default. Use an already-installed
Node22 on PATH; do not change global tools. Local readiness used
`/private/tmp/rubberducky-readiness/node-runtime/node_modules/.bin`, but portable setup must
not depend on it. In a new authorized checkout:

```sh
cd /Users/huangrh/workspace/rubberducky
npm --prefix frontend ci
```

Use the committed `package-lock.json`, project-local Expo CLI, and SDK-matched packages.
Do not copy `node_modules` to another worktree or run legacy global Expo/RN CLIs. Large
installs beyond agreed setup scope require approval; resource and standing download restrictions
still apply. No installs/downloads were run for this handoff.
Expo Go is the approved native route. Local Xcode26.2 is below Expo57's26.4 native compilation
requirement; SDK compatibility is not a standalone native-build pass. Actual iPad/OS/Go and
Pencil/palm behavior require user participation.

Always run Expo with `frontend/` as project root and `EXPO_NO_DOTENV=1`. Do not load root
dotenv or put secrets into `EXPO_PUBLIC_*`.

## API selection, database and service safety

[apiBaseUrl](src/config/apiBaseUrl.ts) uses `EXPO_PUBLIC_API_BASE_URL` when supplied;
otherwise web uses `http://127.0.0.1:3100`, native derives the Mac bundle host on3100.
**The fallback is unsafe for agent testing against the user's API.** Future mission web
must explicitly set `EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:3102`.
The public API address is not a secret. Bearer/provider credentials are.

The frontend does not select the backend database. Agent CLI/pairing and API3102 must all
use the fixed separate mission runtime `test-api-3102.db`; never default `data/tutor.db`.
See the [backend guide](../backend/README.md) for fresh non-server CLI checks.

After explicit browser resumption and owner coordination ONLY:

1. Reconcile3101 ownership. One-time PID27683 stop permission is consumed; later unowned
   listeners are not covered. Do not stop the user API3100 or Expo8081, choose3103, or expose a
   public tunnel.
2. Use authoritative mission `services.yaml`: `test_api`3102, then `web`3101 with explicit
   override, clean mock/disabled backend and recorded owned identities. Derived
   `start-test-api`/`stop-test-api`/`start-web`/`stop-web` scripts must match the YAML.
   Do not run legacy extractor/API3100 harnesses.
3. Metro uses CI=1 in the manifest and does not watch edits. If code changed, restart **only
   owned** web with the exact permitted `--clear` variant before judging new UI.
4. Stop only owned exact recorded PIDs with birth/UID/command/cwd checks; reverse dependency
   order. Never kill by port/name or close Factory's browser.

The package's `web` and `start` scripts are **manual developer** shortcuts on3101 and8081,
not current mission startup authorization.

## Actual scripts and future checks

Run from the repository root with Node22:

```sh
cd /Users/huangrh/workspace/rubberducky
npm --prefix frontend test -- --runInBand
npm --prefix frontend run typecheck
npm --prefix frontend run lint
EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 npm --prefix frontend run build:web
EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 npm --prefix frontend run check:expo
```

| Script | Actual command / meaning |
| --- | --- |
| `start` | `expo start --lan --port 8081`; manual trusted-LAN Go route only |
| `web` | `expo start --web --localhost --port 3101`; manual shortcut, no safe-backend override built in |
| `test` | Jest; add `--runInBand` for resource bounds |
| `typecheck` | `tsc --noEmit`; capture its actual exit |
| `lint` | ESLint whole frontend, zero warnings |
| `build:web` | Expo web export to `dist`, max-workers1; not deployment |
| `check:expo` | `expo install --check`; SDK compatibility, not full Expo Doctor/native proof |

Focused example after assignment:
`npm --prefix frontend test -- --runInBand src/interactives/ExplanationManipulative.test.tsx`.
Do not claim old results apply to dirty UI. Historical461 tests passed at `1a9ade2`;
then tsc exited2 on WaitControls `absoluteFillObject`. That file/UI has since changed.
This handoff did not rerun or diagnose the current compiler. Historical build/Expo results
also are not fresh gates.

## Module map and learner flow

| Path | Responsibility |
| --- | --- |
| [App.tsx](App.tsx) | Load credential, authenticate, onboard or resume/start session; memoized client; Settings/Memory cover rather than unmount workspace |
| [screens](src/screens/) | Onboarding, workspace, settings, private memory/source correction/removal, service status |
| [api](src/api/) | Typed contracts/client, operation IDs and scene resync |
| [state](src/state/) | Workspace generation guards/retry logical commands; waiting, preferences, memory effects, progressive reveals/avatar state |
| [components](src/components/) | Whiteboard/input layers, native SVG scene, controls, prompt/avatar/media; externally dirty new TutorChat |
| [board](src/board/) | Logical1600×1200 geometry, fixed3-unit pen/palette, pointer/touch normalization, safe scene types |
| [storage](src/storage/) | AsyncStorage credentials, durable stroke outbox/cache; localStorage on web |
| [media](src/media/) | Capture/speech controllers + lazy platform drivers, uncertain candidates, scoped late-callback cancellation |
| [feedback](src/feedback/) | Reduced-motion/sound/haptics/text-only resolution; unsupported haptics no-op |
| [theme](src/theme/) | Shared current theme tokens/web integration; preserve UI-owner changes |
| [interactives](src/interactives/) | Strict bounded explanation spec parser and isolated native manipulatives, **not production-mounted** |
| [testing](src/testing/) | Labeled deterministic service/media fixtures, never live evidence |

App obtains a fictional scoped bearer credential, stores it locally, independently selects
appearance/personality, then resumes/starts a server session. Workspace uses current session/
scene revisions, check-in, typed/confirmed work and Help through the actual backend.
The current UI has a welcome/question intake and optional typing; do not assume historical
screenshots' exact layout/selectors. New TutorChat/question/Claude edits are external dirty
work, not Photon implementation or validated acceptance.

`useWorkspace` retains one logical key/body through uncertain work retries and clears only
the resolved submitted draft, not newer text. Full page reload autosave of uncommitted typed
draft/key is **not** part of the durable-scene promise. Finished strokes use durable outbox IDs;
pending marks visibly say unsaved, retry publishes authoritative scene before dropping preview.
Offline history edits are honestly refused instead of blindly queued. Server state is source
of truth; client generation plus server cancellation epoch reject obsolete responses.

The turn feed is polling `GET /sessions/{id}/events`, not client SSE. Progressive marks use
brief cancellable reveals; hiding the board displays accepted content without delayed replay.
One fixed student pen, locked author-distinct palette, author metadata, and separate grouped
tutor undo remain required. Raw ink never becomes confidently graded handwriting.

## Media, accessibility and private state

Capture panel closed/default off. Opening it may fetch capabilities, but capture requires a
start action and permission. An open mic without a transcriber says open, **not listening**.
Real STT/photo perception are unavailable; simulated sequences are labeled. Candidate text
can be edited/copied into a draft and still requires explicit work submission.
Digital strokes stay authoritative; weak context may clarify, not diagnose emotion/disability.

Drivers are loaded lazily by `defaultMediaServices.tsx`; eager expo-audio/camera/speech imports
previously broke Jest/render. `useMedia` scopes speech to session/generation/epoch/attempt
and ignores late callbacks after stop/work/problem/source/navigation/background changes.
Preferences must suppress actual speech/haptics calls, not merely change labels.

ChoiceControls explicitly expose checked state and keyboard behavior; verify actual a11y
tree/focus, not selected styles alone. Server timestamps govern seven-day persona eligibility.
Comfort/accessibility are independently editable while locked. Private memory links sources,
uncertainty and relevance, corrects/deletes with receipts, and handles session/profile removal.
Clearing browser storage is not a substitute for server-side deletion.

Web storage keys include `rubberducky.credentials.v1`, `rubberducky.outbox.v1.<sessionId>`
and `rubberducky.scene-cache.v1.<sessionId>`. Do not print/export stored tokens or adopt
another person's learner/history. Clear only an owned test learner's data when authorized.
Default raw audio/video/image bytes are not stored/logged; retained transcript metadata is
different and obeys evidence/deletion controls.

## Remaining work and verification boundaries

- [Media validation](../docs/agent-handoff/media-validation/README.md): existing media code
  retained; remaining visible journey and formal assertions paused. Recovered screenshots
  are not current API-target provenance or native-device proof.
- [Interactive wiring](../docs/agent-handoff/interactive-wiring/README.md): parse released
  payload and mount existing component through a minimal compatible learner path only after
  dirty UI ownership is resolved. No mandated new scene-kind/route.
- [Delivery](../docs/agent-handoff/delivery-and-acceptance/README.md): formal accessibility/
  agency checks, fresh gates and actual iPad checklist. Browser simulation does not establish
  Pencil/palm/OS permissions/background/native media.
- [Photon](../docs/agent-handoff/photon-messaging/README.md) and
  [voice](../docs/agent-handoff/livekit-voice/README.md) are separate gated processes sharing
  Python history/policy, not a license to rewrite this UI.

After browser resumption, use the agent-browser skill and supplied **visible** Factory pane.
Stop on hidden/zero-sized/screenshot/input blockage after a brief readiness attempt and one
ordinary retry; ask the user. DOM/a11y access continuing to work is not a bypass permission.
At most one validator, check each dependent result, calibrate current pointer scaling, preserve
accepted evidence, and never call close against the user/Factory browser.
