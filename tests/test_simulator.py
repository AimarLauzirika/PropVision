import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.propvision.data import _format_account_name
from src.propvision.simulator import SimulationConfig, build_example_context, simulate_account, simulate_example


def test_simulate_account_returns_expected_summary_fields():
    account = {
        "id": 1,
        "name": "Demo",
        "company_id": 1,
        "initial_balance": 10000,
        "e1_target_usd": 12000,
        "e_mdd_type": "static",
        "a_mdd_usd": 8000,
        "e_ddd_usd": None,
        "e_highest_mdd_account": 9000,
        "e_consistency_pct": None,
        "e_min_days": 5,
        "e_min_profit_days": 0,
        "a_profit_day_usd": 50,
        "e_suscription_type": "one_time_30_days",
        "activation_fee_usd": 100,
        "activation_fee_type": "always",
        "e_tps_usd": [100, 150],
        "e_sls_usd": [100, 150],
        "reset_prices": None,
        "eval_prices": [50, 75],
    }

    config = SimulationConfig(num_sims=50, modes=["fixed"], reset_trades=[0], seed=7)
    results = simulate_account(account, config)

    assert len(results) > 0
    first = results[0]
    assert first["price"] == 50
    assert first["mode"] == "fixed"
    assert first["reset_trades"] == 0
    assert first["num_sims"] == 50
    assert first["num_evals"] >= first["num_sims"]
    assert first["prob_pass"] >= 0.0
    assert first["cost_fund"] >= 0.0


def test_simulate_example_returns_trade_log():
    account = {
        "id": 2,
        "name": "Demo2",
        "company_id": 1,
        "initial_balance": 10000,
        "e1_target_usd": 12000,
        "e_mdd_type": "static",
        "a_mdd_usd": 8000,
        "e_ddd_usd": None,
        "e_highest_mdd_account": 9000,
        "e_consistency_pct": None,
        "e_min_days": 5,
        "e_min_profit_days": 0,
        "a_profit_day_usd": 50,
        "e_suscription_type": "one_time_30_days",
        "activation_fee_usd": 100,
        "activation_fee_type": "always",
        "e_tps_usd": [100],
        "e_sls_usd": [100],
        "reset_prices": None,
        "eval_prices": [75],
    }

    combo = {"price": 75, "mode": "fixed", "sl": 100, "tp": 100, "reset_trades": 0}
    trades = simulate_example(account, combo, seed=11)

    assert len(trades) > 0
    first = trades[0]
    assert "trade_result" in first
    assert "balance_after" in first
    assert "ddd_failed" in first
    assert "traded_days" in first
    assert first["traded_days"] == "1/5"
    assert "profits" in first
    assert "profit_days" in first
    assert "resets" in first
    assert "renews" in first
    assert "cost" in first
    assert "cost_total" in first
    assert first["profit_days"].endswith("($50)")


def test_build_example_context_includes_combo_metadata():
    account = {
        "id": 3,
        "name": "Demo3",
        "company_id": 1,
        "initial_balance": 10000,
        "e1_target_usd": 12000,
        "e_mdd_type": "static",
        "a_mdd_usd": 8000,
        "e_ddd_usd": 600,
        "e_highest_mdd_account": 9000,
        "e_consistency_pct": 40,
        "e_min_days": 5,
        "e_min_profit_days": 2,
        "activation_fee_usd": 100,
        "activation_fee_type": "always",
        "reset_prices": [50, 75],
        "eval_prices": [50, 75],
    }
    combo = {"price": 75, "mode": "fixed", "sl": 100, "tp": 100, "reset_trades": 0}

    context = build_example_context(account, combo)

    assert context["price_eval"] == 75
    assert context["reset_cost"] == 75
    assert context["commission"] == 6
    assert context["target_initial"] == 12000
    assert context["target_consist"] == 10250
    assert context["target_eval"] == 12000
    assert context["activation_cost"] == 100


def test_format_account_name_includes_company_and_account_ids():
    account = {"id": 7, "name": "My Account", "company_id": 3, "company": {"id": 3, "short_name": "E2T"}}
    assert _format_account_name(account) == "E2T (3) - My Account (7)"
