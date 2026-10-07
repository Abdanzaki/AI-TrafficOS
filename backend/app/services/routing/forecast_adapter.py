"""Forecast routing adapter module.

Bridges Phase 5 predictive inference outputs with Phase 3 routing cost functions.
Provides pure transformation functions to blend instantaneous real-time congestion
with forward-looking ML forecasts (H=30m), adjusting edge traversal impedances.

Architectural seam:
    This adapter represents the exact contract and seam that Phase 6 (Autonomous
    Routing & Dynamic Network Optimization) will invoke immediately prior to
    instantiating Dijkstra or A* shortest-path graph searches.
"""

from typing import Any, Optional, Union


def blend_predicted_congestion(
    base_congestion: float,
    predicted_congestion: Optional[float],
    alpha: float = 0.5,
) -> float:
    """Compute an alpha-weighted blend between real-time base congestion and ML forecast.

    Traffic-engineering rationale:
        Pure reactive routing suffers from oscillation and herding onto currently
        clear corridors that will become saturated by the time a vehicle arrives.
        Conversely, pure predictive routing risks overreacting to noisy forecasts.
        An alpha-weighted convex combination balances current ground-truth telemetry
        with 30-minute predictive lookahead:
            blended = (1.0 - alpha) * base + alpha * predicted

    Args:
        base_congestion: Current observed congestion percentage in [0.0, 100.0].
        predicted_congestion: Forecasted congestion percentage in [0.0, 100.0],
            or None if no predictive forecast is available for this segment.
        alpha: Weight assigned to the predictive forecast in [0.0, 1.0].
            - alpha = 0.0: Purely reactive (uses base congestion only).
            - alpha = 0.5: Equal balance between current state and forecast.
            - alpha = 1.0: Purely predictive.

    Returns:
        Blended congestion score clamped to [0.0, 100.0].

    Raises:
        ValueError: If alpha is outside the closed interval [0.0, 1.0].
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be between 0.0 and 1.0, got {alpha}")

    if predicted_congestion is None:
        return max(0.0, min(100.0, float(base_congestion)))

    blend = (1.0 - alpha) * float(base_congestion) + alpha * float(predicted_congestion)
    return max(0.0, min(100.0, float(blend)))


def apply_predictions_to_costs(
    edge_costs: dict[Any, Any],
    predictions: dict[int, float],
    alpha: float = 0.5,
) -> dict[Any, Any]:
    """Adjust road network edge traversal costs using predictive congestion forecasts.

    Architectural seam:
        This is the primary seam Phase 6 will call before executing Dijkstra or A*
        pathfinding. Given a precomputed baseline cost map (e.g. from instantaneous
        traffic records or free-flow calculations) and a dictionary of predicted
        congestion levels keyed by road or intersection ID, this function returns a
        new cost mapping incorporating expected future impedance.

    Traffic-engineering rationale:
        Corridors expected to experience bottleneck growth over the next 30 minutes
        receive an elevated generalized impedance penalty, discouraging route plans
        from routing high-priority traffic into impending gridlock.

    Args:
        edge_costs: Mapping of edge identifiers (road ID int, tuple (from_id, to_id),
            or Edge object) to baseline cost (float minutes, or dict with cost/congestion).
        predictions: Mapping of road ID or intersection ID to forecasted congestion (0-100).
        alpha: Blending weight in [0.0, 1.0] passed to blend_predicted_congestion.

    Returns:
        A new dictionary with adjusted impedance costs. Pure function, no DB or side effects.

    Raises:
        ValueError: If alpha is outside [0.0, 1.0].
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be between 0.0 and 1.0, got {alpha}")

    adjusted_costs: dict[Any, Any] = {}

    for key, cost_val in edge_costs.items():
        # Match edge key to prediction target (road_id or junction node)
        pred_congestion: Optional[float] = None

        if key in predictions:
            pred_congestion = predictions[key]
        elif isinstance(key, tuple):
            # For link tuple (from_id, to_id), check downstream junction first, then upstream
            if len(key) >= 2 and key[1] in predictions:
                pred_congestion = predictions[key[1]]
            elif len(key) >= 1 and key[0] in predictions:
                pred_congestion = predictions[key[0]]
        elif hasattr(key, "road_id") and key.road_id in predictions:
            pred_congestion = predictions[key.road_id]
        elif hasattr(key, "to_id") and key.to_id in predictions:
            pred_congestion = predictions[key.to_id]

        if pred_congestion is None:
            adjusted_costs[key] = cost_val
            continue

        if isinstance(cost_val, (int, float)):
            base_cost = float(cost_val)
            # Scaling multiplier: base free-flow/delay cost scaled by blended forecast
            blended_cong = blend_predicted_congestion(0.0, pred_congestion, alpha=alpha)
            congestion_multiplier = 1.0 + (blended_cong / 100.0) * 2.0
            adjusted_costs[key] = round(base_cost * congestion_multiplier, 4)
        elif isinstance(cost_val, dict):
            new_dict = dict(cost_val)
            base_cost = float(cost_val.get("cost", 0.0))
            base_cong = float(cost_val.get("congestion", 0.0))
            blended_cong = blend_predicted_congestion(base_cong, pred_congestion, alpha=alpha)
            new_dict["congestion"] = round(blended_cong, 2)
            if "cost" in cost_val:
                congestion_multiplier = 1.0 + (blended_cong / 100.0) * 2.0
                new_dict["cost"] = round(base_cost * congestion_multiplier, 4)
            adjusted_costs[key] = new_dict
        else:
            adjusted_costs[key] = cost_val

    return adjusted_costs
