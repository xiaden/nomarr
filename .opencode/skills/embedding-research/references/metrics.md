# Metrics — Primary, Advisory, and Forbidden

All metrics used in the embedding research pipeline, with their meaning and ranking.

---

## Primary Metrics (used for candidate ranking)

| Metric | Meaning | Priority |
|--------|---------|----------|
| `disc_general` | Mean of non-zero `(disc_artist, disc_genre, disc_head)` | **Primary ranking metric** |
| `disc_artist` | Pairwise sim gap: same-artist pairs vs cross-artist | Required |
| `disc_genre` | Pairwise sim gap: same-genre pairs vs cross-genre | Required |
| `disc_head` | Head discriminability via 10-bin histogram overlap | Required |
| `map_k` | Mean Average Precision at k | Required |
| `ndcg_k` | NDCG at k | Secondary |
| `precision_k_genre` | Precision@k for genre-matching | Secondary |
| `precision_k_head_mean` | Precision@k averaged over all heads | Secondary |

---

## Advisory Metrics (present but not primary)

| Metric | Notes |
|--------|-------|
| `disc_score` | Raw pairwise sim gap (artist only, not genre/head). Less informative than `disc_general`. |
| `mrr` | Mean Reciprocal Rank. Useful for top-1 analysis, not primary. |
| `recall_k` | Recall@k. Use alongside MAP, not standalone. |
| `mean_within` / `mean_cross` | Raw within-group and cross-group cosine means. Useful for diagnosing collapse. |
| `per_head_corr` | Spearman correlation between pairwise cosine sim and mean head-score difference. Measures whether embedding geometry tracks head predictions. |
| `flat_binned_spearman` | Rank correlation between flat and binned similarity rankings for same song pairs. High value = binned adds no ordering information. |
| `flat_binned_beneficial_reorder_rate` | Fraction of pairs where binned ranking moves a same-artist pair higher than flat did. Positive = useful reordering. |

---

## Forbidden / Do Not Add

| Column | Reason |
|--------|--------|
| `disc_album` | Removed from schema. Does not exist. Never SELECT or upsert. |
| `recall_k_album` | Removed from schema. Does not exist. |
| `bin_div_std` | Removed — mean pairwise bin distance has no semantic quality signal (see FINDINGS.md). |
