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
    reset_prices = account['eval1_conditions'].get("reset_prices")
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
    eval_prices = account['eval1_conditions'].get("eval_prices")
    reset_prices = account['eval1_conditions'].get("reset_prices")
    combos: List[Dict[str, Any]] = []
    for price_index, price in enumerate(eval_prices):
        if reset_prices != None:
            if len(reset_prices) > 1:
                reset_price = reset_prices[price_index]
            elif len(reset_prices) == 1:
                reset_price = reset_prices[0]

        for mode in config.modes:
            for sl in account["eval1_conditions"].get("e_sls_usd"):
                for tp in account["eval1_conditions"].get("e_tps_usd"):
                    for reset_trades in config.reset_trades:
                        # Si no hay resets reset_trades será 0
                        if reset_prices == None:
                            reset_trades = 0
                        elif reset_price >= price:
                            reset_trades = 0
                        combo = {
                                    "price": float(price),
                                    "mode": mode,
                                    "sl": float(sl),
                                    "tp": float(tp),
                                    "reset_trades": int(reset_trades),
                                }
                        combos.append(combo)

    # Condicionantes:
        # Si no hay e_min_days ni e_min_profit_days el Mode average no se ejecuta
    if _int_or_zero(account['eval1_conditions']['e_min_days']) == 0 and _int_or_zero(account['eval1_conditions']['e_min_profit_days']) == 0:
        combos = [combo for combo in combos if combo['mode'] != 'Average']
    
    # Eliminar repetidos
    lista_unica = []
    vistos = set()
    for combo in combos:
        tupla_hashable = tuple(sorted(combo.items()))
        
        if tupla_hashable not in vistos:
            vistos.add(tupla_hashable)
            lista_unica.append(combo)

    combos = lista_unica
    print(f'{len(combos)} combinaciones')

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


def simulate_eval(account: Dict[str, Any], combo: Dict[str, Any], seed: Optional[int] = None) -> List[Dict[str, Any]]:
    # if seed is not None:
    #     random.seed(seed)
    #     np.random.seed(seed)

    data: Dict = {}
    trs: List[Dict[str, Any]] = []
    results: Dict = {}
    # General conditions
    initial_balance = float(account.get("initial_balance"))
    price_eval = float(combo.get("price"))
    subscription_type = account['eval1_conditions'].get("e_suscription_type")
    reset_cost = _get_reset_cost(account, price_eval, _coerce_list(account['eval1_conditions'].get("eval_prices")))
    e_min_days = _int_or_zero(account['eval1_conditions'].get("e_min_days"))
    e_min_profit_days = _int_or_zero(account['eval1_conditions'].get("e_min_profit_days"))
    profit_day_usd = float(account['eval1_conditions'].get("a_profit_day_usd", 0.0)) if account['eval1_conditions'].get("a_profit_day_usd") is not None else 0.0
    activation_cost = float(account['eval1_conditions'].get("activation_fee_usd", 0.0)) if account['eval1_conditions'].get("activation_fee_usd") is not None else 0.0
    a_mdd_usd = float(account['eval1_conditions'].get("e_mdd_usd"))
    target_usd = float(account['eval1_conditions'].get("e_target_usd"))
    target_initial = initial_balance + target_usd
    initial_pass_prob = a_mdd_usd / (a_mdd_usd + target_usd)
    # Initial conditions
    mdd = initial_balance - a_mdd_usd
    mdd_after = mdd
    balance = initial_balance
    balance_after = initial_balance
    peak_balance = balance
    consistency_pct = account['eval1_conditions'].get("e_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)
    # target_consist = initial_balance + float(combo.get("tp", 0.0)) / (consistency_pct / 100.0) if consistency_pct != 100.0 else initial_balance
    target_consist = 0
    general_commission = max(6.0, max(float(combo.get("tp", 0.0)), float(combo.get("sl", 0.0))) / 500.0 * 6.0)
    target_eval = max(target_initial + general_commission, target_consist + general_commission)
    profit_remaining = (target_eval + general_commission) - balance
    days = 0
    trades = 0
    profits = 0
    days_for_reset = 0
    resets = 0
    renews = 0
    total_cost = 0.0
    pending_reset = False
    # last_mdd_after = mdd
    account_end = False


    while not account_end:
        days += 1
        trades += 1
        days_for_reset += 1
        balance = balance_after

        if trades == 1 or pending_reset:
            mdd = initial_balance - a_mdd_usd
        else:
            mdd = last_mdd_after

        if pending_reset:
            balance = initial_balance
            peak_balance = balance
            trades = 1
            profits = 0
            pending_reset = False


        profit_remaining = target_eval - balance_after
        if combo["mode"] == "Max":
            tp_used = min(combo["tp"], profit_remaining + general_commission)
        elif combo["mode"] == "Average":
            trades_remaining = max(0, e_min_days - trades)
            profits_remaining = max(0, e_min_days - profits)
            tp_used = min(
                combo["tp"],
                (profit_remaining / max(1, trades_remaining, profits_remaining)),
            )
        sl_used = max(0.0, min(combo["sl"], balance - mdd))
        tp_used = round(tp_used,2)
        sl_used = round(sl_used,2)

        commission = int(max(6.0, max(tp_used, sl_used)) / 500.0 * 6.0)
        target_consist = max(target_consist, initial_balance + (tp_used / (consistency_pct / 100)) + general_commission)
        target_eval = max(target_eval, target_consist)

        prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
        rndm = random.random()
        trade_result = tp_used - commission if rndm < prob_tp else -sl_used - commission

        mdd_trailing = mdd + max(tp_used, sl_used) * random.uniform(0.1, 0.9) if account['eval1_conditions'].get("e_mdd_type") == "trailing" else 0.0
        mdd_used = min(max(mdd, mdd_trailing), initial_balance)
        ddd_failed = account['eval1_conditions'].get("e_ddd_usd") is not None and trade_result < -float(account['eval1_conditions'].get("e_ddd_usd"))
        balance_after = balance + trade_result
        peak_balance = max(peak_balance, balance_after)
        mdd_after = min(max(mdd, peak_balance - a_mdd_usd), initial_balance)
        if account['eval1_conditions'].get("e_mdd_type") == "static":
            mdd_after = initial_balance - a_mdd_usd
        # mdd_after = min(mdd_after, float(account['eval1_conditions'].get("e_highest_mdd_account", 0.0)))
        new_pass_prob = (balance_after - mdd_after) / (profit_remaining + (balance_after - mdd_after))


        if trade_result > profit_day_usd:
            profits += 1

        trade_cost = 0.0

        if days == 1:
            trade_cost = price_eval

        # Reset
        can_reset = reset_cost is not None and reset_cost < price_eval and days_for_reset <= int(combo["reset_trades"])
        if can_reset and (balance_after <= mdd or ddd_failed):
            resets += 1
            trade_cost += reset_cost
            pending_reset = True

        # Renew
        if subscription_type == "monthly" and days % 20 == 0 and initial_pass_prob < new_pass_prob:
            renews += 1
            trade_cost += price_eval
            days_for_reset = 0

        # profit_days = f"{profits}/{e_min_profit_days} (${profit_day_usd:.0f})"
        # if profits == 0 and reset:
        #     profit_days = f"0/{e_min_profit_days} (${profit_day_usd:.0f})"

        # if balance_after >= target_eval and trades >= e_min_days and profits >= e_min_profit_days:
        #     if account.get("activation_fee_type") == "always" and activation_cost > 0:
        #         trade_cost += activation_cost


        #? Finales de cuenta

        # Eval pass
        if balance_after >= target_eval and trades >= e_min_days and profits >= e_min_profit_days:
            account_end = True
            trade_cost += activation_cost


        # MDD
        if balance_after <= mdd_used and not can_reset:
            account_end = True

        # Fecha de renew pero sin resultados favorables
        if subscription_type == "monthly" and days % 20 == 0 and initial_pass_prob > new_pass_prob:
            account_end = True


        # De seguridad
        if days >= 300:
            account_end = True

        total_cost += trade_cost

        trs.append(
            {
                "days": days,
                # "mdd": mdd,
                # "mdd_trailing": mdd_trailing,
                "mdd_used": mdd_used,
                "balance": balance,
                # "target_consist": target_consist,
                # "target_eval": target_eval,
                # "profit_remaining": profit_remaining,
                "tp_used": tp_used,
                "sl_used": sl_used,
                "prob_tp": prob_tp,
                "rndm": rndm,
                "trade_result": trade_result,
                "ddd_failed": ddd_failed,
                "balance_after": balance_after,
                # "peak_balance": peak_balance,
                "mdd_after": mdd_after,
                "traded_days": f"{trades}/{e_min_days}",
                "profit_days": f"{profits}/{e_min_profit_days} (${profit_day_usd:.0f})",
                # "days_for_reset": days_for_reset,
                "can_reset": can_reset,
                "resets": resets,
                # "initial_pass_prob": initial_pass_prob,
                # "new_pass_prob": new_pass_prob,
                "renews": renews,
                "cost": trade_cost,
                "cost_total": total_cost,
            }
        )

        balance = balance_after
        last_mdd_after = mdd_after

    data['trades'] = trs
    data['results']= results
    return data


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
