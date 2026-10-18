# Current handoff

Updated 18 October 2026. This replaces the interrupted-worker snapshot from `904d965`.
Use the [root README](../../README.md) for setup and current features and the
[Chalk deployment guide](../../deploy/chalk/README.md) for the live demo.

## Shipped in the hosted demo

- Public scripted exploration and passcode-protected Claude on one Chalk URL.
- Dedicated server-side secrets, a password gate, and request-rate limits.
- Separate preview/Claude databases and browser credential slots; protected history is
  checkpointed to a Chalk volume. Preview history is disposable.
- Selected partner names in chat, a quiet-hint countdown/bar, and selected-tool circles.

The latest UI releases used an isolated snapshot. Active edits in this checkout are not
necessarily deployed. Do not overwrite or stage unrelated changes.

## Remaining work

- [Photon](photon-messaging/README.md): Beta code is on separate branches; no live messaging
  delivery is verified. This checkout still contains the Stable Spectrum bridge.
- [Voice](livekit-voice/README.md): distinguish implemented xAI recording support from the
  unfinished LiveKit/Deepgram/Photon calling feature. Neither is enabled on the demo.
- [Factory/Daytona](interactive-wiring/README.md): diagnose the failed live Factory generation;
  no Daytona sandbox was created. Learner-explanation wiring remains on separate branches.
- [Modeling](modeling-integration/README.md): experiment code is now in the repository;
  do not rebuild it or claim synthetic/random-base results are teaching improvements.
- [Media/device checks](media-validation/README.md): complete target-specific visible/device
  verification rather than treating fixtures or exported bundles as hardware evidence.
- [Delivery](delivery-and-acceptance/README.md): review active changes, fix remaining gates,
  and distinguish current source, branches, deployed releases, and historical test results.
- [Ownership](working-tree/README.md): inspect current changes before editing or splitting work.

Old mission assertion counts and worker queue states are not a current completion ledger.
No formal acceptance assertions were re-certified by this documentation update. Existing user
instructions still govern browser/service actions; old blanket prohibitions must not be used
to deny work the user has since explicitly authorized. Credentials being present are not an
instruction to activate another integration.
