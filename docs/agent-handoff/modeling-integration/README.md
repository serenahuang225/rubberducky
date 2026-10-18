# External modeling handoff integration

## Goal and current status

**Receiving-agent role: integrate, review and validate the user's other agent's delivered
GRU/shared-dataset/LoRA work. Do not implement those pipelines.**
Feature `external-modeling-handoff-integration` owns **VAL-EXP-001..004**, all pending.
Read the [index](../README.md), [backend guide](../../../backend/README.md) and
[working-tree coordination](../working-tree/README.md).

No branch/worktree/commit IDs, delivered model cards or actual experiment results are recorded.
Missing delivery is a **user/other-agent input blocker**, not permission to write substitute
training. Original three implementation queue entries were cancelled as ownership-transfer
history; acceptance was not dropped. Documentation does not resume implementation/training.

Request this exact external handoff:

1. Repository-relative base/branch and absolute worktree path, commit IDs and changed paths.
2. Actual commands/options for GRU train/save/reload/eval; dataset validate/prepare/dry-run/
   teacher fixture; LoRA smoke/save/reload/matched eval, including dependencies/locks.
3. Exact tests/exits, dataset manifests/split IDs/mask evidence, checkpoint/config/base/vocab,
   metrics/model cards and small artifact locations.
4. Known failures/gaps and synthetic/random-base limitations. No auto-merge/push.

## Already implemented / do not rebuild

- [BKT](../../../backend/app/tracing/bkt.py), [common predictor](../../../backend/app/tracing/predictor.py),
  [contracts](../../../backend/app/tracing/contracts.py), [eligibility](../../../backend/app/tracing/eligibility.py)
  and [replay](../../../backend/app/tracing/replay.py) exist.
- [Memory/context](../../../backend/app/inference/context.py), [graph](../../../backend/app/graph/),
  validated providers/coordinator and persistence are real. Preserve their provenance/
  causality/isolation instead of importing lifetime history or raw private student data.
- [Tutoring evaluator](../../../backend/app/tutoring_eval/) in `b76811e` has seven authored
  fictional cases/nine turns, strict-before bounded snapshots/source IDs, separate scores/
  latency, fixture and response-file candidates, and actual Chalk SDK fixture transports.
  This is reusable evaluation plumbing, **not** an experiment or trained adapter result.
- Readiness tiny GRU/LoRA optimizer probes were disposable toolchain checks, not delivered
  experiment source/checkpoints or approved product results. Do not relabel them.

## Relevant code and interfaces

The common `StatisticalPredictor` protocol covers metadata, predict-before-observation,
observe, reset and save/load. GRU next-response probability is not latent mastery:
use `latent_knowledge=None`, `has_latent_state=False` where that protocol requires it.

BKT handparameters: `p_init=.2`, `p_learn=.1`, `p_guess=.25`, `p_slip=.1`, uncalibrated.
Prediction `p(1-s)+(1-p)g`; posterior uses response likelihood; transition
`posterior+(1-posterior)T`. Invalid/impossible observations are explicit, never NaN.
For the fixture: first correct leads10/19; two corrects0.82; correct then incorrect67/310.
Match GRU to **BKT predicted correctness**, not latent knowledge.

Eligibility is causal: only verified independent non-explanation assessments, one opportunity
per problem/concept. Hints before the response taint independence; later corrective feedback
cannot reach backward. Assisted/revealed/unknown/self-report evidence remains distinguishable.
Use identical target IDs/splits for comparison, not loosely similar counts.

External experiment package/file/CLI names are **not present in this snapshot**. Do not
invent `app.cli gru`, `train-lora` flags or a nonexistent `backend/experiments/` link.
Shared config/CLI/test entrypoints require coordination with integration owners.

### Complete original modeling scope — reference for the external implementer

This section preserves original requirements for the implementer and the receiver's review.
It is not an assignment to the receiver to fill missing code.

**GRU tracing**
- Genuine compact unidirectional PyTorch GRU with concept embeddings behind the common
  predictor. Shift previous **completed** interactions so the current target response and
  future hints/verifier/memory cannot enter their own prediction.
- Mask padding for prediction/loss, preserve chronological order, split learners before
  constructing windows, document held-out-learner and chronological evaluation.
- Finite cold-start/unseen-concept handling, reset/replay, seeded deterministic configuration,
  saved weights/config/vocabulary, checkpoint reload with stated tolerance.
- Target/future perturbation invariance, padding invariance, split/window-disjoint tests.
  Optional prerequisite-summary/graph-feature comparison has an executable ablation flag;
  no assertion that a GNN or graph features are necessary/superior.
- Bounded genuine seeded synthetic backward/optimizer run showing nonzero parameter updates;
  held-out same-target-ID comparison with real BKT: log loss, Brier, calibration bins/counts,
  assistance eligibility/counts and AUROC only with both labels. One-class AUROC is undefined.
  This proves execution, not real predictive utility, calibrated mastery or learning gains.

**Shared tutoring examples**
- Versioned executable validation/preparation/dry-run accepts reviewed fictional/shared
  examples and explicitly rejects/quarantines malformed, unreviewed, private learner/recording,
  missing-source and leaky-family fixtures with selected/excluded IDs/reasons.
- Group held-out related problem/concept/scenario families; do not randomly split near-duplicate
  turns/examples across train and evaluation. Completion-only masks exclude prompt and padding.
- Configurable teacher generation uses existing provider boundaries, disabled absent activation
  and bounded terms/cost controls; records provider/model/version/source/template/terms/cost/
  review state. Generated examples need review before default training.
- Public data requires license/access/mapping documentation before use, not automatic download.
  No private recordings/default learner data, per-learner fine-tuning or unapproved dataset.

**Shared PEFT LoRA**
- Executable pipeline with architecture-specific supported target-module validation, actual
  PEFT `LoraConfig`/CAUSAL_LM/get_peft_model/save_pretrained/PeftModel.from_pretrained behavior.
  Check installed Transformers5.20.1/PEFT0.21.2 compatibility, not guessed APIs.
- Offline tiny **random-config** supported causal Transformer requires no pretrained weights/
  tokenizer download. Real backward/optimizer, finite loss, nonzero trainable adapter update
  and intended frozen-base invariance; prompt/padding labels `-100`.
- Save adapter/config and reproducible same base; reject unsupported targets/incompatible base.
  Reloaded outputs agree within stated tolerance, not merely “file exists.”
- Base/adapter use identical held-out examples/prompts/decoding/scorers. Report both actual
  results including regressions, no tuned-model win inferred from loss decreasing.
- Configurable pretrained mode remains lazy/opt-in; no expensive GPU/cloud run by default.
  Card prominently says random-base synthetic plumbing, **not a useful fine-tuned tutor**.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] Ask for the external delivery above. **Stop if absent.** Do not dispatch duplicate
   implementation/training or continue a missing handoff by guessing.
2. [ ] Inspect delivered base/diff/status and configured identity; inventory intended files and
   large/private artifacts before integration. Review in a separate worktree, never copy
   `.venv`/`node_modules`, dirty UI, real databases or raw data.
3. [ ] Agree on bounded integration ownership: CLI registrations, predictor interface, dataset
   response format/tooling. Integrate only delivered intended commits after explicit permission;
   preserve original worker commit provenance, no history rewriting or broad reset/stash.
4. [ ] Review each scientific/data/interface criterion above against actual code/tests/results.
   Small interface conflicts may be resolved within assignment; missing pipeline/masking/
   training behavior goes back to external implementer, not silently rebuilt.
5. [ ] Run proportionate delivered focused tests and bounded documented train/reload/eval once
   after authorization, using temporary outputs, two threads, no downloads/network/private data.
   Reuse unaffected external evidence; no repeated heavyweight experiment.
6. [ ] Verify same eligible target IDs for BKT/GRU, disjoint learner/family splits, shifted target
   exclusion, padding/completion masks, actual changed parameters/frozen base/checkpoint reload.
   Retain real failure/undefined metric results.
7. [ ] Connect actual external tutor outputs through existing Candidate/response-file evaluator
   only after delivery. Record base/adapter identity/prompts/decoding/held-out provenance
   outside the fixture report; do not flip its intentionally false claims.
8. [ ] Hand artifact-matching cards/metrics/commands and gaps to delivery owner. Formal001..004
   remain pending until actual integrated validation; report unavailable inputs honestly.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

| ID | Receiver must verify from delivered work |
| --- | --- |
| VAL-EXP-001 | Actual GRU/concept tensors/common interface; causal shift, chronology, target/future perturbation and padding invariance, finite cold/unseen/reset; learner-disjoint split-before-windows; optional graph ablation |
| VAL-EXP-002 | Seeded tiny genuine optimizer update/save/config/vocab/reload; same eligible held-out target IDs as BKT; actual counts/log loss/Brier/calibration/AUROC or undefined; tolerance stated |
| VAL-EXP-003 | Reviewed provenance-aware validation/prep/dry-run, named exclusions, grouped holdouts and prompt/padding masks; configurable gated teacher metadata/terms/cost; no private/default downloads |
| VAL-EXP-004 | Actual random-base PEFT optimization, changed adapters/frozen base, supported/rejected targets/masks, same-base reload tolerance and matched held-out base/adapter results including regressions |

No requirement for public dataset runs, pretrained useful model, GPU purchase, learner study,
scientific novelty, learning-gain claims or new artifact proof subsystem.

## Verification commands and evidence

**Not run here; external train/prep/LoRA commands remain unknown until handoff.**
Do not substitute invented commands. Existing future local evaluator commands, using the clean
isolated-DB `cli` wrapper in [backend guide](../../../backend/README.md):

```sh
cli evaluation cases
cli evaluation run --candidate fixture:good
cli evaluation run --responses-file /absolute/path/to/delivered/replies.jsonl
cli evaluation chalk-plan --responses-file /absolute/path/to/delivered/replies.jsonl
```

Response JSONL fields: `case_id`, `turn_id`, `text`; optional `cited_source_ids`,
`answer_revealed`, `latency_ms`. Sources must be available at each strictly-before replay
cutoff; default history6/max20. Supplied latency is labeled `supplied_by_candidate_source`;
fixtures have missing latency, not0. Report seven dimensions separately: math, diagnosis,
disclosure, hint specificity/usefulness, respect, memory grounding; latency separately.
Model-judged ratings stay separate. Candidate files are not the training data interface.

Current report intentionally retains `trained_model_result=false`, `learning_gain_claim=false`;
file input is precomputed external responses, not proof of a trained model. Matching actual
base/adapter outputs/checkpoints/cards supply separate evidence. No `chalk-run --confirm-live`,
deploying module import or cloud scorer needed for this assignment. Chalk account queue/
enablement/shipping/judge-column/cost remain unverified.

After bounded integration, applicable backend pytest/mypy (explicit backend config)/Ruff gates
and delivered package CLI checks get actual exits. Record artifact paths, seed/splits/IDs/
mask counts, before/after parameters, tolerance, metrics/counts, runtime/resources if actually
measured, failures and skipped live/pretrained work. Tests passing are not educational results.

## Ownership, dependencies, parallelism and stop conditions

Other agent owns GRU/dataset/LoRA implementation; receiving agent owns review/integration/
validation only. Delivery owns final narrative/cards/inventory; evaluator implementation is
already complete. Coordinate CLI/config/interface edits with Photon/voice. No frontend/media/
integration rebuilds or editing external worktree/mission artifacts.

Stop on absent/incomplete commits/results, private/unknown-license data, unapproved downloads/
spend, scientific leakage/mask/checkpoint failure or broad conflict requiring implementation.
Return exact failing criterion and external owner follow-up; do not relax criteria or fabricate
results to unblock delivery.

## Not authorized / deferred

No duplicate model implementation, private data/recordings, public/pretrained downloads,
expensive GPU/cloud runs, live teacher/Chalk calls, per-learner fine-tuning, browser/services,
secret reads, auto-merge/push or commits during the docs request.
Readiness execution and fixture scores cannot become actual trained-model/learning gains.

## Copyable assignment prompt

> Receive and integrate only the external commits/results I supply:
> [absolute worktree/branch/base/commits/artifacts]. Read this README, handoff index,
> backend and working-tree guides. GRU/shared-data/LoRA implementation remains with the
> other agent. Verify VAL-EXP-001..004 causality, split/mask/eligibility, real optimizer/
> frozen-base/checkpoint and matched evaluation requirements using bounded actual delivered
> tests/commands. Connect real outputs through existing Candidate interface without changing
> fixture honesty. No duplicate pipeline, downloads/private data/GPU/cloud/live spend.
> If delivery is absent/incomplete or scientifically fails, return exact input/fix needed
> to its owner, not a substitute implementation.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include external base/branch/commit provenance, assertion-by-assertion review, seed/split/
target IDs/masks/optimizer/checkpoint/tolerance evidence, actual matched metrics/regressions,
card paths and explicit synthetic/random-base/untrained/unverified limits.
