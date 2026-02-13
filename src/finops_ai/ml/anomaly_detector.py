"""
Anomaly Detector — Isolation Forest for cost anomaly detection.

Uses Isolation Forest to identify unusual spending patterns, orphan surges,
and other anomalies in cloud resource data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finops-ai.ml.anomaly")


@dataclass
class Anomaly:
    """A detected cost anomaly."""

    resource_id: str
    resource_name: str
    provider: str
    anomaly_score: float
    feature_values: Dict[str, float] = field(default_factory=dict)
    description: str = ""
    severity: str = "medium"

    def __post_init__(self) -> None:
        if self.anomaly_score > 0.8:
            self.severity = "critical"
        elif self.anomaly_score > 0.6:
            self.severity = "high"
        elif self.anomaly_score > 0.4:
            self.severity = "medium"
        else:
            self.severity = "low"


@dataclass
class AnomalyDetectionResult:
    """Result of anomaly detection run."""

    total_resources: int = 0
    anomalies_detected: int = 0
    anomalies: List[Anomaly] = field(default_factory=list)
    model_accuracy: float = 0.0
    features_used: List[str] = field(default_factory=list)


class AnomalyDetector:
    """
    Isolation Forest-based anomaly detector for cloud resources.

    Identifies resources with unusual cost patterns, age profiles,
    or usage characteristics compared to their peers.
    """

    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 100,
        random_state: int = 42,
    ) -> None:
        try:
            from sklearn.ensemble import IsolationForest
            import numpy as np
            import pandas as pd
        except ImportError:
            raise ImportError(
                "ML libraries not installed. Install with: pip install finops-ai[ml]"
            )

        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        self._model: Optional[Any] = None
        self._feature_names: List[str] = []

    def _extract_features(self, resources: list) -> Any:
        """Extract numerical features from OrphanedResource objects."""
        import numpy as np
        import pandas as pd

        features = []
        for r in resources:
            features.append({
                "size_gb": r.size_gb,
                "estimated_monthly_cost": r.estimated_monthly_cost,
                "age_days": r.age_days,
                "tag_count": len(r.tags),
                "dependency_count": len(r.dependent_resources),
            })

        df = pd.DataFrame(features)
        self._feature_names = list(df.columns)

        # Fill NaN with 0
        df = df.fillna(0)

        return df

    def detect(self, resources: list) -> AnomalyDetectionResult:
        """
        Run anomaly detection on a list of OrphanedResource objects.

        Args:
            resources: List of OrphanedResource instances.

        Returns:
            AnomalyDetectionResult with detected anomalies.
        """
        import numpy as np
        from sklearn.ensemble import IsolationForest

        if len(resources) < 5:
            logger.warning("Too few resources for anomaly detection (need >= 5)")
            return AnomalyDetectionResult(total_resources=len(resources))

        features_df = self._extract_features(resources)

        # Fit Isolation Forest
        self._model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=self.random_state,
        )

        predictions = self._model.fit_predict(features_df.values)
        scores = self._model.decision_function(features_df.values)

        # Normalize scores to [0, 1] where 1 = most anomalous
        min_score, max_score = scores.min(), scores.max()
        if max_score > min_score:
            normalized_scores = 1 - (scores - min_score) / (max_score - min_score)
        else:
            normalized_scores = np.zeros(len(scores))

        anomalies: List[Anomaly] = []
        for i, (pred, score) in enumerate(zip(predictions, normalized_scores)):
            if pred == -1:  # Anomaly
                r = resources[i]
                provider_val = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
                feature_vals = {name: float(features_df.iloc[i][name]) for name in self._feature_names}

                anomaly = Anomaly(
                    resource_id=r.resource_id,
                    resource_name=r.name,
                    provider=provider_val,
                    anomaly_score=float(score),
                    feature_values=feature_vals,
                    description=self._generate_description(r, feature_vals, float(score)),
                )
                anomalies.append(anomaly)

        return AnomalyDetectionResult(
            total_resources=len(resources),
            anomalies_detected=len(anomalies),
            anomalies=sorted(anomalies, key=lambda a: a.anomaly_score, reverse=True),
            features_used=self._feature_names,
        )

    def _generate_description(self, resource: Any, features: Dict[str, float], score: float) -> str:
        """Generate a human-readable description of why this is anomalous."""
        parts = []

        if features.get("estimated_monthly_cost", 0) > 100:
            parts.append(f"High cost: ${features['estimated_monthly_cost']:.2f}/mo")
        if features.get("age_days", 0) > 365:
            parts.append(f"Very old: {int(features['age_days'])} days")
        if features.get("size_gb", 0) > 500:
            parts.append(f"Large: {features['size_gb']:.0f} GB")
        if features.get("tag_count", 0) == 0:
            parts.append("Untagged resource")

        if not parts:
            parts.append(f"Unusual pattern (anomaly score: {score:.2f})")

        return "; ".join(parts)
