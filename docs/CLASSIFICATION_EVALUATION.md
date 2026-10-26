# Occupation & Seniority Classification: Evaluation Report

> 本报告由 `scripts/train_and_eval_classifier.py` 根据`artifacts/classification_eval/evaluation_metrics.json` 自动生成；数字来自实际计算。精确复现需要相同数据哈希与依赖版本；默认仅使用仓库内合成模板，不自动读取私人数据库。

## Reproducibility

- Random seed: `42`; test fraction: 0.25; train 308 / test 129 samples.
- Dataset sha256 (corpus content hash): `672bac2668316d38fb6164f825f55a85e4d1a37afa5918b541833b7c8f67daf1`.
- Corpus scope: `synthetic_only`; synthetic/weak-label results are not human-labelled real-world accuracy.
- Version pins: `{'python': '3.11.7', 'platform': 'Windows-10-10.0.19045-SP0', 'numpy': '1.26.3', 'sklearn': '1.9.1', 'joblib': '1.6.0'}`.

## Data provenance & leakage control

- Group rule: same-template, same-job and cross-source-duplicate variants share one dedup group and one split; TF-IDF fit on training split only.
- Label provenance — template rows: `synthetic smoke-test corpus; hand-authored, not job-board annotation`; `.preview.db` rows: `keyword-rule pseudo labels from .preview.db; not human ground truth`.
- Human ground truth present: `False`; metrics rows are therefore comparison experiments against rule-derived labels, not human accuracy.
- TF-IDF fit scope: `training_split_only`.

## 1. Three strategies evaluated on the identical group-split holdout

| Strategy | Occupation Macro-F1 | Seniority Macro-F1 | Overall Macro-F1 | Occupation errors | Seniority errors | Total errors |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Keyword-rule baseline** | 0.7525 | 0.7551 | 0.7538 | 30 | 32 | 62 |
| **TF-IDF + Linear SVM (pure)** | 0.6855 | 0.4817 | 0.5836 | 32 | 66 | 98 |
| **Online hybrid (rule-first, ML fallback)** | 0.7525 | 0.7465 | 0.7495 | 30 | 32 | 62 |

Overall Macro-F1 = equally weighted mean of occupation and seniority Macro-F1 (same 0.5/0.5 definition applied to all three rows).

**Error count went UP, not down**: pure SVM committed 98 errors vs. 62 baseline (+36 on this holdout). The SVM's gains on ambiguous titles are offset by new failures elsewhere — every failing row is listed in `artifacts/classification_eval/error_examples.csv`. No reduced-error claim is made here.

## 2. Honest comparison with the resume claim

The resume says *raising Macro-F1 from 0.68 to 0.84*. On this group-split holdout the computed values were: baseline overall 0.7538 → pure SVM overall 0.5836, online hybrid 0.7495.

**The measured values do not match the resume claim.** Suggested honest resume wording:

> "Classified job postings by occupation group and seniority using TF-IDF + linear SVM evaluated against a keyword-rule baseline; on a group-stratified, de-duplicated holdout of collected postings, the keyword-rule baseline reached 0.7538 overall Macro-F1 while the pure SVM reached 0.5836 on the same group-split holdout, so the SVM did not outperform the baseline once template leakage was removed; the deployed online policy stays rule-first (0.7495 Macro-F1). Confusion analysis covers ambiguous titles and mixed-responsibility roles. Human-labelled holdout evaluation pending."

Do not reuse 0.68→0.84 until a human-labelled holdout reproduces it.

## 3. Per-class breakdown & artifacts

Per-class precision/recall/F1/support for every strategy x head, full confusion matrices and per-sample predictions are stored in `artifacts/classification_eval/`:

`evaluation_metrics.json`, `per_class_metrics.csv`, `confusion_matrices.csv`, `predictions.csv`, `error_examples.csv`.

Occupation support on the test split:

| occupation | test samples |
|---|:---:|
| `accountant` | 6 |
| `admin` | 7 |
| `aged-care` | 4 |
| `business-analyst` | 4 |
| `chef` | 4 |
| `construction` | 4 |
| `customer-service` | 3 |
| `cybersecurity` | 4 |
| `data-analyst` | 7 |
| `data-engineer` | 4 |
| `data-scientist` | 4 |
| `devops-sre` | 4 |
| `electrician` | 4 |
| `financial-analyst` | 3 |
| `healthcare-allied` | 4 |
| `hr` | 4 |
| `legal` | 3 |
| `marketing` | 3 |
| `mechanic` | 4 |
| `product-manager` | 4 |
| `project-manager` | 4 |
| `registered-nurse` | 7 |
| `retail` | 4 |
| `sales` | 3 |
| `security-officer` | 4 |
| `software-engineer` | 8 |
| `teacher` | 4 |
| `truck-driver` | 4 |
| `warehouse` | 7 |

## 4. Misclassification pattern analysis

Same group-split holdout; the three strategies are reported separately. Keyword baseline errors: 62 (occ 30, sen 32); pure SVM errors: 98 (occ 32, sen 66); online hybrid errors: 62 (occ 30, sen 32).

- Most frequent pure-SVM occupation confusions: `devops-sre → software-engineer` ×4, `admin → legal` ×4, `aged-care → customer-service` ×4, `data-engineer → data-analyst` ×4, `healthcare-allied → aged-care` ×4
- Error rows for every strategy are enumerated in `artifacts/classification_eval/error_examples.csv`; sample-level reasoning has to stay grounded in those computed rows rather than narrative claims.
