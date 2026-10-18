# Factory Droid and Daytona

## What exists

`backend/app/interactives/` implements constrained Factory generation, repository-owned
checks, Daytona checks, cleanup accounting, and a labeled pre-vetted fallback. The frontend
has a bounded native `ExplanationManipulative` renderer. Settings also exposes fictional
integration walkthroughs; those walkthroughs do not call either service.

Offline learner-explanation routing/mounting was prepared in `agent/interactive-wiring`
and `pr/learner-explanations`. It is not present in this checkout's `TeachingContext` or
mounted on the hosted learner path. Review those branches before implementing overlapping work.

## Live result

The user authorized one live test using `.env.local` on 18 October 2026. Configuration was
present, but generation returned `generation_failed` and the labeled pre-vetted fallback.
Daytona was never reached: no sandbox was created or deleted. The underlying Factory error
was not exposed by the public release result. Both integrations remain off on the hosted demo.

## Configuration and next steps

Factory needs an installed/authenticated Droid CLI, `FACTORY_DROID_EXECUTABLE` set to its
absolute path, `FACTORY_MODEL`, and an applicable account key/login. Find the path with
`command -v droid`. Daytona needs `DAYTONA_API_KEY` and a valid `DAYTONA_API_URL`.
`EXTERNAL_INTEGRATIONS_ENABLED`, `FACTORY_INTERACTIVES_ENABLED`, and
`DAYTONA_CHECKS_ENABLED` are separate activation flags.

`python -m app.cli interactives status` checks configuration without contacting services.
`interactives generate --confirm-live` can incur usage charges; it is not a hard cost cap.
Before another paid attempt, expose a sanitized generation diagnostic and fix its cause.
Then validate candidate contracts, trusted checks, and exact sandbox cleanup. No completed
live-generation or sandbox-validation claim is supported by the failed attempt.
