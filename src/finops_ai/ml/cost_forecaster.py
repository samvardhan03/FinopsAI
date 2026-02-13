"""
Cost Forecaster — time-series cost prediction using Prophet or simple models.

Provides waste growth forecasting so teams can project future savings
and identify cost trends before they become critical.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("finops-ai.ml.forecaster")


@dataclass
class ForecastPoint:
    """A single forecast data point."""

    date: str
    predicted_cost: float
    lower_bound: float
    upper_bound: float


@dataclass
class CostForecast:
    """Result of a cost forecast."""

    provider: str = ""
    resource_type: str = ""
    forecast_days: int = 30
    current_monthly_cost: float = 0.0
    predicted_monthly_cost: float = 0.0
    trend: str = "stable"  # increasing, decreasing, stable
    confidence: float = 0.0
    forecast_points: List[ForecastPoint] = field(default_factory=list)
    savings_potential: float = 0.0


class CostForecaster:
    """
    Cost forecasting using simple trend analysis or Prophet.

    For small datasets, uses linear regression. For larger datasets
    with seasonality, attempts to use Prophet.
    """

    def __init__(self, use_prophet: bool = False) -> None:
        self.use_prophet = use_prophet
        self._prophet_available = False

        if use_prophet:
            try:
                from prophet import Prophet
                self._prophet_available = True
            except ImportError:
                logger.warning("Prophet not installed, falling back to linear regression")

    def forecast_from_snapshots(
        self,
        historical_costs: List[Tuple[str, float]],
        forecast_days: int = 30,
        provider: str = "",
        resource_type: str = "",
    ) -> CostForecast:
        """
        Forecast future costs from historical cost data points.

        Args:
            historical_costs: List of (date_string, cost) tuples.
            forecast_days: Number of days to forecast.
            provider: Cloud provider name.
            resource_type: Type of resource.

        Returns:
            CostForecast with predicted values.
        """
        import numpy as np

        if len(historical_costs) < 3:
            logger.warning("Need at least 3 data points for forecasting")
            return CostForecast(
                provider=provider,
                resource_type=resource_type,
                forecast_days=forecast_days,
            )

        # Parse dates and costs
        dates = []
        costs = []
        for date_str, cost in historical_costs:
            try:
                dates.append(datetime.strptime(date_str, "%Y-%m-%d"))
                costs.append(cost)
            except ValueError:
                continue

        if len(dates) < 3:
            return CostForecast(provider=provider, resource_type=resource_type)

        costs_array = np.array(costs)
        current_cost = float(costs_array[-1])

        if self._prophet_available and len(dates) >= 10:
            return self._forecast_prophet(dates, costs, forecast_days, provider, resource_type)

        return self._forecast_linear(dates, costs_array, forecast_days, provider, resource_type, current_cost)

    def _forecast_linear(
        self,
        dates: List[datetime],
        costs: Any,
        forecast_days: int,
        provider: str,
        resource_type: str,
        current_cost: float,
    ) -> CostForecast:
        """Simple linear regression forecast."""
        import numpy as np

        # Convert dates to numeric (day offsets from first date)
        start_date = min(dates)
        x = np.array([(d - start_date).days for d in dates], dtype=float)
        y = costs

        # Fit linear regression
        n = len(x)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        slope = np.sum((x - x_mean) * (y - y_mean)) / max(np.sum((x - x_mean) ** 2), 1e-10)
        intercept = y_mean - slope * x_mean

        # Standard error for confidence bands
        y_pred = slope * x + intercept
        residuals = y - y_pred
        std_err = float(np.std(residuals))

        # Generate forecast points
        forecast_points: List[ForecastPoint] = []
        last_day = int(x[-1])
        for i in range(1, forecast_days + 1):
            future_x = last_day + i
            pred = slope * future_x + intercept
            forecast_date = dates[-1] + timedelta(days=i)
            forecast_points.append(ForecastPoint(
                date=forecast_date.strftime("%Y-%m-%d"),
                predicted_cost=round(float(max(pred, 0)), 2),
                lower_bound=round(float(max(pred - 1.96 * std_err, 0)), 2),
                upper_bound=round(float(pred + 1.96 * std_err), 2),
            ))

        predicted_cost = forecast_points[-1].predicted_cost if forecast_points else current_cost

        # Determine trend
        if slope > 0.01:
            trend = "increasing"
        elif slope < -0.01:
            trend = "decreasing"
        else:
            trend = "stable"

        r_squared = 1.0 - np.sum(residuals ** 2) / max(np.sum((y - y_mean) ** 2), 1e-10)

        return CostForecast(
            provider=provider,
            resource_type=resource_type,
            forecast_days=forecast_days,
            current_monthly_cost=round(current_cost * 30, 2),
            predicted_monthly_cost=round(predicted_cost * 30, 2),
            trend=trend,
            confidence=round(max(float(r_squared), 0.0), 2),
            forecast_points=forecast_points,
            savings_potential=round(max(predicted_cost * 30 - current_cost * 30, 0), 2),
        )

    def _forecast_prophet(
        self,
        dates: List[datetime],
        costs: List[float],
        forecast_days: int,
        provider: str,
        resource_type: str,
    ) -> CostForecast:
        """Prophet-based forecast with seasonality."""
        import pandas as pd
        from prophet import Prophet

        df = pd.DataFrame({"ds": dates, "y": costs})

        model = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=True,
            daily_seasonality=False,
            changepoint_prior_scale=0.05,
        )
        model.fit(df)

        future = model.make_future_dataframe(periods=forecast_days)
        forecast = model.predict(future)

        # Extract forecast points
        forecast_points: List[ForecastPoint] = []
        for _, row in forecast.tail(forecast_days).iterrows():
            forecast_points.append(ForecastPoint(
                date=row["ds"].strftime("%Y-%m-%d"),
                predicted_cost=round(float(max(row["yhat"], 0)), 2),
                lower_bound=round(float(max(row["yhat_lower"], 0)), 2),
                upper_bound=round(float(row["yhat_upper"]), 2),
            ))

        current_cost = costs[-1]
        predicted_cost = forecast_points[-1].predicted_cost if forecast_points else current_cost

        trend_val = forecast["trend"].iloc[-1] - forecast["trend"].iloc[0]
        if trend_val > 0.01:
            trend = "increasing"
        elif trend_val < -0.01:
            trend = "decreasing"
        else:
            trend = "stable"

        return CostForecast(
            provider=provider,
            resource_type=resource_type,
            forecast_days=forecast_days,
            current_monthly_cost=round(current_cost * 30, 2),
            predicted_monthly_cost=round(predicted_cost * 30, 2),
            trend=trend,
            confidence=0.85,
            forecast_points=forecast_points,
        )
