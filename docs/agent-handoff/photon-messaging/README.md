# Photon messaging

## Current state

The primary checkout's `integrations/photon/package.json` depends on Stable
`@spectrum-ts/core` and `@spectrum-ts/imessage` 12.11.0. It uses `SPECTRUM_PROJECT_ID`,
`SPECTRUM_PROJECT_SECRET`, and the explicit `PHOTON_MESSAGING_ENABLED` flag.

The user chose **Photon Beta**. Beta code using `@photon-ai/api` 0.5.0 is on
`pr/photon-beta` and `pr/photon-on-master`, with matching prepared worktrees. Its credentials
are `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`, `PHOTON_AGENT_HANDLE`, and `PHOTON_TEST_SENDER`.
The Beta host is `https://api.photon.codes`; do not point Stable Spectrum packages at Beta
credentials. Consult https://photon.codes/docs/beta when implementing against that API.

No live Beta connection, real send, or end-to-end provider retry behavior is verified.
Photon is not part of the hosted Chalk demo. The prior read-only worker's queue status is no
longer useful implementation status.

## Continuity boundary

Pair a channel using its own one-time code and scoped learner credential. A phone number or
provider sender ID never selects a learner. Follow-ups must use the learner's active session,
current revision, and a stable idempotency key for an unchanged logical body. Shared Python
history, policy, and knowledge-graph context belong to the existing `execute_turn` path.
The bridge does not create a second authoritative transcript. Messaging and future calling
must use separate credentials and independently revoke their bindings on opt-out.

## Next work

Review and integrate the Beta branch, check its actual HTTP/request contracts against the
current API, test replay/body conflicts and outbound failure, then verify an explicitly
approved sender/recipient. The current demo password gate requires a deliberate service-to-
service access design; do not embed its browser passcode or a Chalk token in client code.
Do not install a local Messages provider or read a personal Messages database as a fallback.
