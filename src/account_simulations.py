from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import random

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status, load_results_with_id
from src.propvision.simulator import (
    SimulationConfig,
    simulate_eval,
    simulate_funded,
    _build_combinations,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _max_drawdown(series: List[float]) -> Tuple[float, int, int, List[float]]:
    if not series:
        return 0.0, 0, 0, []
    cum = []
    s = 0.0
    for v in series:
        s += v
        cum.append(s)

    peak = cum[0]
    peak_idx = 0
    maxdd = 0.0
    start = end = 0
    for i, v in enumerate(cum):
        if v > peak:
            peak = v
            peak_idx = i
        dd = peak - v
        if dd > maxdd:
            maxdd = dd
            start = peak_idx
            end = i
    return maxdd, start, end, cum


def render_account_simulations_page() -> None:
    st.title("PropVision — :blue[Simulaciones de cuentas]")
    # st.caption("Simula el ciclo evaluación → fondeada según número de simulaciones")

    accounts, connection_status = load_accounts_with_status()
    # require both eval and funded ids/conditions
    accounts = [a for a in accounts if a.get("eval1_id") and a.get("funded_id")]


    if not accounts:
        st.warning("No hay cuentas que tengan eval1_id y funded_id.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        account_options = [_format_account_name(a) for a in accounts]
        selected = st.selectbox("Selecciona cuenta", account_options)
        account = next(a for a in accounts if _format_account_name(a) == selected)
        eval_results = load_results_with_id(account["eval1_id"], 'eval')['results']
        eval_prices = [d["price"] for d in eval_results]
        funded_result_types = ["total_profits", "p_prob*payouts", "payouts/month"]
    with col2:
        prices = st.segmented_control(
            "Precios (All para poder guardar)",
            eval_prices + ["All"],
            default=["All"],
        )
    with col3:
        result_types = st.segmented_control(
            "Criterio de resultados (All para poder guardar)",
            funded_result_types + ["All"],
            default=["All"],
        )
    # st.dataframe(eval_results)
    if prices == "All":
        prices = eval_prices
    if result_types == "All":
        result_types = funded_result_types
    combinations = []
    for price in eval_prices:
        for type in result_types:
            combo = {"price": price, "result_type": type}
            combinations.append(combo)

    with st.expander("Mostrar un ejemplo", expanded=True):
        if not account:
            st.warning('Selecciona sólo una cuenta.')
            return

        if not combinations:
            st.warning("No hay combinaciones disponibles para generar un ejemplo.")
            return

        # account = account[0]
        selected_comb = st.selectbox(
            "Selecciona una combinación para ver un ejemplo",
            options=combinations,
            format_func=lambda comb: f"Precio: {comb['price']} | Criterio: {comb['result_type']}",
        )
    

    n = st.number_input(
        "Número total de simulaciones",
        min_value=1,
        max_value=1000000,
        value=1000,
        step=1,
    )
    save = st.checkbox("Guardar resumen (CSV)", value=False)

    if "stop_account_sim" not in st.session_state:
        st.session_state.stop_account_sim = False

    start_btn = st.button("Empezar simulación")
    stop_btn = st.button("Detener simulación")
    if stop_btn:
        st.session_state.stop_account_sim = True

    if not start_btn:
        return

    # reset stop flag
    st.session_state.stop_account_sim = False

    progress = st.progress(0)

    completed = 0
    total_costs = 0.0
    total_income = 0.0
    total_evals = 0
    total_passed_evals = 0
    total_positive_funded = 0
    seq: List[float] = []

    # Build simple per-run configs: eval may include reset_trades, funded should not
    base_sim = SimulationConfig()
    # eval_config = SimulationConfig(num_sims=1, modes=list(SimulationConfig.modes), reset_trades=tuple(range(min(base_sim.reset_trades), max(base_sim.reset_trades) + 1)))
    funded_config = SimulationConfig(num_sims=1, modes=list(SimulationConfig.modes), reset_trades=tuple())

    # eval_results = load_results_with_id(account["eval1_id"])
    # eval_prices = [d["price"] for d in eval_results]
    # funded_result_types = ["total_profits", "p_prob*payouts", "payouts/month"]
    # eval_combs = _build_combinations(account, eval_config) or []
    # funded_combs = _build_combinations(account, funded_config) or []

    if not eval_combs:
        st.warning("No hay combinaciones para la evaluación en esta cuenta.")
        return

    i = 0
    # loop until we reach n completed simulations (evaluations count as 1; a passed eval triggers a funded sim which also counts as 1)
    while completed < n:
        if st.session_state.stop_account_sim:
            st.warning("Simulación detenida por usuario.")
            break

        # pick a random evaluation combination and run it
        eval_comb = random.choice(eval_combs)
        eval_data = simulate_eval(account, eval_comb)
        er = eval_data.get("results", {})
        eval_cost = float(er.get("cost", 0) or 0)
        num_evals = int(er.get("num_evals", 0) or 0)
        passed = int(er.get("passed", 0) or 0)

        total_costs += eval_cost
        total_evals += num_evals
        if passed:
            total_passed_evals += 1

        seq.append(-eval_cost)
        completed += 1
        progress.progress(min(1.0, completed / n))

        # if evaluation passed, run funded sim and count it as another completed simulation
        if passed and completed < n:
            if funded_combs:
                funded_comb = random.choice(funded_combs)
                fdata = simulate_funded(account, funded_comb)
                fr = fdata.get("results", {})
                profits = float(fr.get("profits", 0) or 0)
                # positive incomes count as income; negative funded results are considered cost
                if profits > 0:
                    total_income += profits
                    total_positive_funded += 1
                else:
                    total_costs += abs(profits)

                seq.append(profits)
            else:
                # no funded combos: treat as zero change
                seq.append(0.0)

            completed += 1
            progress.progress(min(1.0, completed / n))

        i += 1

    # compute ratio and drawdown
    ratio = (total_income / total_costs) if total_costs > 0 else None
    maxdd, dd_start, dd_end, cum = _max_drawdown(seq)

    st.subheader("Resumen")
    st.write("- Total costes:", f"{total_costs:.2f}")
    st.write("- Total ingresos:", f"{total_income:.2f}")
    st.write("- Ingresos / Costes:", f"{ratio:.3f}" if ratio is not None else "N/A")
    st.write("- Mayor drawdown:", f"{maxdd:.2f}")
    st.write("- Total evaluaciones realizadas (suma num_evals):", f"{total_evals}")
    st.write("- Número de evaluaciones superadas:", f"{total_passed_evals}")
    st.write("- Número de cuentas fondeadas con resultado positivo:", f"{total_positive_funded}")

    # plot cumulative evolution and highlight max drawdown
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot(cum, marker=".", linewidth=1)
        if dd_end > dd_start:
            ax.axvspan(dd_start, dd_end, color="red", alpha=0.2)
        ax.set_xlabel("Paso")
        ax.set_ylabel("Evolución (USD)")
        st.pyplot(fig)
    except Exception:
        st.warning("No se pudo dibujar el gráfico (matplotlib podría no estar disponible).")

    if save:
        st.info("Funcionalidad de guardado de resumen no implementada; se puede añadir si lo deseas.")


if __name__ == "__main__":
    st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")
    render_account_simulations_page()
