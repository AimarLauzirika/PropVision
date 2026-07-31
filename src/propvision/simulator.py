from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class SimulationConfig:
    num_sims: int = 200000
    modes: Sequence[str] = ("Max", "Average")
    reset_trades: Sequence[int] = tuple(range(0, 20+1))
    # seed: Optional[int] = None


def _float_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0
def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

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
                            reset_price = 0
                        elif reset_price >= price:
                            reset_trades = 0
                        combo = {
                                    "price": float(price),
                                    "mode": mode,
                                    "sl": float(sl),
                                    "tp": float(tp),
                                    "reset_trades": int(reset_trades),
                                    "reset_cost": float(reset_price),
                                }
                        combos.append(combo)

    # Condicionantes:
        # Si no hay e_min_days ni e_min_profit_days el Mode average no se ejecuta
    if _float_or_zero(account['eval1_conditions']['e_min_days']) == 0 and _float_or_zero(account['eval1_conditions']['e_min_profit_days']) == 0:
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
    profit_day_usd = _float_or_zero(account['eval1_conditions'].get("e_profit_day_usd", 0.0))
    activation_cost = _float_or_zero(account['eval1_conditions'].get("activation_fee_usd", 0.0))
    e_mdd_type = account['eval1_conditions'].get("e_mdd_type")
    e_mdd_usd = float(account['eval1_conditions'].get("e_mdd_usd"))
    e_ddd_usd = float(account['eval1_conditions'].get("e_ddd_usd"))
    target_usd = float(account['eval1_conditions'].get("e_target_usd"))
    target_initial = initial_balance + target_usd
    initial_pass_prob = e_mdd_usd / (e_mdd_usd + target_usd)
    # Initial conditions
    mdd = initial_balance - e_mdd_usd
    mdd_used = mdd
    mdd_after = mdd
    balance = initial_balance
    balance_after = initial_balance
    peak_balance = initial_balance
    consistency_pct = account['eval1_conditions'].get("e_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)
    target_consist = 0
    general_commission = max(6.0, max(float(combo.get("tp", 0.0)), float(combo.get("sl", 0.0))) / 500.0 * 6.0)
    commission = general_commission
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
    account_end = False
    passed = False


    while not account_end and combo['sl'] <= e_ddd_usd:
        days += 1
        trades += 1
        days_for_reset += 1
        balance = balance_after

        if trades == 1 or pending_reset:
            balance = initial_balance
            mdd = initial_balance - e_mdd_usd
            mdd_after = mdd
            mdd_used = mdd
            peak_balance = initial_balance
            profits = 0
            pending_reset = False
            trades = 1

        # if pending_reset:


        profit_remaining = target_eval - balance
        trades_remaining = max(0, e_min_days - trades)
        profit_days_remaining = max(0, e_min_profit_days - profits)
        profits_in_profit_days_remaining = profit_days_remaining * profit_day_usd
        if combo["mode"] == "Max":
            tp_used = min(
                combo["tp"], profit_remaining + commission)
            if profit_days_remaining:
                tp_used = max(profit_day_usd + commission, profit_remaining - profits_in_profit_days_remaining + profit_day_usd)
        elif combo["mode"] == "Average":
            tp_used = min(
                combo["tp"],
                (profit_remaining / max(1, trades_remaining, profit_days_remaining)) + commission,
            )
        tp_used = min(tp_used + commission, combo['tp'])
        sl_used = max(0.0, min(combo["sl"], balance - mdd_used))
        tp_used = round(tp_used,2)
        sl_used = round(sl_used,2)

        commission = int(max(6.0, max(tp_used, sl_used)) / 500.0 * 6.0)
        if consistency_pct < 100:
            target_consist = max(target_consist, initial_balance + (tp_used / (consistency_pct / 100)) + general_commission)
        target_eval = max(target_eval, target_consist)
        profit_remaining = target_eval - balance #? Para que se actualice

        prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
        rndm = random.random()
        trade_result = tp_used - commission if rndm < prob_tp else -sl_used - commission

        mdd = mdd_after
        if e_mdd_type == 'trailing':
            mdd_trailing = mdd + round(max(tp_used, sl_used) * random.uniform(0.1, 0.9))
            if mdd_trailing > initial_balance:
                mdd_trailing = initial_balance
        else:
            mdd_trailing = 0
        # if mdd_trailing > balance - e_mdd_usd:
        #     mdd_trailing = mdd
        mdd_used = min(max(mdd, mdd_trailing), initial_balance)
        if e_mdd_type == 'trailing':
            progress = mdd_trailing - mdd
            if balance + progress < mdd + e_mdd_usd:
                mdd_used = mdd
        # if balance + tp_used - e_mdd_usd < mdd_trailing:
        #     mdd_used = mdd
        ddd_failed = e_ddd_usd is not None and trade_result < -e_ddd_usd
        balance_after = balance + trade_result
        mdd_failed = balance_after <= mdd_used
        peak_balance = max(peak_balance, balance_after)
        mdd_after = min(max(mdd, mdd_used, peak_balance - e_mdd_usd), initial_balance)
        if e_mdd_type == "static":
            mdd_after = initial_balance - e_mdd_usd
        new_pass_prob = (balance_after - mdd_after) / (profit_remaining + (balance_after - mdd_after))


        if trade_result >= profit_day_usd:
            profits += 1

        trade_cost = 0.0

        if days == 1:
            trade_cost = price_eval


        # Reset
        can_reset = False
        if reset_cost is not None and reset_cost < price_eval and reset_cost > 0:
            if days_for_reset <= int(combo["reset_trades"]) or subscription_type == "one_time_lifetime":
                can_reset = True
        if can_reset and (balance_after <= mdd_used or ddd_failed):
            resets += 1
            trade_cost += reset_cost
            pending_reset = True

        # Renew
        if subscription_type == "monthly" and days % 20 == 0 and initial_pass_prob < new_pass_prob:
            renews += 1
            trade_cost += price_eval
            days_for_reset = 0



        #? Finales de cuenta
        # Eval pass
        if balance_after >= target_eval and trades >= e_min_days and profits >= e_min_profit_days:
            account_end = True
            trade_cost += activation_cost
            passed = True

        # MDD
        if mdd_failed and not can_reset:
            account_end = True

        # DDD
        if ddd_failed and not can_reset:
            account_end = True

        # Fecha de renew pero sin resultados favorables
        if subscription_type == "monthly" and days % 20 == 0 and initial_pass_prob > new_pass_prob:
            account_end = True

        # Subscription_type 'one_time_30_days'
        if subscription_type == "one_time_30_days" and days >= 20:
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
                "target_eval": target_eval,
                # "profit_remaining": profit_remaining,
                "tp_used": tp_used,
                "sl_used": sl_used,
                "prob_tp": prob_tp,
                "rndm": rndm,
                "trade_result": trade_result,
                "ddd_failed": ddd_failed,
                "mdd_failed": mdd_failed,
                "passed": passed,
                "balance_after": balance_after,
                "peak_balance": peak_balance,
                "mdd_after": mdd_after,
                "traded_days": f"{trades}/{e_min_days}",
                "profit_days": f"{profits}/{e_min_profit_days} (${profit_day_usd})",
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

    data['trades'] = trs
    results['num_evals'] = 1 + resets if e_ddd_usd > combo['sl'] else 0
    results['resets'] = resets if e_ddd_usd > combo['sl'] else 0
    results['renews'] = renews if e_ddd_usd > combo['sl'] else 0
    results['passed'] = int(passed) if e_ddd_usd > combo['sl'] else 0
    results['cost'] = total_cost if e_ddd_usd > combo['sl'] else 0
    results['sim_days'] = days if e_ddd_usd > combo['sl'] else 0
    data['results']= results
    return data


# def simulate_account(account: Dict[str, Any], config: SimulationConfig) -> List[Dict[str, Any]]:
#     # if config.seed is not None:
#     #     random.seed(config.seed)
#     #     np.random.seed(config.seed)

#     combos = _build_combinations(account, config)
#     results: List[Dict[str, Any]] = []
#     consistency_pct = account.get("e_consistency_pct")
#     consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)

#     for combo in combos:
#         num_sims = int(config.num_sims)
#         num_passed = 0
#         num_resets = 0
#         num_renews = 0
#         total_cost = 0.0
#         total_trades = 0
#         breached_streak = 0
#         max_breached_streak = 0
#         cost_streak = 0.0
#         max_cost_streak = 0.0

#         for _ in range(num_sims):
#             balance = float(account.get("initial_balance", 0.0))
#             peak_balance = balance
#             mdd = float(account.get("initial_balance", 0.0)) - float(account.get("e_mdd_usd", 0.0))
#             mdd_used = mdd
#             days = 0
#             trades = 0
#             profit_days = 0
#             total_cost_eval = 0.0
#             passed = False
#             breached = False
#             reset_counter = 0
#             renew_counter = 0
#             trade_count = 0
#             pending_reset = False

#             for _ in range(200):
#                 days += 1
#                 trades += 1
#                 trade_count += 1

#                 if trade_count == 1 or pending_reset:
#                     balance = float(account.get("initial_balance", 0.0))
#                     pending_reset = False
#                 else:
#                     balance = balance

#                 target_eval = max(
#                     float(account.get("e1_target_usd", 0.0)),
#                     float(account.get("initial_balance", 0.0)) + combo["tp"] / (consistency_pct / 100.0)
#                     if consistency_pct is not None and consistency_pct != 100
#                     else 0.0,
#                 )
#                 target_eval = max(float(account.get("e1_target_usd", 0.0)), target_eval)

#                 profit_remaining = target_eval - balance
#                 trades_remaining = max(0, _float_or_zero(account.get("e_min_days")) - trades)
#                 profit_days_remaining = max(0, _float_or_zero(account.get("e_min_profit_days")) - profit_days)

#                 if account.get("e_mdd_type") == "trailing":
#                     mdd_trailing = mdd + combo["tp"] * random.uniform(0.2, 0.5)
#                 else:
#                     mdd_trailing = 0.0
#                 mdd_used = max(mdd, mdd_trailing)

#                 if combo["mode"] == "fixed":
#                     tp_used = min(combo["tp"], (target_eval - balance) + max(6.0, max(combo["tp"], combo["sl"]) / 500.0 * 6.0))
#                 else:
#                     tp_used = min(
#                         combo["tp"],
#                         (profit_remaining / max(1, trades_remaining if trades_remaining > 0 else _float_or_zero(account.get("e_min_days")))) + max(6.0, max(combo["tp"], combo["sl"]) / 500.0 * 6.0),
#                     )

#                 sl_used = min(combo["sl"], balance - mdd_used)
#                 prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
#                 rndm = random.random()
#                 if rndm < prob_tp:
#                     trade_result = tp_used
#                 else:
#                     trade_result = -sl_used

#                 balance_after = balance + trade_result
#                 peak_balance = max(peak_balance, balance_after)
#                 mdd_after = max(mdd_used, peak_balance - float(account.get("e_mdd_usd", 0.0)))
#                 if account.get("e_mdd_type") == "static":
#                     mdd_after = float(account.get("initial_balance", 0.0)) - float(account.get("e_mdd_usd", 0.0))
#                 mdd_after = min(mdd_after, float(account.get("e_highest_mdd_account", 0.0)))

#                 if balance_after <= mdd_used:
#                     breached = True
#                     break

#                 if account.get("e_ddd_usd") is not None and trade_result < -float(account.get("e_ddd_usd", 0.0)):
#                     breached = True
#                     break

#                 if account.get("e_suscription_type") == "one_time_30_days" and days >= 20:
#                     breached = True
#                     break

#                 if days == 20 and (target_eval - balance_after) > (balance_after - mdd_used):
#                     breached = True
#                     break

#                 if balance_after >= target_eval and trades_remaining == 0 and profit_days_remaining == 0:
#                     passed = True
#                     break

#             if passed:
#                 num_passed += 1
#                 max_breached_streak = 0 if max_breached_streak == 0 else max_breached_streak
#             else:
#                 breached_streak += 1
#                 max_breached_streak = max(max_breached_streak, breached_streak)

#             total_trades += trade_count
#             total_cost += 0.0
#             num_resets += 0
#             num_renews += 0

#         results.append(
#             {
#                 "price": combo["price"],
#                 "mode": combo["mode"],
#                 "reset_trades": combo["reset_trades"],
#                 "tp": combo["tp"],
#                 "sl": combo["sl"],
#                 "num_sims": num_sims,
#                 "num_evals": num_sims + num_resets,
#                 "num_passed": num_passed,
#                 "prob_pass": num_passed / num_sims if num_sims else 0.0,
#                 "num_resets": num_resets,
#                 "num_renews": num_renews,
#                 "cost_total": total_cost,
#                 "cost_pass": total_cost / num_passed if num_passed else float("inf"),
#                 "cost_fund": total_cost + float(account.get("activation_fee_usd", 0.0)) if account.get("activation_fee_type") == "always" else total_cost,
#                 "trades_avg": total_trades / num_sims if num_sims else 0.0,
#                 "breached_streak": max_breached_streak,
#                 "cost_streak": max_cost_streak,
#             }
#         )
#     return results
