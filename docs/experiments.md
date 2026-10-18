# Offline modeling experiments

These commands check that a causal GRU and a tiny LoRA adapter can train, save, reload and score
held-out rows. They run on the CPU with at most two numerical threads. They do not download
pretrained weights, call a paid teacher, or use student recordings.

Checkpoints written under `artifacts/` are local and git-ignored. The numbers below are from one
run on this machine (macOS arm64, Python 3.12, the locked backend environment). Re-running will
rewrite the checkpoints; the seed makes the synthetic GRU labels and the split deterministic.

Nothing here is calibrated mastery, a learning gain, or a better tutor.

## GRU knowledge tracing

The model is a unidirectional PyTorch GRU with concept embeddings. At step t the input is the
current concept, the previous response (never the current one) and, only when
`--graph-features` is set, four scalars summarizing earlier prerequisite outcomes. That summary
is not a graph neural network. Padding is masked out of the loss. Learners are split before
windows are built. The comparison with BKT uses the same eligible observation IDs and predicts
before it observes. AUROC is omitted when a score file has only one outcome class.

```sh
EXP="env PYTHONPATH=backend OMP_NUM_THREADS=2 backend/.venv/bin/python"
$EXP -m experiments.tracing train --synthetic --seed 17 --epochs 2 --output artifacts/gru-smoke
$EXP -m experiments.tracing evaluate --checkpoint artifacts/gru-smoke \
  --output artifacts/gru-smoke/eval.json
```

Recorded `train` result (exit 0):

| Item | Value |
| --- | --- |
| Seed | 17 |
| Train learners | `learner.train.0` … `learner.train.3` |
| Held-out learners | `learner.heldout.0`, `learner.heldout.1` |
| Held-out target count | 12, identical IDs for GRU and BKT |
| Epoch losses | 0.7365320324897766, 0.6152557730674744 (finite) |
| Parameter L1 change | 55.052391335368156 |
| Reload max abs probability diff | 0.0 (tolerance 1e-5) |
| GRU log loss / Brier / AUROC | 0.6283835614226976 / 0.21919086170568333 / 0.625 |
| BKT log loss / Brier / AUROC | 0.6446029065960897 / 0.22623767596465286 / 0.875 |
| Threads | 2 |
| Training-section time | 0.6367659170064144 s |
| Process wall clock | 1.70 s real, 1.48 s user |
| Process max RSS | 308117504 bytes (macOS `ru_maxrss`, includes the PyTorch runtime) |

GRU calibration counts on the 12 targets, bins of width 0.2: 0, 0, 2, 10, 0. BKT counts: 0, 8,
4, 0, 0. Log loss and AUROC disagree on this draw, so the table is not a ranking of teaching
quality. Ineligible `obs.ineligible` and duplicate `obs.duplicate` are not in the target list.

A separate one-epoch run with `--graph-features --n-train 2 --n-heldout 1 --length 4` also
exited 0 (`artifacts/gru-graph`). It updated parameters (L1 change 44.730356991291046) and
reloaded within tolerance. It does not show that the prerequisite summary helps.

The card written beside the checkpoint is copied, with these measurements, to
[model-cards/gru-synthetic-smoke.md](model-cards/gru-synthetic-smoke.md).

## Shared tutor examples

Reviewed fictional rows live in
`backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl` (`CC0-1.0`, source
`rubberducky.fictional_shared.v1`). Preparation groups rows that share a scenario, problem or
concept family and holds out whole groups. Prompt and padding labels are `-100`.

```sh
$EXP -m experiments.tutor_data validate \
  --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl
$EXP -m experiments.tutor_data prepare \
  --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl \
  --output artifacts/tutor-data --seed 17
$EXP -m experiments.tutor_data dry-run \
  --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl \
  --output artifacts/tutor-data-dry --seed 17
```

Recorded results (each exit 0, `download_count` 0):

- Validate accepted `ex.grouping.1`, `ex.equality.1`, `ex.transfer.1`.
- Prepare, seed 17, trained `ex.grouping.1` and `ex.transfer.1` (they share
  `concept.distribution`) and held out `ex.equality.1`.
- Dry-run wrote `manifest.json` only.

`teacher` without `--activate` exits 2 and does not call a provider. With
`--activate --provider mock --max-cost-usd 0.05` it writes an unreviewed mock row. Unreviewed,
private, missing-source and cross-split rows are excluded from training. Remote providers stay
off unless `--allow-remote` is also set, and this workspace did not set it. There is no
per-learner fine-tune.

## Tiny LoRA

The default base is a randomly initialized Llama config (hidden size 32, one layer, vocabulary
64). No pretrained weights are loaded. The opt-in SmolLM2-135M path
(`HuggingFaceTB/SmolLM2-135M-Instruct`, revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`)
refuses to download unless a later command explicitly allows it; that command was not run.

```sh
$EXP -m experiments.lora train --smoke --seed 17 --steps 2 \
  --data artifacts/tutor-data --output artifacts/lora-smoke
$EXP -m experiments.lora reload --checkpoint artifacts/lora-smoke
$EXP -m experiments.lora evaluate --checkpoint artifacts/lora-smoke --data artifacts/tutor-data
```

Recorded `train` result (exit 0):

| Item | Value |
| --- | --- |
| Seed / steps | 17 / 2 |
| Targets | `q_proj`, `v_proj`; rank 2, alpha 4, dropout 0 |
| Losses | 4.13395881652832, 4.132872581481934 (finite) |
| Adapter L1 change | 2.8059804439544678 |
| Base max absolute change | 0.0 |
| Reload max abs logit diff | 0.0 (tolerance 1e-4), including a second `reload` command |
| Pretrained activated | false |
| Threads | 2 |
| Training-section time | 2.4313566249911673 s |
| Process wall clock | 3.54 s real, 2.73 s user |
| Process max RSS | 373587968 bytes (includes the PyTorch and Transformers runtime) |

`evaluate` used the same greedy settings for the base and the adapter
(`do_sample` false, `max_new_tokens` 8, `num_beams` 1, temperature unset) on held-out
`ex.equality.1`. Both completions were the single token id `2`. Rubric scores matched
(answer withheld 1, respectful 1, gold-token overlap 0). Completion NLL moved from
4.149040222167969 to 4.1437177658081055, so the report lists one numeric improvement and no
regression on this draw. A regression is recorded when a rubric score falls or NLL rises; this
run simply did not produce one. The text is not a tutoring response.

See [model-cards/lora-random-base-smoke.md](model-cards/lora-random-base-smoke.md).
