from __future__ import annotations

from typing import Any, Dict, List

from pathlib import Path
from src.propvision.db import supabase

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status, load_eval_results_with_id
from src.propvision.simulator import SimulationConfig, build_example_context, simulate_eval, _build_combinations, _get_reset_cost, _should_save_results, _save_final_results_in_csv, _insert_best_results_to_supabase, montecarlo_simulation, _normalize_results_to_save, _read_results_in_csv, _get_best_results_from_final_results

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
        with st.expander("Configuración para la simulación", expanded=True):
            num_sims = st.number_input("Número de simulaciones (mín. 200000 para poder guardar)", min_value=1, max_value=500000, value=200000, step=1000)
            modes = st.segmented_control("Mode (All para poder guardar)", list(SimulationConfig.modes) + ["All"], default=["All"])
            if modes == "All": modes = SimulationConfig.modes
            else:
                modes = [modes]
            col21, col22 = st.columns(2)
            with col21:
                min_reset = st.number_input("Reset trades mínimo (0 para poder guardar), sólo pares", min_value=min(SimulationConfig().reset_trades), max_value=max(SimulationConfig().reset_trades), value=0, step=1)
            with col22:
                max_reset = st.number_input("Reset trades máximo (20 para poder guardar), sólo pares", min_value=min(SimulationConfig().reset_trades), max_value=max(SimulationConfig().reset_trades), value=20, step=1)
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
            if len(combinations):
                st.info("Hay %d combinaciones." % len(combinations))
            else:
                st.warning("Hay %d combinaciones." % len(combinations))
            

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

        #* Si en la BD hay guardados los resultados de esta evaluación con las mismas condiciones, no se ejecutará, se mostrarán los resultados
        # Obtener resultados (si hay)
        eval_id = account['eval1_id']
        data = load_eval_results_with_id(eval_id)
        if data['exc']:
            st.error(f'Error con supabase: {data['exc']}')
        elif not data['results']:
            st.info('No se encontraron resultados para esta evaluación en la base de datos.')
        new_prices = []
        new_tps = []
        new_sls = []
        same_conditions = True
        if data['results']:
            st.markdown(
                """
                <div style="line-height:1.7;">
                <strong>Registros previos</strong><br>
                """,
                unsafe_allow_html=True,
            )
            st.dataframe(data['results'])
            # Comprobar si las condiciones actuales coinciden con los de los resultados guardados
            eval_conditions_fields = ['e_target_usd', 'e_mdd_usd', 'e_mdd_type', 'e_ddd_usd', 'e_consistency_pct', 'e_min_days', 'e_min_profit_days', 'e_profit_day_usd', 'reset_prices','e_suscription_type', 'activation_fee_usd']
            for condition in eval_conditions_fields:
                if data['results'][0].get(condition) != account['eval1_conditions'].get(condition):
                    same_conditions = False
                    st.warning(f'Hay condiciones diferentes de los resultados de la BD como el de {condition}, se realizará la simulación de nuevo.')
            # Comprobar si hay precios nuevos
            if same_conditions:
                st.info(f'Todas las CONDICIONES coinciden con los resultados de la BD.')
                new_prices = list(set(account['eval1_conditions']['eval_prices']) - set(data['results'][0]['eval_prices']))
                new_tps = list(set(account['eval1_conditions']['e_tps_usd']) - set(data['results'][0]['e_tps_usd']))
                new_sls = list(set(account['eval1_conditions']['e_sls_usd']) - set(data['results'][0]['e_sls_usd']))
                if new_prices:
                    st.warning(f'Hay precios que faltan en la BD: {new_prices}.')
                if new_tps:
                    st.warning(f'Hay TPs que faltan en la BD: {new_tps}.')
                if new_sls:
                    st.warning(f'Hay SLs que faltan en la BD: {new_sls}.')
        
        if not data['results'] or not same_conditions or new_prices or new_tps or new_sls and len(combinations):
            save_requisites = _should_save_results(config)
            guardar = st.toggle("Guardar", disabled=not save_requisites, value=True)
            if save_requisites:
                st.success("Esta configuración cumple con los requisitos para guardar los resultados de las simulaciones de Montecarlo.")
            if not save_requisites:
                st.warning("Esta configuración NO cumple con los requisitos para guardar los resultados de las simulaciones de Montecarlo.")
            if st.button("Empezar Montecarlo"):
                if not guardar:
                    st.dialog('Los resultados de esta simulación No se guardarán.', width="small", dismissible=True, icon=None, on_dismiss="ignore")

                if not data['results'] or not same_conditions:
                    # 1.- Combinaciones sin filtros
                    # 2.- Montecarlo simulations
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    # 3.- Normalizar resultados para guardar
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(final_results, best_results, account)
                    # 4.- Guardar fichero csv
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file= True)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning(f"No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    # 5.- Guardar en Supabase, eliminar si hay registros anteriores
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete= True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data['results'])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and new_prices and not new_tps and not new_sls:
                    # 1.- Filtrar combinaciones, sólo nuevos precios
                    combinations = [c for c in combinations if c['price'] in new_prices]
                    # 2.- Simulaciones de Montecarlo
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    # 3.- Normalizar resultados para guardar
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(final_results, best_results, account)
                    # 4.- Añadir a fichero csv existente
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file= False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning(f"No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    
                    # 5.- Guardar en Supabase, añadir sin eliminar
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete= False)
                            st.success("Resultados guardados en Supabase.")
                            # Actualizar los registros anteriores con los nuevos precios
                            response = (
                                supabase.table("eval_sim_results")
                                .update({"eval_prices": account['eval1_conditions']['eval_prices']})
                                .eq("eval_id", eval_id)
                                .execute()
                            )
                            st.success('Registros anteriores actualizado con eval_prices completo.')
                            # Obtener todos los registros de Supabase
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data['results'])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")
                elif same_conditions and (new_tps or new_sls) and not new_prices:
                    # 1.- Filtrar combinaciones, sólo nuevos tps o sls
                    combinations = [c for c in combinations if c['tp'] in new_tps or c['sl'] in new_sls]
                    # 2.- Simulaciones de Montecarlo
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    # 3.- Normalizar resultados para guardar
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(final_results, best_results, account)
                    # 4.- Añadir a fichero csv existente
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file= False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning(f"No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    # 5.- Obtener best_results del fichero csv
                    final_results_with_conditions = _read_results_in_csv(account)
                    best_results_with_conditions = _get_best_results_from_final_results(final_results_with_conditions)
                    # print('******************-------------****************---------------************-----------------')
                    # print('final_results_with_conditions from csv:')
                    # for f in final_results_with_conditions:
                    #     print(f)
                    # print('best_results_with_conditions from csv:')
                    # for b in best_results_with_conditions:
                    #     print(b)
                        
                    # 6.- Guardar en Supabase, añadir sin eliminar
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete= True)
                            st.success("Resultados guardados en Supabase.")
                            # Actualizar los registros anteriores con los nuevos tps y sls
                            response = (
                                supabase.table("eval_sim_results")
                                .update({"e_tps_usd": account['eval1_conditions']['e_tps_usd'], "e_sls_usd": account['eval1_conditions']['e_sls_usd']})
                                .eq("eval_id", eval_id)
                                .execute()
                            )
                            st.success('Registros anteriores actualizado con eval_prices completo.')
                            # Obtener todos los registros de Supabase
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data['results'])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")

                elif same_conditions and new_prices and (new_tps or new_sls):
                    # 1.- Filtrar combinaciones, sólo nuevos precios
                    new_prices_combinations = [c for c in combinations if c['price'] in new_prices and not c['tp'] in new_tps and not c['sl'] in new_sls]
                    # 2.- Simulaciones de Montecarlo
                    final_results, best_results = montecarlo_simulation(account, config, new_prices_combinations)
                    # 3.- Normalizar resultados para guardar
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(final_results, best_results, account)
                    # 4.- Añadir a fichero csv existente
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file= False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    else:
                        st.warning(f"No se cumplen las condiciones de guardado o se ha seleccionado no guardar")
                    # 5.- Combinaciones, con todos los precios, pero sólo con los nuevos tps y sls
                    combinations = _build_combinations(account, config)
                    combinations = [c for c in combinations if c['tp'] in new_tps or c['sl'] in new_sls]
                    # 6.- Simulaciones de Montecarlo
                    final_results, best_results = montecarlo_simulation(account, config, combinations)
                    # 7.- Normalizar resultados para guardar
                    final_results_with_conditions, best_results_with_conditions = _normalize_results_to_save(final_results, best_results, account)
                    # 8.- Añadir a csv
                    if _should_save_results(config) and guardar:
                        csv_path = _save_final_results_in_csv(final_results_with_conditions, account, new_file= False)
                        st.success(f"Resultados exportados a CSV: {csv_path}")
                    # 9.- Obtener best_results del fichero csv
                    final_results_with_conditions = _read_results_in_csv(account)
                    best_results_with_conditions = _get_best_results_from_final_results(final_results_with_conditions)
                    # 10.- Guardar en Supabase, eliminar si hay registros anteriores
                    if _should_save_results(config) and guardar:
                        try:
                            _insert_best_results_to_supabase(best_results_with_conditions, eval_id, delete= True)
                            st.success("Resultados guardados en Supabase.")
                            data = load_eval_results_with_id(eval_id)
                            st.markdown(
                                """
                                <div style="line-height:1.7;">
                                <strong>Todos los resultados de la evaluación en la base de datos:</strong><br>
                                """,
                                unsafe_allow_html=True,
                            )
                            st.dataframe(data['results'])
                        except Exception as exc:
                            st.warning(f"No se pudo guardar en Supabase: {exc}")



if __name__ == "__main__":
    main()
