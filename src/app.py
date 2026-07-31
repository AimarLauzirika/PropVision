from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status
from src.propvision.simulator import SimulationConfig, build_example_context, simulate_eval, _build_combinations, _get_reset_cost

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")


def main() -> None:
    st.title("PropVision")
    st.caption("Simulaciones de evaluación para prop firms con enfoque Monte Carlo.")

    col1, col2 = st.columns(2)

    with col1:
        with st.expander("Selector de evaluaciones", expanded=True):
            accounts, connection_status = load_accounts_with_status()
            # Filtrar las cuentas que tengan una eval asociada
            accounts = [acc for acc in accounts if acc.get("eval1_conditions") is not None]
            print(accounts)

            company_names = sorted(
                {
                    account.get("company", {}).get("long_name")
                    or account.get("company", {}).get("short_name")
                    or "Sin empresa"
                    for account in accounts
                }
            )

            if "Conectado a Supabase" in connection_status:
                st.success(connection_status)
            else:
                st.warning(connection_status)
            st.info("Se han cargado %d evaluaciones desde Supabase." % len(accounts))

            selected_company = st.selectbox("Filtrar por empresa", ["Todas"] + company_names)
            # search = st.text_input("Buscar cuenta")

            filtered_accounts = [
                account
                for account in accounts
                if selected_company == "Todas"
                or account.get("company", {}).get("long_name") == selected_company
            ]

            account_options = [_format_account_name(account) for account in filtered_accounts]
            selected_labels = st.multiselect(
                "Selecciona evaluaciones",
                options=account_options,
                default=st.session_state.get("selected_account_names", []),
                key="selected_account_names",
                help="La lista se puede desplazar cuando hay muchas cuentas.",
            )
            selected_accounts = [
                account
                for account in filtered_accounts
                if _format_account_name(account) in selected_labels
            ]

            if not filtered_accounts:
                st.warning("No se encontraron cuentas con ese filtro de empresa o texto.")

    with col2:
        with st.expander("Parámetros de simulación", expanded=True):
            num_sims = st.number_input("Número de simulaciones", min_value=1, max_value=500000, value=30, step=1000)
            modes = st.segmented_control("Mode", list(SimulationConfig.modes) + ["All"], default=["All"])
            if modes == "All": modes = SimulationConfig.modes
            else:
                modes = [modes]
            col21, col22 = st.columns(2)
            with col21:
                min_reset = st.number_input("Reset trades mínimo", min_value=min(SimulationConfig().reset_trades), max_value=max(SimulationConfig().reset_trades), value=15, step=1)
            with col22:
                max_reset = st.number_input("Reset trades máximo", min_value=min(SimulationConfig().reset_trades), max_value=max(SimulationConfig().reset_trades), value=15, step=1)
            # min_reset = st.number_input("Reset trades mínimo", min_value=0, max_value=20, value=5, step=1)
            # max_reset = st.number_input("Reset trades máximo", min_value=0, max_value=20, value=5, step=1)
            if min_reset > max_reset:
                st.error("El máximo de reset trades debe ser mayor o igual al mínimo.")
                st.stop()
            config = SimulationConfig(num_sims=num_sims, modes=modes, reset_trades=tuple(range(min_reset, max_reset + 1)))
            print(config)
            combinations = _build_combinations(selected_accounts[0], config) if selected_accounts else []
            print(f'Hay {len(combinations)} combinaciones')
            # print(combinations)
            st.info("Hay %d combinaciones." % len(combinations))

            # if st.button("Empezar simulación"):
            #     if not modes:
            #         st.error("Debes seleccionar al menos un Mode para lanzar la simulación.")
            #         st.stop()
            #     if not selected_accounts:
            #         st.error("Selecciona al menos una cuenta para ejecutar la simulación.")
            #         st.stop()

            #     results_by_account = []
            #     for account in selected_accounts:
            #         account_results = simulate_account(account, config)
            #         for row in account_results:
            #             results_by_account.append({**row, "account_name": _format_account_name(account)})

                # st.session_state["results"] = results_by_account
                # st.session_state["account_name"] = ", ".join(_format_account_name(account) for account in selected_accounts)
                # st.session_state["selected_combo"] = None

    with st.expander('Ejemplo de evaluación', expanded=True):
        if len(selected_accounts) != 1:
            st.warning('Selecciona sólo una cuenta.')
            return
        account = selected_accounts[0]
        selected_comb = st.selectbox(
                    "Selecciona una combinación para ver un ejemplo",
                    options=combinations,
                    format_func=lambda comb: f"Price {comb['price']} | Mode {comb['mode']} | TP {comb['tp']} | SL {comb['sl']} | Reset {comb['reset_trades']}",
                )

        if st.button("Generar nuevo ejemplo"):
            print(f'selected_comb: {selected_comb}')
            # account = next((account for account in selected_accounts if _format_account_name(account) == selected_comb.get("account_name", "")), None)
            # if account is None:
            #     account = selected_accounts[0] if selected_accounts else (filtered_accounts[0] if filtered_accounts else accounts[0])
            # seed = int(st.session_state.get("example_seed", 0)) + 1
            # st.session_state["example_seed"] = seed
            data = simulate_eval(account, selected_comb)
            trades, results = data['trades'], data['results']
            # trades = simulate_eval(account, selected_comb, seed=seed)
            # st.session_state["example_trades"] = trades
            # st.session_state["example_combo"] = selected_comb

            with st.expander('Condiciones de la cuenta'):
                st.markdown(
                    f"""
                    <div style="line-height:1.7;">
                    <strong>Condiciones:</strong> Balance inicial {account['initial_balance']} | MDD {account['eval1_conditions']['e_mdd_usd']} | Tipo MDD {account['eval1_conditions']['e_mdd_type']} | DDD {account['eval1_conditions']['e_ddd_usd']} | Consistencia {account['eval1_conditions']['e_consistency_pct']} | Días mín. {account['eval1_conditions']['e_min_days']} | Días beneficio {account['eval1_conditions']['e_min_profit_days']} | Beneficio mín. {account['eval1_conditions']['e_profit_day_usd']}<br>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if results:
                st.subheader("Ejemplo de ejecución trade a trade")
                st.markdown(
                    f"""
                    <div style="line-height:1.7;">
                    <strong>Eval:</strong> {account['eval1_conditions']}<br>
                    <strong>Resultados:</strong> {results}<br>
                    """,
                    unsafe_allow_html=True,
                )
                st.dataframe(trades, height=500, width='stretch')


    with st.expander(f"Simulación de Montecarlo", expanded=True):

        if st.button("Empezar Montecarlo"):
            final_results = []
            # print(f'combinations: {combinations}')
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
                combination_results['fund_cost'] = round(combination_results['total_cost'] / combination_results['total_passed'], 2) if combination_results['total_passed'] > 0 else 0
                combination_results['sim_days_avg'] = round(sum(d["sim_days"] for d in comb_all_results) / len(comb_all_results), 1) if len(comb_all_results) else 0
                combination_results = combination_results | comb
                # combination_results['reset_trades'] = comb['reset_trades']
                # combination_results = combination_results | config.__dict__ | comb
                # combination_results.pop('num_sims')
                # combination_results.pop('modes')
                final_results.append(combination_results)
                # print(f'combination_results: {combination_results}')

        #? Mejores resultados para cada precio
        
        # Mínimo fund_cost por price
        min_cost = {}
        for d in final_results:
            price = d["price"]
            min_cost[price] = min(min_cost.get(price, float("inf")), d["fund_cost"])

        # Filtrar y eliminar duplicados por price
        seen = set()
        best_results = [
            d for d in final_results
            if d["fund_cost"] == min_cost[d["price"]]
            and not (d["price"] in seen or seen.add(d["price"]))
        ]



        st.markdown(
            f"""
            <div style="line-height:1.7;">
            <strong>Mejores resultados por precio</strong><br>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe(best_results, width='stretch')

        # Todas las combinaciones
        st.markdown(
            f"""
            <div style="line-height:1.7;">
            <strong>Todas las combinaciones:</strong> {len(final_results)}<br>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe(final_results, width='stretch')

        #? GUARDAR RESULTADOS

        final_results_with_conditions = []
        for res in best_results:
            final_results_with_conditions.append(res | account['eval1_conditions'])
        # Normalizar resultados
        for res in final_results_with_conditions:
            res["eval_id"] = res.pop("id")
            if res["reset_cost"] == 0:
                res["reset_cost"] = None
        # final_results_with_conditions = final_results | account['eval1_conditions']
        st.dataframe(final_results_with_conditions, width='stretch')
        

        # Fichero csv para todas las combinaciones (final_results)

if __name__ == "__main__":
    main()
