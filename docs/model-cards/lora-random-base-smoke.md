# LoRA random-base smoke model card

This artifact is a **random**-base LoRA plumbing check. It is **not a tuned tutor**, not a
pretrained-model run, and not evidence of better teaching. The base is initialized from a small
Llama config. No weight file was downloaded.

## Data and split

- Reviewed fictional rows from `backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl`.
- Source `rubberducky.fictional_shared.v1`, license `CC0-1.0`, reviewer `fixture-review`.
- Seed 17 preparation trained `ex.grouping.1` and `ex.transfer.1` (shared concept family
  `concept.distribution`) and held out `ex.equality.1`.
- Prompt and padding labels are `-100`. Only completion tokens are in the loss.
- No per-learner fine-tune and no public-dataset download.

## Configuration

- Seed 17, 2 AdamW steps, learning rate 0.01.
- Random Llama: vocabulary 64, hidden 32, intermediate 64, 1 layer, 4 heads, 2 key/value heads,
  max position 256. `tie_word_embeddings` true. Pad/bos/eos ids 0/1/2.
- LoRA: PEFT `LoraConfig`, `TaskType.CAUSAL_LM`, targets `q_proj` and `v_proj`, rank 2, alpha 4,
  dropout 0, bias none.
- Base parameters frozen. Pretrained path not activated.
- Opt-in candidate, not used: `HuggingFaceTB/SmolLM2-135M-Instruct` revision
  `12fd25f77366fa6b3b4b768ec3050bf629380bac` (Apache-2.0). Download stays disabled.
- Checkpoint (local, not committed): `artifacts/lora-smoke/` (`base_state.pt`, `adapter/`,
  `config.json`, `probe.json`, `metrics.json`, `evaluation.json`).
- Reload tolerance: 1e-4 on logits. Measured max absolute difference: 0.0, both inside `train`
  and on a later `reload` command.
- Decoding for the comparison: greedy, `do_sample` false, `max_new_tokens` 8, `num_beams` 1,
  temperature unset. Same settings for the base and the adapter.

## Metrics

Train losses: 4.13395881652832, 4.132872581481934 (both finite). Adapter L1 change:
2.8059804439544678. Base max absolute change: 0.0.

Held-out `ex.equality.1` (same prompt, decoding and rubric):

| Score | Base | Adapter |
| --- | --- | --- |
| Answer withheld | 1.0 | 1.0 |
| Respectful | 1.0 | 1.0 |
| Gold-token overlap | 0.0 | 0.0 |
| Completion NLL | 4.149040222167969 | 4.1437177658081055 |

Greedy completions were the token id `2` for both models. The report lists one improvement
(the NLL delta -0.005322456359863281) and no regression. The comparison code records a
regression when a higher-is-better score drops or NLL rises; this draw did not produce one.
Overlap with the reviewed completion is zero either way.

## Resources

- Training section: 2.4313566249911673 s.
- Shell wall clock for `train`: 3.54 s real, 2.73 s user, 0.56 s system.
- `ru_maxrss`: 373587968 bytes, including PyTorch and Transformers, not the adapter alone.
- Threads: 2. CPU only.
- `reload` wall clock 3.30 s real. `evaluate` wall clock 3.20 s real. Both exit 0.

## Limitations

Randomly initialized tiny Transformer and two CPU steps on fictional examples. Not a tuned
tutor, not a pretrained-model run, and not an educational improvement.
