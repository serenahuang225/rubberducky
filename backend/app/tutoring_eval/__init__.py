"""History-grounded tutoring evaluation: replay snapshots, a deterministic rubric and an
optional explicit Chalk Compute adapter.

Nothing in this package starts a network call, deploys or uploads anything at import. The
Chalk SDK is imported only inside explicit adapter calls, and ``chalk_functions`` /
``chalk_judge`` (whose decorators deploy when imported) are imported only by the explicit
``evaluation chalk-run --confirm-live`` command.
"""
