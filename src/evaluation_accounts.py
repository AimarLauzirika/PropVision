from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status, load_eval_results_with_id
from src.propvision.db import supabase
from src.propvision.simulator import (
    SimulationConfig,
    simulate_eval,
    _build_combinations,
    _should_save_results,
    _save_final_results_in_csv,
    _insert_best_results_to_supabase,
    montecarlo_simulation,
    _normalize_results_to_save,
    _read_results_in_csv,
    _get_best_results_from_final_results,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _render_simulation_page(
    page_label: str,
    selector_label: str,
    select_prompt: str,
    example_label: str,
    montecarlo_label: str,
    simulate_fn,
) -> None:
    col1, col2 = st.columns(2)

    with col1:
        with st.expander(selector_label, expanded=True):
            accounts, connection_status = load_accounts_with_status()
            accounts = [acc for acc in accounts if acc.get("eval1_conditions") is not None]

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

            st.info("Se han cargado %d cuentas desde Supabase." % len(accounts))

            selected_company = st.selectbox("Filtrar por empresa", ["Todas"] + company_names)
            filtered_accounts = [
                account
                for account in accounts
                if selected_company == "Todas"
                or account.get("company", {}).get("long_name") == selected_company
            ]

            account_options = [_format_account_name(account) for account in filtered_accounts]
            selected_labels = st.multiselect(
                select_prompt,
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
        with st.expander(f"Configuración para la simulación {page_label}", expanded=True):
            num_sims = st.number_input(
                "Número de simulaciones (mín. 200000 para poder guardar)",
                min_value=1,
                max_value=500000,
                value=200000,
                step=1000,
            )
            modes = st.segmented_control(
                "Mode (All para poder guardar)",
                list(SimulationConfig.modes) + ["All"],
                default=["All"],
            )
            if modes == "All":
                modes = SimulationConfig.modes
            else:
                modes = [modes]

            col21, col22 = st.columns(2)
            with col21:
                min_reset = st.number_input(
                    "Reset trades mínimo (0 para poder guardar), sólo pares",
                    min_value=min(SimulationConfig().reset_trades),
                    max_value=max(SimulationConfig().reset_trades),
                    value=0,
                    step=1,
                )
            with col22:
                max_reset = st.number_input(
                    "Reset trades máximo (20 para poder guardar), sólo pares",
                    min_value=min(SimulationConfig().reset_trades),
                    max_value=max(SimulationConfig().reset_trades),
                    value=20,
                    step=1,
                )

            if min_reset > max_reset:
                st.error("El máximo de reset trades debe ser mayor o igual al mínimo.")
                st.stop()

            config = SimulationConfig(
                num_sims=num_sims,
                modes=modes,
                reset_trades=tuple(range(min_reset, max_reset + 1)),
            )
            combinations = _build_combinations(selected_accounts[0], config) if selected_accounts else []

            if combinations:
                st.info("Hay %d combinaciones." % len(combinations))
            else:
                st.warning("Hay %d combinaciones." % len(combinations))

    with st.expander(example_label, expanded=True):
        if len(selected_accounts) != 1:
            st.warning('Selecciona sólo una cuenta.')
            return

        if not combinations:
            st.warning("No hay combinaciones disponibles para generar un ejemplo.")
            return

        account = selected_accounts[0]
        selected_comb = st.selectbox(
            "Selecciona una combinación para ver un ejemplo",
            options=combinations,
            format_func=lambda comb: f"Price {comb['price']} | Mode {comb['mode']} | TP {comb['tp']} | SL {comb['sl']} | Reset {comb['reset_trades']}",
        )

        if st.button("Generar nuevo ejemplo"):
            data = simulate_fn(account, selected_comb)
            trades, results = data["trades"], data["results"]

            with st.expander("Condiciones de la cuenta"):
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
                    <strong>Resultados:</strong> {results}<br>
                    """,
                    unsafe_allow_html=True,
                )
                st.dataframe(trades, height=500, width="stretch")

    with st.expander(montecarlo_label, expanded=True):
        if not selected_accounts:
            st.warning('Selecciona al menos una cuenta para ejecutar la simulación.')
            return

        account = selected_accounts[0]
        eval_id = account["eval1_id"]
        data = load_eval_results_with_id(eval_id)
        if data["exc"]:
            st.error(f'Error con supabase: {data["exc"]}')
        elif not data["results"]:
            st.info('No se encontraron resultados para esta evaluación en la base de datos.')

        new_prices: List[Any] = []
        new_tps: List[Any] = []
        new_sls: List[Any] = []
        same_conditions = True

        if data["results"]:
            st.markdown(
                """
                <div style="line-height:1.7;">
                <strong>Registros previos</strong><br>
                """,
                unsafe_allow_html=True,
            )
            st.dataframe(data["results"])

            eval_conditions_fields = [
                "e_target_usd",
                "e_mdd_usd",
                "e_mdd_type",
                "e_ddd_usd",
                "e_consistency_pct",
                "e_min_days",
                "e_min_profit_days",
                "e_profit_day_usd",
                "reset_prices",
                "e_suscription_type",
                "activation_fee_usd",
            ]
            for condition in eval_conditions_fields:
                if data["results"][0].get(condition) != account["eval1_conditions"].get(condition):
                    same_conditions = False
                    st.warning(
                        f'Hay condiciones diferentes de los resultados de la BD como el de {condition}, se realizará la simulación de nuevo.'
                    )

            if same_conditions:
                st.info("Todas las CONDICIONES coinciden con los resultados de la BD.")
                new_prices = list(set(account["eval1_conditions"]["eval_prices"]) - set(data["results"][0]["eval_prices"]))
                new_tps = list(set(account["eval1_conditions"]["e_tps_usd"]) - set(data["results"][0]["e_tps_usd"]))
                new_sls = list(set(account["eval1_conditions"]["e_sls_usd"]) - set(data["results"][0]["e_sls_usd"]))
                if new_prices:
                    st.warning(f'Hay precios que faltan en la BD: {new_prices}.')
                if new_tps:
                    st.warning(f'Hay TPs que faltan en la BD: {new_tps}.')
                if new_sls:
                    st.warning(f'Hay SLs que faltan en la BD: {new_sls}.')

        if not data["results"] or not same_conditions or new_prices or new_tps or new_sls and len(combinations):
            save_requisites = _should_save_results(config)
            guardar = st.toggle("Guardar", disabled=not save_requisites, value=True)
            if save_requisites:
                st.success("Esta configuración cumple con los requisitos para guardar los resultados de las simulaciones de Montecarlo.")
            else:
                st.warning("Esta configuración NO cumple con los requisitos para guardar los resultados de las simulaciones de Montecarlo.")

            if st.button("Empezar Montecarlo"):
                if not guardar:
                    st.dialog(
                        'Los resultados de esta simulación No se guardarán.',
                        width="small",
                        dismissible=True,
                        icon=None,
                        on_dismiss="ignore",
                    )

                if not data["results"] or not same_conditions:
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file=True)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and new_prices and not new_tps and not new_sls:
                    combinations = [c for c in combinations if c["price"] in new_prices]
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file=False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete=False)
                            st.success("Resultados guardados en Supabase.")
                            supabase.table("eval_sim_results").update({"eval_prices": account["eval1_conditions"]["eval_prices"]}).eq("eval_id", eval_id).execute()
                            st.success("Registros anteriores actualizado con eval_prices completo.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and (new_tps or new_sls) and not new_prices:
                    combinations = [c for c in combinations if c["tp"] in new_tps or c["sl"] in new_sls]
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file=False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    final_results_with_conditions = _read_results_in_csv(account)
                    best_results_with_conditions = _get_best_results_from_final_results(final_results_with_conditions)
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and new_prices and (new_tps or new_sls):
                    new_prices_combinations = [
                        c
                        for c in combinations
                        if c["price"] in new_prices and c["tp"] not in new_tps and c["sl"] not in new_sls
                    ]
                    final_results, best_results = montecarlo_simulation(account, config, new_prices_combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file=False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    combinations = _build_combinations(account, config)
                    combinations = [c for c in combinations if c["tp"] in new_tps or c["sl"] in new_sls]
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file=False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    final_results_with_conditions = _read_results_in_csv(account)
                    best_results_with_conditions = _get_best_results_from_final_results(final_results_with_conditions)
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")


def render_evaluation_page() -> None:
    st.title(":orange[Evaluaciones] - PropVision")
    st.caption("Simulaciones de evaluación para prop firms con enfoque Monte Carlo.")
    _render_simulation_page(
        page_label="evaluación",
        selector_label="Selector de evaluaciones",
        select_prompt="Selecciona evaluaciones",
        example_label="Ejemplo de evaluación",
        montecarlo_label="Simulación de Montecarlo",
        simulate_fn=simulate_eval,
    )


if __name__ == "__main__":
    st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")
    render_evaluation_page()
