from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

@dataclass(frozen=True)
class SimulationConfig:
    num_sims: int = 200000
    modes: Sequence[str] = ("Max", "Average")
    reset_trades: Sequence[int] = tuple(range(5, 20))
    # seed: Optional[int] = None


def _coerce_list(value: Any) -> List[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, np.ndarray)):
        return [float(item) for item in value]
    return [float(value)]


def _get_reset_cost(account: Dict[str, Any], price_eval: float, eval_prices: Sequence[float]) -> Optional[float]:
    reset_prices = account.get("reset_prices")
    if reset_prices is None:
        return None

    values = _coerce_list(reset_prices)
    if len(values) == 1:
        return values[0]

    if not values:
        return None

    try:
        index = int(eval_prices.index(price_eval))
    except ValueError:
        index = 0
    return values[index] if index < len(values) else values[-1]


def _build_combinations(account: Dict[str, Any], config: SimulationConfig) -> List[Dict[str, Any]]:
    eval_prices = _coerce_list(account.get("eval_prices"))
    if not eval_prices:
        eval_prices = [account.get("e1_target_usd", 0.0)]

    combos: List[Dict[str, Any]] = []
    for price in eval_prices:
        for mode in config.modes:
            for sl in _coerce_list(account.get("e_sls_usd")):
                for tp in _coerce_list(account.get("e_tps_usd")):
                    for reset_trades in config.reset_trades:
                        combos.append(
                            {
                                "price": float(price),
                                "mode": mode,
                                "sl": float(sl),
                                "tp": float(tp),
                                "reset_trades": int(reset_trades),
                            }
                        )
    return combos


def build_example_context(account: Dict[str, Any], combo: Dict[str, Any]) -> Dict[str, Any]:
    initial_balance = float(account.get("initial_balance", 0.0))
    consistency_pct = account.get("e_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)

    target_initial = float(account.get("e1_target_usd", 0.0))
    target_consist = initial_balance + float(combo.get("tp", 0.0)) / (consistency_pct / 100.0) if consistency_pct != 100.0 else initial_balance
    target_eval = max(target_initial, target_consist)

    return {
        "price_eval": float(combo.get("price", 0.0)),
        "reset_cost": _get_reset_cost(account, float(combo.get("price", 0.0)), _coerce_list(account.get("eval_prices"))),
        "commission": max(6.0, max(float(combo.get("tp", 0.0)), float(combo.get("sl", 0.0))) / 500.0 * 6.0),
        "target_initial": target_initial,
        "target_consist": target_consist,
        "target_eval": target_eval,
        "activation_cost": float(account.get("activation_fee_usd", 0.0)) if account.get("activation_fee_usd") is not None else 0.0,
    }


def simulate_example(account: Dict[str, Any], combo: Dict[str, Any], seed: Optional[int] = None) -> List[Dict[str, Any]]:
    # if seed is not None:
    #     random.seed(seed)
    #     np.random.seed(seed)

    trades: List[Dict[str, Any]] = []
    initial_balance = float(account.get("initial_balance", 0.0))
    a_mdd_usd = float(account.get("a_mdd_usd", 0.0))
    mdd = initial_balance - a_mdd_usd
    balance = initial_balance
    balance_after = initial_balance
    peak_balance = balance
    consistency_pct = account.get("e_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)
    target_initial = float(account.get("e1_target_usd", 0.0))
    target_consist = initial_balance + float(combo.get("tp", 0.0)) / (consistency_pct / 100.0) if consistency_pct != 100.0 else initial_balance
    target_eval = max(target_initial, target_consist)
    price_eval = float(combo.get("price", 0.0))
    reset_cost = _get_reset_cost(account, price_eval, _coerce_list(account.get("eval_prices")))
    commission = max(6.0, max(float(combo.get("tp", 0.0)), float(combo.get("sl", 0.0))) / 500.0 * 6.0)
    profit_threshold = float(account.get("a_profit_day_usd", 0.0)) if account.get("a_profit_day_usd") is not None else 0.0
    e_min_days = _int_or_zero(account.get("e_min_days"))
    e_min_profit_days = _int_or_zero(account.get("e_min_profit_days"))
    activation_cost = float(account.get("activation_fee_usd", 0.0)) if account.get("activation_fee_usd") is not None else 0.0
    subscription_type = account.get("e_suscription_type")

    days = 0
    trades_count = 0
    trades_for_reset_count = 0
    profits = 0
    total_cost = 0.0
    resets = 0
    renews = 0
    pending_reset = False
    last_mdd_after = mdd

    for _ in range(20):
        days += 1
        trades_count += 1
        trades_for_reset_count += 1
        balance = balance_after

        if trades_count == 1 or pending_reset:
            mdd = initial_balance - a_mdd_usd
        else:
            mdd = last_mdd_after

        if pending_reset:
            balance = initial_balance
            peak_balance = balance
            trades_count = 1
            profits = 0
            pending_reset = False

        profit_remaining = target_eval - balance
        traded_days = f"{trades_count}/{e_min_days}"

        if combo["mode"] == "fixed":
            tp_used = min(combo["tp"], (target_eval - balance) + commission)
        else:
            trades_remaining = max(0, e_min_days - trades_count)
            tp_used = min(
                combo["tp"],
                (profit_remaining / max(1, trades_remaining if trades_remaining > 0 else max(1, e_min_days))) + commission,
            )

        # tp_used = tp_target
        sl_used = max(0.0, min(combo["sl"], balance - mdd))
        prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
        rndm = random.random()
        trade_result = tp_used - commission if rndm < prob_tp else -sl_used - commission
        mdd_trailing = mdd + max(tp_used, sl_used) * random.uniform(0.1, 0.9) if account.get("e_mdd_type") == "trailing" else 0.0
        mdd_used = min(max(mdd, mdd_trailing), float(account.get("e_highest_mdd_account", 0.0)))
        ddd_failed = account.get("e_ddd_usd") is not None and trade_result < -float(account.get("e_ddd_usd", 0.0))
        balance_after = balance + trade_result
        peak_balance = max(peak_balance, balance_after)
        mdd_after = min(max(mdd, peak_balance - a_mdd_usd), float(account.get("e_highest_mdd_account", 0.0)))
        if account.get("e_mdd_type") == "static":
            mdd_after = initial_balance - a_mdd_usd
        # mdd_after = min(mdd_after, float(account.get("e_highest_mdd_account", 0.0)))

        if ddd_failed or balance_after <= mdd:
            breached = True
        else:
            breached = False

        if trade_result > profit_threshold:
            profits += 1

        renewed = False
        reset = False
        trade_cost = 0.0

        if days == 1:
            trade_cost = price_eval

        if subscription_type == "monthly" and days % 20 == 0 and (target_eval - balance) < (balance - mdd):
            renewed = True
            renews += 1
            trade_cost += price_eval
            trades_for_reset_count = 0

        can_reset = reset_cost is not None and reset_cost < price_eval
        if can_reset and (balance_after <= mdd or ddd_failed) and trades_for_reset_count <= int(combo["reset_trades"]):
            reset = True
            resets += 1
            trade_cost += reset_cost
            pending_reset = True
            trades_for_reset_count = 0

        trades_for_reset = trades_for_reset_count
        profit_days = f"{profits}/{e_min_profit_days} (${profit_threshold:.0f})"
        if profits == 0 and reset:
            profit_days = f"0/{e_min_profit_days} (${profit_threshold:.0f})"

        if balance_after >= target_eval and trades_count >= e_min_days and profits >= e_min_profit_days:
            if account.get("activation_fee_type") == "always" and activation_cost > 0:
                trade_cost += activation_cost

        total_cost += trade_cost

        trades.append(
            {
                "days": days,
                "mdd": mdd,
                "mdd_trailing": mdd_trailing,
                # "mdd_used": mdd_used,
                "balance": balance,
                # "profit_remaining": profit_remaining,
                "tp_used": tp_used,
                "sl_used": sl_used,
                "prob_tp": prob_tp,
                "rndm": rndm,
                "trade_result": trade_result,
                "ddd_failed": ddd_failed,
                "balance_after": balance_after,
                "peak_balance": peak_balance,
                "mdd_after": mdd_after,
                "trades": trades_count,
                "traded_days": traded_days,
                "profits": profits,
                "profit_days": profit_days,
                "trades_for_reset": trades_for_reset,
                "resets": resets,
                "renews": renews,
                "cost": trade_cost,
                "cost_total": total_cost,
            }
        )

        balance = balance_after
        last_mdd_after = mdd_after

        if reset:
            balance = initial_balance

        if reset or renewed:
            trades_for_reset_count = 0

    return trades


def simulate_account(account: Dict[str, Any], config: SimulationConfig) -> List[Dict[str, Any]]:
    # if config.seed is not None:
    #     random.seed(config.seed)
    #     np.random.seed(config.seed)

    combos = _build_combinations(account, config)
    results: List[Dict[str, Any]] = []
    consistency_pct = account.get("e_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)

    for combo in combos:
        num_sims = int(config.num_sims)
        num_passed = 0
        num_resets = 0
        num_renews = 0
        total_cost = 0.0
        total_trades = 0
        breached_streak = 0
        max_breached_streak = 0
        cost_streak = 0.0
        max_cost_streak = 0.0

        for _ in range(num_sims):
            balance = float(account.get("initial_balance", 0.0))
            peak_balance = balance
            mdd = float(account.get("initial_balance", 0.0)) - float(account.get("a_mdd_usd", 0.0))
            mdd_used = mdd
            days = 0
            trades = 0
            profit_days = 0
            total_cost_eval = 0.0
            passed = False
            breached = False
            reset_counter = 0
            renew_counter = 0
            trade_count = 0
            pending_reset = False

            for _ in range(200):
                days += 1
                trades += 1
                trade_count += 1

                if trade_count == 1 or pending_reset:
                    balance = float(account.get("initial_balance", 0.0))
                    pending_reset = False
                else:
                    balance = balance

                target_eval = max(
                    float(account.get("e1_target_usd", 0.0)),
                    float(account.get("initial_balance", 0.0)) + combo["tp"] / (consistency_pct / 100.0)
                    if consistency_pct is not None and consistency_pct != 100
                    else 0.0,
                )
                target_eval = max(float(account.get("e1_target_usd", 0.0)), target_eval)

                profit_remaining = target_eval - balance
                trades_remaining = max(0, _int_or_zero(account.get("e_min_days")) - trades)
                profit_days_remaining = max(0, _int_or_zero(account.get("e_min_profit_days")) - profit_days)

                if account.get("e_mdd_type") == "trailing":
                    mdd_trailing = mdd + combo["tp"] * random.uniform(0.2, 0.5)
                else:
                    mdd_trailing = 0.0
                mdd_used = max(mdd, mdd_trailing)

                if combo["mode"] == "fixed":
                    tp_used = min(combo["tp"], (target_eval - balance) + max(6.0, max(combo["tp"], combo["sl"]) / 500.0 * 6.0))
                else:
                    tp_used = min(
                        combo["tp"],
                        (profit_remaining / max(1, trades_remaining if trades_remaining > 0 else _int_or_zero(account.get("e_min_days")))) + max(6.0, max(combo["tp"], combo["sl"]) / 500.0 * 6.0),
                    )

                sl_used = min(combo["sl"], balance - mdd_used)
                prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
                rndm = random.random()
                if rndm < prob_tp:
                    trade_result = tp_used
                else:
                    trade_result = -sl_used

                balance_after = balance + trade_result
                peak_balance = max(peak_balance, balance_after)
                mdd_after = max(mdd_used, peak_balance - float(account.get("a_mdd_usd", 0.0)))
                if account.get("e_mdd_type") == "static":
                    mdd_after = float(account.get("initial_balance", 0.0)) - float(account.get("a_mdd_usd", 0.0))
                mdd_after = min(mdd_after, float(account.get("e_highest_mdd_account", 0.0)))

                if balance_after <= mdd_used:
                    breached = True
                    break

                if account.get("e_ddd_usd") is not None and trade_result < -float(account.get("e_ddd_usd", 0.0)):
                    breached = True
                    break

                if account.get("e_suscription_type") == "one_time_30_days" and days >= 20:
                    breached = True
                    break

                if days == 20 and (target_eval - balance_after) > (balance_after - mdd_used):
                    breached = True
                    break

                if balance_after >= target_eval and trades_remaining == 0 and profit_days_remaining == 0:
                    passed = True
                    break

            if passed:
                num_passed += 1
                max_breached_streak = 0 if max_breached_streak == 0 else max_breached_streak
            else:
                breached_streak += 1
                max_breached_streak = max(max_breached_streak, breached_streak)

            total_trades += trade_count
            total_cost += 0.0
            num_resets += 0
            num_renews += 0

        results.append(
            {
                "price": combo["price"],
                "mode": combo["mode"],
                "reset_trades": combo["reset_trades"],
                "tp": combo["tp"],
                "sl": combo["sl"],
                "num_sims": num_sims,
                "num_evals": num_sims + num_resets,
                "num_passed": num_passed,
                "prob_pass": num_passed / num_sims if num_sims else 0.0,
                "num_resets": num_resets,
                "num_renews": num_renews,
                "cost_total": total_cost,
                "cost_pass": total_cost / num_passed if num_passed else float("inf"),
                "cost_fund": total_cost + float(account.get("activation_fee_usd", 0.0)) if account.get("activation_fee_type") == "always" else total_cost,
                "trades_avg": total_trades / num_sims if num_sims else 0.0,
                "breached_streak": max_breached_streak,
                "cost_streak": max_cost_streak,
            }
        )
    return results
