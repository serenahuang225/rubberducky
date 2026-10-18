"""Model card for a synthetic GRU smoke run. Numbers come from the report, not a template guess."""


def _mapping(report: dict[str, object], key: str) -> dict[str, object]:
    value = report[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return value


def render_gru_card(report: dict[str, object]) -> str:
    gru = _mapping(report, "gru")
    bkt = _mapping(report, "bkt")
    reload = _mapping(report, "reload")
    return "\n".join(
        [
            "# GRU synthetic smoke model card",
            "",
            "This artifact is a **synthetic** execution check of a causal GRU on generated",
            "interactions. It is **not calibrated mastery** and it is not evidence that a learner",
            "improved. Do not read a lower log loss than BKT as an educational result.",
            "",
            "## Data and split",
            "",
            f"- Seed: `{report['seed']}`.",
            f"- Train learners: `{report['train_learner_ids']}`.",
            f"- Held-out learners: `{report['heldout_learner_ids']}`.",
            "- Learners were split before sequence windows were built.",
            "- Eligibility rule: `bkt-eligibility.v1`, the same eligible target IDs as BKT.",
            f"- Graph-feature ablation: `{report['graph_features']}`.",
            "",
            "## Configuration",
            "",
            (
                f"- Embed {report['embed_dim']}, hidden {report['hidden_dim']}, "
                f"epochs {report['epochs']}."
            ),
            f"- Numerical threads: {report['threads']}.",
            f"- Elapsed seconds: {report['elapsed_seconds']}.",
            f"- Max RSS bytes (process, platform-specific): {report['max_rss_bytes']}.",
            "",
            "## Metrics on identical held-out target IDs",
            "",
            f"- Target count: {gru['count']}. IDs equal to BKT: `{report['target_ids_equal']}`.",
            (
                f"- GRU log loss {gru['log_loss']}, Brier {gru['brier']}, "
                f"AUROC {gru['auroc']} ({gru['auroc_status']})."
            ),
            (
                f"- BKT log loss {bkt['log_loss']}, Brier {bkt['brier']}, "
                f"AUROC {bkt['auroc']} ({bkt['auroc_status']})."
            ),
            f"- Reload max absolute probability difference {reload['max_abs_diff']} "
            f"(tolerance {reload['atol']}).",
            "",
            "## Limitations",
            "",
            "- Generated labels, a tiny network and a few CPU epochs.",
            "- Hand-set BKT parameters are uncalibrated.",
            "- The GRU probability is not a latent skill.",
            "- No real student recordings, public dataset or pretrained language model was used.",
            "",
        ]
    )
