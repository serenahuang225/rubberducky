# GRU synthetic smoke model card

Historical offline smoke-run record. Checkpoints are ignored local artifacts and may need
regeneration. These measurements were not rerun for the current documentation update, and
this model is not used by the hosted demo.

This artifact is a **synthetic** execution check of a causal GRU on generated interactions.
It is **not calibrated mastery** and it is not evidence that a learner improved. Do not read a
lower log loss than BKT as an educational result. On this run the GRU log loss is lower and the
BKT AUROC is higher.

## Data and split

- Seed: `17`.
- Train learners: `learner.train.0`, `learner.train.1`, `learner.train.2`, `learner.train.3`.
- Held-out learners: `learner.heldout.0`, `learner.heldout.1`.
- Learners were split before sequence windows were built.
- Eligibility: `bkt-eligibility.v1`. Twelve held-out target IDs match BKT exactly.
- `obs.ineligible` and `obs.duplicate` are not targets.
- Graph-feature ablation on this checkpoint: off. A separate one-epoch `--graph-features` command
  also ran; it is not evidence that the summary helps.
- Provenance: seeded synthetic events in `experiments.tracing.synthetic`. Not student data.

## Configuration

- Algorithm: `gru-causal.v1`. Embed 8, hidden 8, one GRU layer, no bidirection.
- Epochs: 2. Adam learning rate 0.05.
- Numerical threads: 2.
- Checkpoint (local, not committed): `artifacts/gru-smoke/` (`model.pt`, `config.json`,
  `vocabulary.json`, `run.json`, `metrics.json`).
- Reload tolerance: 1e-5. Measured max absolute probability difference: 0.0.

## Metrics

Held-out count 12. Both outcome classes are present, so AUROC is defined.

| Model | Log loss | Brier | AUROC |
| --- | --- | --- | --- |
| GRU | 0.6283835614226976 | 0.21919086170568333 | 0.625 |
| BKT (`bkt-handset.v1`, uncalibrated) | 0.6446029065960897 | 0.22623767596465286 | 0.875 |

GRU calibration counts in bins `[0,0.2)`, `[0.2,0.4)`, `[0.4,0.6)`, `[0.6,0.8)`, `[0.8,1]`:
0, 0, 2, 10, 0. BKT counts: 0, 8, 4, 0, 0.

Epoch losses: 0.7365320324897766, 0.6152557730674744. Parameter L1 change: 55.052391335368156.

## Resources

Measured on this Mac, one process, CPU only.

- Training section inside the process: 0.6367659170064144 s.
- Shell wall clock for the train command: 1.70 s real, 1.48 s user, 0.20 s system.
- `ru_maxrss`: 308117504 bytes. On macOS that figure is bytes and includes the PyTorch runtime,
  not the GRU alone.
- Evaluate command wall clock: 0.93 s real. Exit 0.

## Limitations

- Generated labels, a tiny network and two CPU epochs.
- Hand-set BKT parameters are uncalibrated. The GRU probability is not a latent skill.
- No student recordings, public dataset or pretrained language model was used.
