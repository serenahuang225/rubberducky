# Offline modeling integration

The delivered experiment code is now present under `backend/experiments/`, and the causal GRU
is in `backend/app/tracing/gru.py`. The original delivery remains on
`experiments/offline-modeling`; it is no longer correct to say that all experiment work is
missing or blocked awaiting another agent's first delivery.

Use [experiment commands](../../experiments.md) and the model cards under
`docs/model-cards/`. Commands cover synthetic GRU training/evaluation, reviewed fictional
shared-example validation/preparation, and random-base LoRA training/reload/evaluation.
Checkpoints and generated artifacts are ignored local outputs, not guaranteed repository files.

These are offline pipeline checks, not production models. The deployed demo uses scripted
responses or Claude; it does not use the experimental GRU or a trained LoRA thinking partner.
Synthetic losses and random-base adapter changes do not establish calibrated knowledge,
better tutoring, or learning gains. Historical model-card metrics are not fresh test results.

Remaining work is reproducibility and review of the delivered code/results, privacy/license
checks for any new data, and explicit evaluation before proposing runtime integration. Do not
start duplicate training, pretrained downloads, or paid teacher generation as part of a docs
or integration review.
