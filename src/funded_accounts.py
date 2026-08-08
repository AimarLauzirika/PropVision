from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status, load_results_with_id
from src.propvision.db import supabase
from src.propvision.simulator import (
    FundedSimulationConfig,
    simulate_funded,
    _build_funded_combinations,
    _should_save_results,
    _csv_file_exist,
    _save_funded_final_results_in_csv,
    _insert_best_funded_results_to_supabase,
    montecarlo_simulation_funded,
    _normalize_funded_results_to_save,
    _read_results_in_csv,
    _get_best_results_from_funded_final_results,
    _int_or_zero
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
            accounts = [acc for acc in accounts if acc.get("funded_conditions") is not None]

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

            st.info("Se han cargado %d cuentas fondeadas desde Supabase." % len(accounts))

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
            col21, col22 = st.columns(2)
            with col21:
                tp_modes = st.segmented_control(
                    "TP Mode (All para poder guardar)",
                    list(FundedSimulationConfig.tp_modes) + ["All"],
                    default=["All"],
                    required=True
                )
                if tp_modes == "All":
                    tp_modes = FundedSimulationConfig.tp_modes
                else:
                    tp_modes = [tp_modes]
            with col22:
                payout_modes = st.segmented_control(
                    "Payouts (All para poder guardar)",
                    list(FundedSimulationConfig.payout_modes) + ["All"],
                    default=["All"],
                    required=True
                )
                if payout_modes == "All":
                    payout_modes = FundedSimulationConfig.payout_modes
                else:
                    payout_modes = [payout_modes]


            config = FundedSimulationConfig(
                num_sims=num_sims,
                tp_modes=tp_modes,
                payout_modes=payout_modes,
                # reset_trades=tuple(range(min_reset, max_reset + 1)),
            )
            combinations = _build_funded_combinations(selected_accounts[0], config) if selected_accounts else []

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
            format_func=lambda comb: f"Payout mode: {comb['payout_mode']} | TP mode: {comb['tp_mode']} | TP: {comb['tp']} | SL: {comb['sl']} | pTarget: {comb['personal_target']} | Margin: {comb['margin']}",
        )

        if st.button("Generar nuevo ejemplo"):
            data = simulate_fn(account, selected_comb)
            trades, results = data["trades"], data["results"]

            with st.expander("Condiciones de la cuenta"):
                st.markdown(
                    f"""
                    <div style="line-height:1.7;">
                    <strong>Condiciones:</strong> Balance inicial {account['initial_balance']} | MDD {account['funded_conditions']['f_mdd_usd']} | Tipo MDD {account['funded_conditions']['f_mdd_type']} | DDD {account['funded_conditions']['f_ddd_usd']} | Consistencia {account['funded_conditions']['f_consistency_pct']} | Días mín. {account['funded_conditions']['f_min_days']} | Días beneficio {account['funded_conditions']['f_min_profit_days']} | Beneficio mín. {account['funded_conditions']['f_profit_day_usd']}<br>
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
        funded_id = account["funded_id"]
        data = load_results_with_id(funded_id, "funded")
        if data["exc"]:
            st.error(f'Error con supabase: {data["exc"]}')
        elif not data["results"]:
            st.info('No se encontraron resultados para esta cuentas fondeadas en la base de datos.')
            if _csv_file_exist(account, 'funded'):
                results_from_csv = _read_results_in_csv(account, 'funded')
                if results_from_csv:
                    st.text("Hay resultados en el fichero csv, ¿quieres guardarlos en la base de datos?")
                    if st.button("Guardar"):
                        # st.info("Ya voy!")
                        results_from_csv = _read_results_in_csv(account, 'funded')
                        best_results = _get_best_results_from_funded_final_results(results_from_csv)
                        try:
                            _insert_best_funded_results_to_supabase(best_results, funded_id, True)
                            # _insert_best_funded_results_to_supabase(best_results_with_conditions, funded_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_results_with_id(funded_id, "funded")
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la cuentas fondeadas en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")


        same_conditions = True
        new_tps: List[Any] = []
        new_sls: List[Any] = []
        new_personal_targets: List[Any] = []
        new_margins: List[Any] = []
        new_combinations = False

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
                if data["results"][0].get(condition) != account["funded_conditions"].get(condition):
                    same_conditions = False
                    st.warning(
                        f'Hay condiciones diferentes de los resultados de la BD como el de {condition}, se realizará la simulación de nuevo.'
                    )

            if same_conditions:
                st.info("Todas las CONDICIONES coinciden con los resultados de la BD.")
                new_tps = list(set(account["funded_conditions"]["f_tps_usd"]) - set(data["results"][0]["f_tps_usd"]))
                new_sls = list(set(account["funded_conditions"]["f_sls_usd"]) - set(data["results"][0]["f_sls_usd"]))
                if not account["funded_conditions"]["f_personal_targets_usd"]:
                    account["funded_conditions"]["f_personal_targets_usd"] = [0]
                if not data["results"][0]["f_personal_targets_usd"]:
                    data["results"][0]["f_personal_targets_usd"] = [0]
                if not account["funded_conditions"]["margins_after_withdrawal"]:
                    account["funded_conditions"]["margins_after_withdrawal"] = [0]
                if not data["results"][0]["margins_after_withdrawal"]:
                    data["results"][0]["margins_after_withdrawal"] = [0]
                new_personal_targets = list(set(account["funded_conditions"]["f_personal_targets_usd"]) - set(data["results"][0]["f_personal_targets_usd"]))
                new_margins = list(set(account["funded_conditions"]["margins_after_withdrawal"]) - set(data["results"][0]["margins_after_withdrawal"]))
                if new_tps:
                    st.warning(f'Hay TPs que faltan en la BD: {new_tps}.')
                if new_sls:
                    st.warning(f'Hay SLs que faltan en la BD: {new_sls}.')
                if new_personal_targets:
                    st.warning(f'Hay personal_targets que faltan en la BD: {new_personal_targets}.')
                if new_margins:
                    st.warning(f'Hay margins que faltan en la BD: {new_margins}.')
                if new_tps or new_sls or new_personal_targets or new_margins:
                    new_combinations = True

        if not data["results"] or not same_conditions or new_combinations:
            save_requisites = _should_save_results(config, 'funded')
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
                    final_results, best_results = montecarlo_simulation_funded(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_funded_results_to_save(final_results, best_results, account)
                    if _should_save_results(config, 'funded') and guardar:
                        csv_path = _save_funded_final_results_in_csv(final_results_with_conditions, account, new_file=True)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    if _should_save_results(config, 'funded') and guardar:
                        try:
                            _insert_best_funded_results_to_supabase(best_results_with_conditions, funded_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_results_with_id(funded_id, "funded")
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la cuentas fondeadas en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and new_combinations:
                    combinations = [c for c in combinations if c["tp"] in new_tps or c["sl"] in new_sls or c["personal_target"] in new_personal_targets or c["margin"] in new_margins]
                    final_results, best_results = montecarlo_simulation_funded(account, config, combinations)
                    final_results_with_conditions, best_results_with_conditions = _normalize_funded_results_to_save(
                        final_results, best_results, account
                    )
                    if _should_save_results(config, 'funded') and guardar:
                        csv_path = _save_funded_final_results_in_csv(final_results_with_conditions, account, new_file=False)
                        final_results_with_conditions = _read_results_in_csv(account, "funded")
                        funded_conditions = account["funded_conditions"]
                        for result in final_results_with_conditions:
                            for key, value in funded_conditions.items():
                                if key in result:
                                    result[key] = value
                        csv_path = _save_funded_final_results_in_csv(final_results_with_conditions, account, new_file=True)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning("No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    best_results_with_conditions = _get_best_results_from_funded_final_results(final_results_with_conditions)
                    if _should_save_results(config, 'funded') and guardar:
                        try:
                            _insert_best_funded_results_to_supabase(best_results_with_conditions, funded_id, delete=True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_results_with_id(funded_id, "funded")
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la cuentas fondeadas en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data["results"])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")



def render_funded_page() -> None:
    st.title(":violet[Fonadeadas] - PropVision")
    st.caption("Simulaciones de cuentas fondeadas para prop firms con enfoque Monte Carlo.")
    _render_simulation_page(
        page_label="cuentas fondeadas",
        selector_label="Selector de cuentas fondeadas",
        select_prompt="Selecciona cuentas fondeadas",
        example_label="Ejemplo de cuentas fondeadas",
        montecarlo_label="Simulación de Montecarlo de cuentas fondeadas",
        simulate_fn=simulate_funded,
    )


if __name__ == "__main__":
    st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")
    render_funded_page()
