# Shared web and iPad client

Expo 57, React Native 0.86, React 19, and TypeScript. The same component code targets React
Native Web and Expo Go. The [root README](../README.md) describes the product and current
integration status; the [deployment guide](../deploy/chalk/README.md) covers the hosted build.

## Run locally

Use Node **22** and the project-local Expo CLI. From the repository root:

```sh
npm --prefix frontend ci
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:3100 npm --prefix frontend run web
```

The web development server uses port 3101. Start the backend separately as described in the
[backend guide](../backend/README.md). Coordinate existing listeners rather than stopping an
unrelated service. Do not put keys or learner bearer credentials in `EXPO_PUBLIC_*` variables.

`src/config/apiBaseUrl.ts` uses an explicit `EXPO_PUBLIC_API_BASE_URL` when supplied. Otherwise,
web falls back to `http://127.0.0.1:3100`, and native uses the Expo bundle host on port 3100.
For the combined Chalk deployment, build with `/api` and clear Metro's cache:

```sh
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_BASE_URL=/api npm --prefix frontend run build:web -- --clear
```

`frontend/dist` is generated output, not source. API selection is compiled into the web
bundle; changing server variables does not rewrite an already exported bundle.

For an iPad on a trusted private network, start the API on an appropriate LAN interface and
use `EXPO_NO_DOTENV=1 npm --prefix frontend start`. That starts Expo on port 8081. The iPad
must be able to reach the Mac's API. Native device permissions, Pencil/palm behavior, and
backgrounding require actual iPad checks; web exports do not establish native compatibility.

## Hosted demo and learner flow

The [demo entry page](https://srnb0d1efa84-rubberducky-demo.mdwje5.svls.customers.gcp.chalk.ai/demo-login)
offers scripted exploration without a passcode and protected Claude for your own questions.
The deployment wrapper selects isolated backends for those modes; it does not expose Claude
by trusting a client-side model toggle. A link on the page returns to the demo options.

`App.tsx` loads a stored scoped credential, onboards a learner, and starts/resumes a session.
The thinking partners are Vincent, Zeeshan, Tony, Janelle, and Mary. The shared board and chat
use the same committed turn. Partner replies display the selected name instead of “Tutor”.

- `WorkspaceScreen` composes the board, chat, intake, controls, and session state.
- `ToolRail` shades a circle behind the selected pen or eraser in the vertical toolbar.
  Undo/redo are actions, not selected drawing modes.
- `WaitControls` displays a thin progress bar and time remaining until a quiet hint offer.
  The countdown comes from `quiet_hint_at - now` returned by the server. It does not infer
  ability from silence or automatically submit a request when the timer expires.
- `useWaitAgency` refreshes timing on real activity and “Still thinking”. `useWorkspace`
  guards session generations, cancellation, revisions, retries, and work submissions.
- Settings includes fictional integration walkthroughs; they do not start Factory/Daytona.
- Memory provides the learner knowledge map and source-linked inspection/correction/removal.

The client polls committed turns; it is not an SSE client. Finished strokes use stable
operation IDs, a scene cache, and an outbox so an uncertain acknowledgement does not duplicate
work. Unsaved strokes remain visibly unsaved. Offline history edits are refused rather than
blindly queued. A full reload of an unsubmitted text draft is not part of stroke durability.

## Media and accessibility

Capture starts only after a learner action and device permission. Browser speech recognition,
recorded xAI hold-to-talk, photo intake through Claude, and labeled simulated media are
separate capabilities. A microphone without transcription must not be labeled “listening”.
Check reported server/browser capabilities rather than assuming every target supports them.
The hosted demo does not enable xAI voice or LiveKit calls.

Platform drivers are lazy-loaded. Session/generation guards ignore obsolete callbacks after
stop, interruption, navigation, or a new turn. Text-only, reduced-motion, sound, captions,
and haptics settings must affect the actual media behavior. Source evidence and deletion
controls are separate from clearing browser storage.

Web storage includes `rubberducky.credentials.v1`, per-session outbox and scene-cache keys.
The hosted wrapper keeps credential slots for Claude and scripted mode. It does not migrate
learner histories between those databases. Never export a stored learner token in diagnostics.

## Commands and verification

```sh
npm --prefix frontend test -- --runInBand
npm --prefix frontend run typecheck
npm --prefix frontend run lint
EXPO_NO_DOTENV=1 npm --prefix frontend run build:web
npm --prefix frontend run check:expo
```

`check:expo` checks SDK dependency compatibility; it is not a full native-device test.
The focused waiting/chat tests passed (9 tests) for the countdown/name change. The isolated
release web builds succeeded, including the selected-tool circle. The full checkout's
TypeScript check reported an unresolved `global` in `WorkspaceScreenMedia.test.tsx`; no
whole-tree clean check or physical iPad pass is claimed. Unrelated active edits were excluded
from the latest hosted UI release using an isolated source snapshot.
