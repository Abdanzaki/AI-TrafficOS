"""Unit tests for Phase 5 to Phase 6 routing forecast adapter."""

import pytest

from app.services.routing.forecast_adapter import (
    apply_predictions_to_costs,
    blend_predicted_congestion,
)


def test_blend_predicted_congestion_alpha_weighting():
    """Verify alpha blends base and predicted congestion values accurately."""
    # alpha = 0.5: equal weight
    blended = blend_predicted_congestion(base_congestion=40.0, predicted_congestion=60.0, alpha=0.5)
    assert blended == 50.0

    # alpha = 0.0: purely reactive (uses base only)
    blended_base = blend_predicted_congestion(base_congestion=35.0, predicted_congestion=90.0, alpha=0.0)
    assert blended_base == 35.0

    # alpha = 1.0: purely predictive (uses prediction only)
    blended_pred = blend_predicted_congestion(base_congestion=35.0, predicted_congestion=90.0, alpha=1.0)
    assert blended_pred == 90.0

    # alpha = 0.2: 80% base + 20% predicted
    blended_custom = blend_predicted_congestion(base_congestion=50.0, predicted_congestion=100.0, alpha=0.2)
    assert blended_custom == 60.0


def test_blend_predicted_congestion_none_fallback():
    """Verify missing forecast gracefully returns clamped base congestion."""
    blended = blend_predicted_congestion(base_congestion=42.5, predicted_congestion=None, alpha=0.5)
    assert blended == 42.5


def test_blend_predicted_congestion_alpha_validation():
    """Verify alpha outside [0, 1] raises ValueError."""
    with pytest.raises(ValueError, match="alpha must be between 0.0 and 1.0"):
        blend_predicted_congestion(base_congestion=50.0, predicted_congestion=70.0, alpha=-0.1)

    with pytest.raises(ValueError, match="alpha must be between 0.0 and 1.0"):
        blend_predicted_congestion(base_congestion=50.0, predicted_congestion=70.0, alpha=1.01)


def test_blend_predicted_congestion_clamping():
    """Verify blended congestion results are clamped strictly within [0.0, 100.0]."""
    # Over 100 clamped to 100
    assert blend_predicted_congestion(base_congestion=150.0, predicted_congestion=None) == 100.0
    assert blend_predicted_congestion(base_congestion=110.0, predicted_congestion=120.0, alpha=0.5) == 100.0

    # Negative clamped to 0
    assert blend_predicted_congestion(base_congestion=-15.0, predicted_congestion=None) == 0.0
    assert blend_predicted_congestion(base_congestion=-20.0, predicted_congestion=-5.0, alpha=0.5) == 0.0


def test_apply_predictions_to_costs_direction_and_types():
    """Verify apply_predictions_to_costs scales edge impedances in the documented direction."""
    # 1. Numeric scalar costs
    edge_costs = {
        101: 10.0,  # Has heavy predicted congestion
        102: 10.0,  # Has low predicted congestion
        103: 10.0,  # No prediction available
    }
    predictions = {
        101: 80.0,  # 80% predicted congestion -> blended (0.5 * 80) = 40% -> multiplier 1.8 -> cost 18.0
        102: 10.0,  # 10% predicted congestion -> blended (0.5 * 10) = 5% -> multiplier 1.1 -> cost 11.0
    }

    adjusted = apply_predictions_to_costs(edge_costs, predictions, alpha=0.5)

    assert adjusted[101] > edge_costs[101]
    assert adjusted[102] > edge_costs[102]
    assert adjusted[101] > adjusted[102]  # Higher congestion leads to higher impedance
    assert adjusted[103] == edge_costs[103]  # Missing prediction leaves cost unaffected

    # 2. Tuple link identifiers: (from_id, to_id)
    tuple_costs = {
        (1, 2): 6.0,
        (2, 3): 6.0,
    }
    tuple_preds = {2: 70.0}  # Matches to_id for (1, 2) or from_id for (2, 3)
    adjusted_tuple = apply_predictions_to_costs(tuple_costs, tuple_preds, alpha=0.5)
    assert adjusted_tuple[(1, 2)] > 6.0
    assert adjusted_tuple[(2, 3)] > 6.0

    # 3. Dictionary edge costs with existing 'cost' and 'congestion'
    dict_costs = {
        1: {"cost": 12.0, "congestion": 20.0},
        2: {"cost": 12.0, "congestion": 20.0},
    }
    dict_preds = {1: 80.0}
    adjusted_dict = apply_predictions_to_costs(dict_costs, dict_preds, alpha=0.5)

    # Intersection 1: congestion blends (1-0.5)*20 + 0.5*80 = 50.0
    # Cost scales: 12.0 * (1.0 + (50/100)*2) = 12.0 * 2.0 = 24.0
    assert adjusted_dict[1]["congestion"] == 50.0
    assert adjusted_dict[1]["cost"] == 24.0
    assert adjusted_dict[1]["cost"] > dict_costs[1]["cost"]
    # Intersection 2 untouched
    assert adjusted_dict[2] == dict_costs[2]


def test_apply_predictions_to_costs_alpha_error():
    """Verify invalid alpha in apply_predictions_to_costs raises ValueError."""
    with pytest.raises(ValueError, match="alpha must be between 0.0 and 1.0"):
        apply_predictions_to_costs({1: 5.0}, {1: 50.0}, alpha=-0.5)
