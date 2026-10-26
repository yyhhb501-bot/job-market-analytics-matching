"""TF-IDF + Linear SVM classifier for job occupation and seniority.

Trains TF-IDF + Linear SVM heads against the keyword-rule baseline in
``packages/enrichment/occupations.py``. Confidence values are relative
confidence scores derived from SVM decision margins; they are not calibrated
probabilities. See scripts/train_and_eval_classifier.py for the reproducible
evaluation protocol (group-stratified splits, distinct strategy metrics).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jobagg.classifier")

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-']+")


def _clean_text(title: str | None, description: str | None = None, max_desc_len: int = 1500) -> str:
    """Combine title and description excerpt into normalized text."""
    parts: list[str] = []
    if title:
        # Title is weighted by repeating it 2x to give lexical priority
        clean_title = " ".join(_WORD_RE.findall(title.lower()))
        parts.append(clean_title)
        parts.append(clean_title)
    if description:
        clean_desc = " ".join(_WORD_RE.findall(description[:max_desc_len].lower()))
        parts.append(clean_desc)
    return " ".join(parts).strip()


@dataclass
class ClassificationResult:
    occupation: str | None
    # Relative confidence scores derived from the SVM decision margins (softmax
    # over one-vs-rest margins). These are NOT calibrated probabilities; do not
    # present them as such before a calibration study exists.
    occupation_relative_score: float
    seniority: str | None
    seniority_relative_score: float
    method: str = "svm"  # "svm" | "baseline" | "fallback"

    @property
    def occupation_confidence(self) -> float:
        """Backwards-compatible alias for the relative confidence score."""
        return self.occupation_relative_score

    @property
    def seniority_confidence(self) -> float:
        """Backwards-compatible alias for the relative confidence score."""
        return self.seniority_relative_score


@dataclass
class EvaluationReport:
    baseline_occupation_macro_f1: float
    svm_occupation_macro_f1: float
    baseline_seniority_macro_f1: float
    svm_seniority_macro_f1: float
    overall_baseline_macro_f1: float
    overall_svm_macro_f1: float
    hybrid_occupation_macro_f1: float | None = None
    hybrid_seniority_macro_f1: float | None = None
    overall_hybrid_macro_f1: float | None = None
    detailed_metrics: dict[str, Any] = field(default_factory=dict)
    misclassification_analysis: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


class OccupationSeniorityClassifier:
    """Dual-head TF-IDF + Linear SVM classifier for occupation and seniority."""

    MODEL_FILENAME = "job_classifier_svm.joblib"

    def __init__(self, model_dir: Path | str | None = None) -> None:
        if model_dir is None:
            self.model_dir = Path(__file__).resolve().parent / "models"
        else:
            self.model_dir = Path(model_dir)

        self.vectorizer = None
        self.occupation_clf = None
        self.seniority_clf = None
        self.occupation_classes: list[str] = []
        self.seniority_classes: list[str] = []
        self.is_trained = False

        # Try auto-loading existing trained model
        model_file = self.model_dir / self.MODEL_FILENAME
        if model_file.exists():
            try:
                self.load(model_file)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to auto-load classifier model: %s", exc)

    def _init_pipeline_components(self) -> None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.svm import LinearSVC
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn is required to use OccupationSeniorityClassifier. "
                "Install with `pip install scikit-learn`."
            ) from exc

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_features=12000,
            min_df=2,
            stop_words="english",
        )
        self.occupation_clf = LinearSVC(
            C=1.0,
            class_weight="balanced",
            random_state=42,
            dual="auto",
            max_iter=3000,
        )
        self.seniority_clf = LinearSVC(
            C=1.0,
            class_weight="balanced",
            random_state=42,
            dual="auto",
            max_iter=3000,
        )

    def fit(
        self,
        samples: list[dict[str, Any]],
    ) -> None:
        """Fit vectorizer and SVM classifiers on labeled samples.

        Each sample should contain:
        - 'title': job title
        - 'description': (optional) job text
        - 'occupation': target occupation group
        - 'seniority': target seniority level ('junior', 'mid', 'senior')
        """
        self._init_pipeline_components()

        texts = [_clean_text(s.get("title"), s.get("description")) for s in samples]
        occ_labels = [s["occupation"] for s in samples]
        sen_labels = [s["seniority"] for s in samples]

        X = self.vectorizer.fit_transform(texts)
        self.occupation_clf.fit(X, occ_labels)
        self.seniority_clf.fit(X, sen_labels)

        self.occupation_classes = list(self.occupation_clf.classes_)
        self.seniority_classes = list(self.seniority_clf.classes_)
        self.is_trained = True

    def predict(
        self,
        title: str | None,
        description: str | None = None,
    ) -> ClassificationResult:
        """Predict occupation and seniority with confidence estimation."""
        if not title and not description:
            return ClassificationResult(
                occupation=None,
                occupation_relative_score=0.0,
                seniority=None,
                seniority_relative_score=0.0,
                method="fallback",
            )

        if not self.is_trained or self.vectorizer is None or self.occupation_clf is None:
            # Fall back to keyword baseline
            from packages.enrichment.occupations import (
                classify_occupation_baseline,
                classify_seniority_baseline,
            )

            occ = classify_occupation_baseline(title, description)
            sen = classify_seniority_baseline(title)
            return ClassificationResult(
                occupation=occ,
                occupation_relative_score=0.7 if occ else 0.0,
                seniority=sen,
                seniority_relative_score=0.7 if sen else 0.0,
                method="baseline",
            )

        import numpy as np

        text = _clean_text(title, description)
        X = self.vectorizer.transform([text])

        # Relative confidence scores: softmax over the one-vs-rest decision
        # margins. These quantify the model's relative preference between
        # classes; they are not calibrated probabilities.
        occ_scores = self.occupation_clf.decision_function(X)[0]
        if occ_scores.ndim == 0:  # binary classification edge case
            occ_pred_idx = int(occ_scores > 0)
            occ_score = float(1 / (1 + np.exp(-abs(occ_scores))))
        else:
            exp_scores = np.exp(occ_scores - np.max(occ_scores))
            probs = exp_scores / np.sum(exp_scores)
            occ_pred_idx = int(np.argmax(probs))
            occ_score = float(probs[occ_pred_idx])
        pred_occ = self.occupation_classes[occ_pred_idx]

        # Seniority prediction with its relative confidence score
        sen_scores = self.seniority_clf.decision_function(X)[0]
        if sen_scores.ndim == 0:
            sen_pred_idx = int(sen_scores > 0)
            sen_score = float(1 / (1 + np.exp(-abs(sen_scores))))
        else:
            exp_scores = np.exp(sen_scores - np.max(sen_scores))
            probs = exp_scores / np.sum(exp_scores)
            sen_pred_idx = int(np.argmax(probs))
            sen_score = float(probs[sen_pred_idx])
        pred_sen = self.seniority_classes[sen_pred_idx]

        return ClassificationResult(
            occupation=pred_occ,
            occupation_relative_score=round(occ_score, 4),
            seniority=pred_sen,
            seniority_relative_score=round(sen_score, 4),
            method="svm",
        )

    def predict_occupation(self, title: str | None, description: str | None = None) -> tuple[str | None, float]:
        res = self.predict(title, description)
        return res.occupation, res.occupation_confidence

    def predict_seniority(self, title: str | None, description: str | None = None) -> tuple[str | None, float]:
        res = self.predict(title, description)
        return res.seniority, res.seniority_confidence

    def save(self, path: Path | str | None = None) -> Path:
        """Save vectorizer and classifiers to a joblib file."""
        import joblib

        dest = Path(path) if path else self.model_dir / self.MODEL_FILENAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "vectorizer": self.vectorizer,
            "occupation_clf": self.occupation_clf,
            "seniority_clf": self.seniority_clf,
            "occupation_classes": self.occupation_classes,
            "seniority_classes": self.seniority_classes,
        }
        joblib.dump(payload, dest, compress=3)
        logger.info("Saved classifier models to %s", dest)
        return dest

    def load(self, path: Path | str) -> None:
        """Load vectorizer and classifiers from joblib file."""
        import joblib

        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"Classifier model file not found: {src}")
        payload = joblib.load(src)
        self.vectorizer = payload["vectorizer"]
        self.occupation_clf = payload["occupation_clf"]
        self.seniority_clf = payload["seniority_clf"]
        self.occupation_classes = payload.get("occupation_classes") or list(
            self.occupation_clf.classes_
        )
        self.seniority_classes = payload.get("seniority_classes") or list(
            self.seniority_clf.classes_
        )
        self.is_trained = True
        logger.info("Loaded classifier models from %s", src)


# Global singleton instance
_GLOBAL_CLASSIFIER: OccupationSeniorityClassifier | None = None


def get_classifier() -> OccupationSeniorityClassifier:
    global _GLOBAL_CLASSIFIER
    if _GLOBAL_CLASSIFIER is None:
        _GLOBAL_CLASSIFIER = OccupationSeniorityClassifier()
    return _GLOBAL_CLASSIFIER


def set_global_classifier(clf: OccupationSeniorityClassifier) -> None:
    """Replace the process-wide singleton so the online hybrid policy in
    :mod:`packages.enrichment.occupations` evaluates with a specific model
    (used by the evaluation pipeline after training a fresh artifact)."""
    global _GLOBAL_CLASSIFIER
    _GLOBAL_CLASSIFIER = clf
