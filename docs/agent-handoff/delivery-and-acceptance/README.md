# Delivery and acceptance

## Current delivery

The demo is hosted on Chalk with public scripted practice and passcode-protected Claude.
See the [deployment guide](../../../deploy/chalk/README.md) for its service, secrets, data
volume, snapshot semantics, and stop/redeploy procedure. The released UI includes partner
names, the quiet-hint countdown/bar, and the selected-tool circle.

Active source edits, prepared PR branches, and the hosted release are different inventories.
Recent UI changes were published from an isolated snapshot to avoid deploying unrelated
work. Several deployment files and active code changes remain uncommitted; inspect Git
before describing a release as reproducible from a pushed commit. Pushed slice branches
are not proof that GitHub pull requests were opened or merged.

## Evidence and outstanding checks

The session recorded a protected Claude own-question turn, free scripted turns, password
and credential-isolation checks, server hint timing, and successful release web builds.
Focused waiting/chat tests passed (9), and gate tests passed (3). The whole-checkout frontend
typecheck reported an unresolved `global` in `WorkspaceScreenMedia.test.tsx`; earlier backend
and other test totals predate subsequent edits. Re-run applicable gates on reviewed source.

Remaining verification includes current whole-tree gates, visual/accessibility review,
physical iPad/permission/Pencil tests, failed Factory diagnostics, actual Daytona execution,
and Beta messaging/calling integration. No formal mission assertion counters were updated.
No learning gains, calibrated mastery, real-message delivery, or trained production model
are established by the recorded checks.

For future PRs, inspect ownership/current diffs, preserve a recoverable snapshot, propose
reviewer-aligned slices, and stage only named files/hunks. Use actual PR URLs and attach
created PRs; do not present compare links as opened pull requests.
