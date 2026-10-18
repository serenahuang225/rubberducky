# Working-tree coordination

Inspect `git status --short --branch`, relevant diffs, branch/worktree history, and ownership
signals before editing. Several backend and frontend files contain active user/other-worker
changes. Do not reset, stash, overwrite, stage, or commit those changes incidentally.

Current known work areas include question intake/coordination, whiteboard layout and reading,
chat/workspace controls, typography, and the uncommitted Chalk deployment files. This list is
context, not a substitute for a fresh status check.

Prepared worktrees/branches include Photon Beta, offline learner explanations, and the
experiment delivery. Reuse/review them before duplicating implementations. Branch names and
old queue labels do not prove work is running, merged, deployed, or formally accepted.

The hosted demo is a separate Chalk service and data volume. Local learner credentials and
databases do not automatically map to it. Recent UI releases were built in an isolated
snapshot; editing the checkout does not change the live site until a reviewed export/deploy.

The user explicitly authorized the Chalk deployment, Claude secret transfer, and protected
live Claude verification in this session. Historical blanket “no .env.local/deployment” notes
must not be treated as overriding that authorization. Keep values private, limit secret reads
to the authorized purpose, and do not activate additional integrations implicitly.

Coordinate local services and data with their owners. Do not reuse stale PID-stop permissions,
kill by port/name, assume browser verification has happened, or create duplicate dependency
trees without a need. Backend Python and the root Chalk environment remain separate.
