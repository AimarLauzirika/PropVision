from __future__ import annotations

import ast
import re
import os
from pathlib import Path
import csv
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Literal
from .db import supabase
import numpy as np


@dataclass(frozen=True)
class SimulationConfig:
    num_sims: int = 200000
    modes: Sequence[str] = ("Max", "Average")
    reset_trades: Sequence[int] = tuple(range(0, 20+1))

@dataclass(frozen=True)
class FundedSimulationConfig:
    num_sims: int = 200000
    tp_modes: Sequence[str] = ("Full", "Calculate", "Average")
    payout_modes: Sequence[str] = ("Min", "Max")


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
                        # Sólo pares
                        if not reset_trades % 2 == 0:
                            continue
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
    # print(f'{len(combos)} combinaciones')

    return combos

def _build_funded_combinations(account: Dict[str, Any], config: FundedSimulationConfig) -> List[Dict[str, Any]]:
    f_personal_targets_usd = _coerce_list(account['funded_conditions'].get("f_personal_targets_usd")) if _coerce_list(account['funded_conditions'].get("f_personal_targets_usd")) else [0]
    margins_after_withdrawal = _coerce_list(account['funded_conditions'].get("margins_after_withdrawal")) if _coerce_list(account['funded_conditions'].get("margins_after_withdrawal")) else [0]
    combos: List[Dict[str, Any]] = []
    for pTarget in f_personal_targets_usd:
        for margin in margins_after_withdrawal:
            for payout_mode in config.payout_modes:
                for tp_mode in config.tp_modes:
                    for sl in account["funded_conditions"].get("f_sls_usd"):
                        for tp in account["funded_conditions"].get("f_tps_usd"):
                            combo = {
                                        "personal_target": int(pTarget),
                                        "margin": int(margin),
                                        "payout_mode": payout_mode,
                                        "tp_mode": tp_mode,
                                        "sl": int(sl),
                                        "tp": int(tp),
                                    }
                            combos.append(combo)

    # Condicionantes:
        # Si no hay e_min_days ni e_min_profit_days el Mode average no se ejecuta
    if _float_or_zero(account['funded_conditions']['f_min_days']) == 0 and _float_or_zero(account['funded_conditions']['f_min_profit_days']) == 0:
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


def simulate_eval(account: Dict[str, Any], combo: Dict[str, Any]) -> List[Dict[str, Any]]:

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
    e_mdd_usd = account['eval1_conditions'].get("e_mdd_usd")
    e_ddd_usd = account['eval1_conditions'].get("e_ddd_usd") if account['eval1_conditions'].get("e_ddd_usd") else initial_balance
    ddd_soft_breach = account['company']['ddd_soft_breach']
    target_usd = account['eval1_conditions'].get("e_target_usd")
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

    while not account_end and e_ddd_usd >= combo["sl"]:
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
        ddd_failed = trade_result < -e_ddd_usd and not ddd_soft_breach
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
    results['num_evals'] = 1 + resets
    results['resets'] = resets
    results['renews'] = renews
    results['passed'] = int(passed)
    results['cost'] = total_cost
    results['sim_days'] = days
    data['results']= results
    return data

def simulate_funded(account: Dict[str, Any], combo: Dict[str, Any]) -> List[Dict[str, Any]]:

    data: Dict = {}
    trs: List[Dict[str, Any]] = []
    results: Dict = {}
    # General conditions
    initial_balance = float(account.get("initial_balance"))
    subscription_type = account['funded_conditions'].get("f_suscription_type")
    f_min_days = _int_or_zero(account['funded_conditions'].get("f_min_days"))
    f_min_profit_days = _int_or_zero(account['funded_conditions'].get("f_min_profit_days"))
    profit_day_usd = _float_or_zero(account['funded_conditions'].get("f_profit_day_usd", 0.0))
    f_mdd_type = account['funded_conditions'].get("f_mdd_type")
    f_mdd_usd = float(account['funded_conditions'].get("f_mdd_usd"))
    f_ddd_usd = float(account['funded_conditions'].get("f_ddd_usd"))
    ddd_soft_breach = account['company']['ddd_soft_breach']
    target_usd = _int_or_zero(account['funded_conditions'].get("f_target_usd"))
    personal_target = initial_balance + combo.get("personal_target")
    target_initial = initial_balance + target_usd
    min_withdrawal = _int_or_zero(account['funded_conditions'].get("min_withdrawal"))
    max_withdrawal = _int_or_zero(account['funded_conditions'].get("max_withdrawal"))
    safety_net_usd = _int_or_zero(account['funded_conditions'].get("safety_net_usd"))
    safety_net_account = initial_balance + safety_net_usd
    margin = combo["margin"]
    payout_mode = combo["payout_mode"]
    min_withdrawal_target = safety_net_account + min_withdrawal
    max_withdrawal_target = safety_net_account + max_withdrawal
    withdrawal_target = min_withdrawal_target if payout_mode == "Min" else max_withdrawal_target
    profit_split = account['funded_conditions'].get("profit_split")
    withdrawal_fee = _int_or_zero(account['funded_conditions'].get("withdrawal_fee"))
    highest_mdd_account = _int_or_zero(account['funded_conditions'].get("f_highest_mdd_account"))
    mdd_account_after_withdrawal = _int_or_zero(account['funded_conditions'].get("mdd_account_after_withdrawal"))
    max_num_payouts = _int_or_zero(account['funded_conditions'].get("max_num_payouts"))
    # Initial conditions
    mdd = initial_balance - f_mdd_usd
    mdd_used = mdd
    mdd_after = mdd
    balance = initial_balance
    balance_after = initial_balance
    peak_balance = initial_balance
    consistency_pct = account['funded_conditions'].get("f_consistency_pct")
    consistency_pct = 100.0 if consistency_pct is None or consistency_pct == 0 else float(consistency_pct)
    consistency_base = initial_balance
    target_consist = consistency_base + (combo["tp"] / (consistency_pct / 100))
    general_commission = max(6.0, max(float(combo.get("tp", 0.0)), float(combo.get("sl", 0.0))) / 500.0 * 6.0)
    commission = general_commission
    target_ = max(target_initial + general_commission, target_consist, min_withdrawal_target) + general_commission
    profit_remaining = (target_ + general_commission) - balance
    days = 0
    trades = 0
    profit_days = 0
    total_cost = 0
    account_end = False
    withdrawal_realized = False
    withdrawal = 0
    payout = 0
    num_payouts = 0
    profits = 0


    while not account_end and combo['sl'] <= f_ddd_usd:

        days += 1
        trades += 1
        balance = balance_after
        trade_cost = 0

        if trades == 1 and not withdrawal_realized:
            balance = initial_balance
            mdd = initial_balance - f_mdd_usd
            mdd_after = mdd
            mdd_used = mdd
            peak_balance = initial_balance
            profit_days = 0
            trades = 1

        if withdrawal_realized:
            trades = 1
            profit_days = 0
            consistency_base = balance_after

        withdrawal_realized = False
        withdrawal = 0
        payout = 0

        profit_remaining = target_ - balance
        trades_remaining = max(0, f_min_days - trades)
        profit_days_remaining = max(0, f_min_profit_days - profit_days)
        profits_in_profit_days_remaining = profit_days_remaining * profit_day_usd
        max_days_remainig = max(trades_remaining, profit_days_remaining)

        if combo["tp_mode"] == "Full":
            tp_used = min(combo["tp"], profit_remaining)
            if profit_days_remaining: tp_used = max(tp_used, profit_day_usd)
        if combo["tp_mode"] == "Calculate":
            tp_used = min(combo["tp"], profit_remaining - (profits_in_profit_days_remaining - profit_day_usd), profit_remaining)
        if combo["tp_mode"] == "Average":
            tp_used = profit_remaining / max(max_days_remainig, 1)
        tp_used = profit_day_usd if profit_days_remaining and tp_used < profit_day_usd else tp_used
        tp_used = min(tp_used + commission, combo['tp'])
        sl_used = max(0.0, min(combo["sl"], balance - mdd_used))
        tp_used = round(tp_used,2)
        sl_used = round(sl_used,2)

        commission = int(max(6.0, max(tp_used, sl_used)) / 500.0 * 6.0)
        if consistency_pct < 100:
            # consistency_base = initial_balance
            target_consist = max(target_consist, consistency_base + (tp_used / (consistency_pct / 100)) + general_commission)
        target_each_payout = consistency_base + account['funded_conditions']['target_each_payout']
        target_ = max(target_, target_consist, personal_target, withdrawal_target, target_each_payout)
        # profit_remaining = target_ - balance #? Para que se actualice

        prob_tp = sl_used / (tp_used + sl_used) if (tp_used + sl_used) > 0 else 0.5
        rndm = random.random()
        trade_result = tp_used - commission if rndm < prob_tp else -sl_used - commission

        mdd = mdd_after
        if f_mdd_type == 'trailing':
            mdd_trailing = mdd + round(max(tp_used, sl_used) * random.uniform(0.1, 0.9))
            if mdd_trailing > initial_balance:
                mdd_trailing = initial_balance
        else:
            mdd_trailing = 0
        # if mdd_trailing > balance - f_mdd_usd:
        #     mdd_trailing = mdd
        mdd_used = min(max(mdd, mdd_trailing), highest_mdd_account)
        if f_mdd_type == 'trailing':
            progress = mdd_trailing - mdd
            if balance + progress < mdd + f_mdd_usd:
                mdd_used = mdd
        # if balance + tp_used - f_mdd_usd < mdd_trailing:
        #     mdd_used = mdd
        ddd_failed = f_ddd_usd is not None and sl_used > f_ddd_usd
        if ddd_soft_breach == False and trade_result < -f_ddd_usd:
            ddd_failed
        balance_after = balance + trade_result
        mdd_failed = balance_after <= mdd_used
        peak_balance = max(peak_balance, balance_after)
        mdd_after = min(max(mdd, mdd_used, peak_balance - f_mdd_usd), highest_mdd_account)
        if f_mdd_type == "static":
            mdd_after = initial_balance - f_mdd_usd


        if trade_result >= profit_day_usd:
            profit_days += 1


        # Withdrawal
        if balance_after >= target_ and trades >= f_min_days and profit_days >= f_min_profit_days:
            withdrawal_realized = True
            withdrawal = min(balance_after - safety_net_account, max_withdrawal, balance_after - safety_net_account)
            payout = (withdrawal * (profit_split / 100)) - withdrawal_fee
            num_payouts += 1
            profits += payout

            balance_after -= withdrawal
            mdd_after = mdd_account_after_withdrawal if mdd_account_after_withdrawal else mdd_after

        #? Finales de cuenta

        # Demasiado éxito
        if num_payouts >= max_num_payouts:
            account_end = True

        # MDD
        if mdd_failed:
            account_end = True

        # DDD
        if ddd_failed:
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
                "consistency_base": consistency_base,
                # "target_initial": target_initial,
                # "target_consist": target_consist,
                # "withdrawal_target": withdrawal_target,
                # "personal_target": personal_target,
                "target_each_payout": target_each_payout,
                "target_": target_,
                # "profit_remaining": profit_remaining,
                "tp_used": tp_used,
                "sl_used": sl_used,
                "prob_tp": prob_tp,
                "rndm": rndm,
                "trade_result": trade_result,
                "ddd_failed": ddd_failed,
                "mdd_failed": mdd_failed,
                "account_end": account_end,
                "withdrawal": withdrawal,
                "payout": payout,
                "balance_after": balance_after,
                # "peak_balance": peak_balance,
                "mdd_after": mdd_after,
                "traded_days": f"{trades}/{f_min_days}",
                "profit_days": f"{profit_days}/{f_min_profit_days} (${profit_day_usd})",
                "profits": profits,
                # "cost": trade_cost,
                # "cost_total": total_cost,
            }
        )

        balance = balance_after

    data['trades'] = trs
    # results['num_evals'] = 1 if f_ddd_usd >= combo['sl'] else 0
    results['profits'] = profits if f_ddd_usd >= combo['sl'] else 0
    # results['num_payouts'] = num_payouts if f_ddd_usd >= combo['sl'] else 0
    # results['cost'] = total_cost if f_ddd_usd >= combo['sl'] else 0
    results['days'] = days if f_ddd_usd >= combo['sl'] else 0
    data['results']= results
    return data



def _should_save_results(config, account_type) -> bool:
    if config.num_sims < 200000:
        return False
    if account_type == 'eval':
        if len(config.modes) <= 1:
            return False
        if not list(config.reset_trades):
            return False
        return min(config.reset_trades) == 0 and max(config.reset_trades) == 20
    elif account_type == 'funded':
        if len(config.tp_modes) <= 1 or len(config.payout_modes) <= 1:
            return False
    return True


def _sanitize_filename(value: str) -> str:
    text = str(value or "").strip()
    return re.sub(r"[^\w\-]+", "_", text)

def get_csv_file_path(account, account_type: Literal["eval", "funded"]):
    exports_root = Path(__file__).resolve().parent / "exports"
    company_short = _sanitize_filename(account.get("company", {}).get("short_name", "unknown"))
    if account_type == "eval":
        name = _sanitize_filename(account.get("eval1_conditions", {}).get("name", "eval"))
        id = account.get("eval1_conditions", {}).get("id", "unknown")
    elif account_type == "funded":
        name = _sanitize_filename(account.get("funded_conditions", {}).get("name"))
        id = account.get("funded_conditions", {}).get("id", "unknown")

    folder = exports_root / company_short
    folder.mkdir(parents=True, exist_ok=True)

    file_name = f"{account_type}_{name}_{id}.csv"
    file_path = folder / file_name

    return file_path

def _csv_file_exist(account, account_type: Literal["eval", "funded"]):
    file_path = get_csv_file_path(account, account_type)
    return os.path.exists(file_path)


def _read_results_in_csv(account, account_type: Literal["eval", "funded"]):
    # exports_root = Path(__file__).resolve().parent / "exports"
    # company_short = _sanitize_filename(account.get("company", {}).get("short_name", "unknown"))
    # eval_name = _sanitize_filename(account.get("eval1_conditions", {}).get("name", "eval"))
    # eval_id = account.get("eval1_conditions", {}).get("id", "unknown")

    # folder = exports_root / company_short
    # folder.mkdir(parents=True, exist_ok=True)

    # file_name = f"{eval_name}_{eval_id}.csv"
    # file_path = folder / file_name
    file_path = get_csv_file_path(account, account_type)

    with open(file_path, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)

def _save_eval_final_results_in_csv(final_results, account, new_file: bool):
    # exports_root = Path(__file__).resolve().parent / "exports"
    # company_short = _sanitize_filename(account.get("company", {}).get("short_name", "unknown"))
    # eval_name = _sanitize_filename(account.get("eval1_conditions", {}).get("name", "eval"))
    # eval_id = account.get("eval1_conditions", {}).get("id", "unknown")

    # folder = exports_root / company_short
    # folder.mkdir(parents=True, exist_ok=True)

    # file_name = f"eval_{eval_name}_{eval_id}.csv"
    # file_path = folder / file_name
    file_path = get_csv_file_path(account, "funded")
    if not final_results:
        return file_path

    if new_file:
        with file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=list(final_results[0].keys()))
            writer.writeheader()
            writer.writerows(final_results)

        return file_path
    else:
        escribir_encabezado = not file_path.exists() or file_path.stat().st_size == 0

        with open(file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=final_results[0].keys())
            
            if escribir_encabezado:
                writer.writeheader()  # Solo escribe el encabezado si es necesario
            
            writer.writerows(final_results)

        print("Resultados añadidos correctamente")
        return file_path

def _save_funded_final_results_in_csv(final_results, account, new_file: bool):
    # exports_root = Path(__file__).resolve().parent / "exports"
    # company_short = _sanitize_filename(account.get("company", {}).get("short_name", "unknown"))
    # funded_name = _sanitize_filename(account.get("funded_conditions", {}).get("name"))
    # funded_id = account.get("funded_conditions", {}).get("id", "unknown")

    # folder = exports_root / company_short
    # folder.mkdir(parents=True, exist_ok=True)

    # file_name = f"funded_{funded_name}_{funded_id}.csv"
    # file_path = folder / file_name
    file_path = get_csv_file_path(account, "funded")

    if not final_results:
        return file_path

    if new_file:
        with file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=list(final_results[0].keys()))
            writer.writeheader()
            writer.writerows(final_results)

        return file_path
    else:
        escribir_encabezado = not file_path.exists() or file_path.stat().st_size == 0

        with open(file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=final_results[0].keys())
            
            if escribir_encabezado:
                writer.writeheader()  # Solo escribe el encabezado si es necesario
            
            writer.writerows(final_results)

        print("Resultados añadidos correctamente")
        return file_path


def _insert_best_eval_results_to_supabase(best_results_with_conditions, eval_id, delete: bool):
    if not best_results_with_conditions:
        return None
    if delete:
        (supabase.table("eval_sim_results").delete().eq("eval_id", eval_id).execute())
    # Normalizar results por si vienen de csv y está todo en string
    for d in best_results_with_conditions:
        for key, value in d.items():
            if value == "":
                d[key] = None
            if (isinstance(value, str) and value.startswith("[") and value.endswith("]")):
                d[key] = ast.literal_eval(value)
    return supabase.table("eval_sim_results").insert(best_results_with_conditions).execute()

def _insert_best_funded_results_to_supabase(best_results_with_conditions, funded_id, delete: bool):
    if not best_results_with_conditions:
        return None
    if delete:
        (supabase.table("funded_sim_results").delete().eq("funded_id", funded_id).execute())
    # Normalizar results por si vienen de csv y está todo en string
    for d in best_results_with_conditions:
        for key, value in d.items():
            if value == "":
                d[key] = None
            if (isinstance(value, str) and value.startswith("[") and value.endswith("]")):
                d[key] = ast.literal_eval(value)
    return supabase.table("funded_sim_results").insert(best_results_with_conditions).execute()

def _read_final_results_from_csv(account):
    exports_root = Path(__file__).resolve().parent / "exports"
    company_short = _sanitize_filename(account.get("company", {}).get("short_name", "unknown"))
    eval_name = _sanitize_filename(account.get("eval1_conditions", {}).get("name", "eval"))
    eval_id = account.get("eval1_conditions", {}).get("id", "unknown")
    
    folder = exports_root / company_short
    file_name = f"{eval_name}_{eval_id}.csv"
    file_path = folder / file_name

    file = Path(file_path)
    
    if not file.exists():
        raise FileNotFoundError(f"No se encontró el archivo csv: {file_path}")
    
    with open(file, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        final_results_from_csv = list(reader)
        return final_results_from_csv

def _get_best_results_from_eval_final_results(final_results):
    best = {}

    for d in final_results:
        d['fund_cost'] = float(d['fund_cost'])
        price = d["price"]

        if price not in best or d["fund_cost"] < best[price]["fund_cost"]:
            best[price] = d

    filtered_results = list(best.values())

    return filtered_results
def _get_best_results_from_funded_final_results(final_results):

    categories = [
        "total_profits",
        "p_prob*payouts",
        "payouts/month",
    ]

    best_results = []

    for category in categories:
        
        best = max(final_results, key=lambda d: float(d.get(category, float("-inf"))))
        # Crear una copia para no modificar el original
        best_copy = best.copy()
        best_copy["result_type"] = category
        
        best_results.append(best_copy)
    
    return best_results


def montecarlo_simulation_eval(account, config, combinations):
    final_results = []
    for comb in combinations:
        combination_results = {
            'total_sims': 0,
            'total_evals': 0,
            'total_resets': 0,
            'total_renews': 0,
            'total_passed': 0,
            'total_cost': 0,
            'sim_days_avg': 0,
        }
        comb_all_results = []
        for i in range(config.num_sims):
            account_data = simulate_eval(account, comb)
            account_results = account_data['results']
            if account_results['num_evals'] == 0:
                continue
            # print(f'account_results: {account_results}')
            combination_results['total_sims'] += 1
            combination_results['total_evals'] += account_results['num_evals']
            combination_results['total_resets'] += account_results['resets']
            combination_results['total_renews'] += account_results['renews']
            combination_results['total_passed'] += account_results['passed']
            combination_results['total_cost'] += account_results['cost']
            comb_all_results.append(account_results)
        # print(f'comb_all_results: {comb_all_results}')
        if combination_results['total_evals'] == 0:
            continue
        combination_results['fund_cost'] = round(combination_results['total_cost'] / combination_results['total_passed'], 2) if combination_results['total_passed'] > 0 else 999999
        combination_results['sim_days_avg'] = round(sum(d["sim_days"] for d in comb_all_results) / len(comb_all_results), 1) if len(comb_all_results) else 0
        combination_results = combination_results | comb
        final_results.append(combination_results)
        # print(f'combination_results: {combination_results}')

    best_results = _get_best_results_from_eval_final_results(final_results)

    return final_results, best_results

def montecarlo_simulation_funded(account, config, combinations):
    final_results = []
    for comb in combinations:
        combination_results = {
            'total_sims': 0,
            'total_profits': 0,
            'profits_per_account': 0,
            'days_avg': 0,
            'payout_accounts': 0,
            'payout_prob': 0,
            'p_prob*payouts': 0,
            'payouts/month': 0,
        }
        comb_all_results = []
        for i in range(config.num_sims):
            account_data = simulate_funded(account, comb)
            account_results = account_data['results']
            # if account_results['num_evals'] == 0:
                # continue
            # print(f'account_results: {account_results}')
            combination_results['total_sims'] += 1
            combination_results['total_profits'] += account_results['profits']
            if account_results['profits'] > 0:
                combination_results['payout_accounts'] += 1
            comb_all_results.append(account_results)
        # print(f'comb_all_results: {comb_all_results}')
        # if combination_results['total_evals'] == 0:
        #     continue
        combination_results['days_avg'] = round(sum(d["days"] for d in comb_all_results) / len(comb_all_results), 1) if len(comb_all_results) else 0
        combination_results['profits_per_account'] = round(combination_results["total_profits"] / combination_results['total_sims'], 2)
        combination_results['payout_prob'] = round(combination_results["payout_accounts"] / combination_results['total_sims'], 2)
        combination_results['p_prob*payouts'] = round(combination_results["payout_prob"] * combination_results['total_profits'], 2)
        combination_results['payouts/month'] = round(combination_results["profits_per_account"] / (combination_results['days_avg'] / 20), 2) if combination_results['days_avg'] > 0 else 1
        combination_results['total_profits'] = round(combination_results['total_profits'], 2)
        combination_results = combination_results | comb
        final_results.append(combination_results)
        # print(f'combination_results: {combination_results}')

    best_results = _get_best_results_from_funded_final_results(final_results)

    return final_results, best_results

def _normalize_eval_results_to_save(final_results, best_results, account):

    final_results_with_conditions = []
    for res in final_results:
        final_results_with_conditions.append(res | account['eval1_conditions'])
    for res in final_results_with_conditions:
        res["eval_id"] = res.pop("id")
        res.pop("name")
        res["sl"] = int(res["sl"])
        res["tp"] = int(res["tp"])
        if res["reset_cost"] == 0:
            res["reset_cost"] = None

    best_results_with_conditions = []
    for res in best_results:
        best_results_with_conditions.append(res | account['eval1_conditions'])
    for res in best_results_with_conditions:
        res["eval_id"] = res.pop("id")
        res.pop("name")
        res["sl"] = int(res["sl"])
        res["tp"] = int(res["tp"])
        if res["reset_cost"] == 0:
            res["reset_cost"] = None

    return final_results_with_conditions, best_results_with_conditions

def _normalize_funded_results_to_save(final_results, best_results, account):

    final_results_with_conditions = []
    for res in final_results:
        final_results_with_conditions.append(res | account['funded_conditions'])
    for res in final_results_with_conditions:
        res["funded_id"] = res.pop("id")
        res.pop("name")

    best_results_with_conditions = []
    for res in best_results:
        best_results_with_conditions.append(res | account['funded_conditions'])
    for res in best_results_with_conditions:
        res["funded_id"] = res.pop("id")
        res.pop("name")

    return final_results_with_conditions, best_results_with_conditions