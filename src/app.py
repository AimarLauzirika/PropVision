from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

from src.propvision.data import _format_account_name, load_accounts_with_status
from src.propvision.simulator import SimulationConfig, build_example_context, simulate_account, simulate_example

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 100% !important;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    div[data-baseweb="multi-select"] > div:first-child {
        max-height: 320px;
        overflow-y: auto;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    st.title("PropVision")
    st.caption("Simulaciones de evaluación para prop firms con enfoque Monte Carlo.")

    with st.expander("Selector de cuentas", expanded=True):
        accounts, connection_status = load_accounts_with_status()
        # print(accounts)
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

        # visible_accounts = [
        #     account
        #     for account in filtered_accounts
        #     if search.lower() in _format_account_name(account).lower()
        #     or search.lower() in account.get("name", "").lower()
        #     or search.lower() in (account.get("company", {}).get("long_name") or "").lower()
        # ]

        account_options = [_format_account_name(account) for account in filtered_accounts]
        selected_labels = st.multiselect(
            "Selecciona cuentas",
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

    with st.expander("Parámetros de simulación", expanded=True):
        num_sims = st.number_input("Número de simulaciones", min_value=1, max_value=500000, value=1000, step=1000)
        modes = st.multiselect("Mode", ["fixed", "variable"], default=["fixed", "variable"])
        min_reset = st.number_input("Reset trades mínimo", min_value=0, max_value=20, value=5, step=1)
        max_reset = st.number_input("Reset trades máximo", min_value=0, max_value=20, value=5, step=1)
        if min_reset > max_reset:
            st.error("El máximo de reset trades debe ser mayor o igual al mínimo.")
            st.stop()

        if st.button("Empezar simulación"):
            if not modes:
                st.error("Debes seleccionar al menos un Mode para lanzar la simulación.")
                st.stop()
            if not selected_accounts:
                st.error("Selecciona al menos una cuenta para ejecutar la simulación.")
                st.stop()

            config = SimulationConfig(num_sims=num_sims, modes=modes, reset_trades=tuple(range(min_reset, max_reset + 1)))
            results_by_account = []
            for account in selected_accounts:
                account_results = simulate_account(account, config)
                for row in account_results:
                    results_by_account.append({**row, "account_name": _format_account_name(account)})

            st.session_state["results"] = results_by_account
            st.session_state["account_name"] = ", ".join(_format_account_name(account) for account in selected_accounts)
            st.session_state["selected_combo"] = None

    if "results" in st.session_state:
        st.subheader(f"Resultados para {st.session_state['account_name']}")
        results = st.session_state["results"]
        df = [
            {
                **row,
                "cost_fund": f"{row['cost_fund']:.2f}",
                "prob_pass": f"{row['prob_pass']:.2%}",
            }
            for row in results
        ]
        st.dataframe(df, use_container_width=True)

        best = min(results, key=lambda row: row["cost_fund"])
        st.success(f"Combinación óptima: Price {best['price']} | Mode {best['mode']} | TP {best['tp']} | SL {best['sl']} | Reset {best['reset_trades']} | Cuenta {best['account_name']} | Coste fundado {best['cost_fund']:.2f}")

        selected_index = st.selectbox(
            "Selecciona una combinación para ver un ejemplo",
            options=range(len(results)),
            format_func=lambda idx: f"Price {results[idx]['price']} | Mode {results[idx]['mode']} | TP {results[idx]['tp']} | SL {results[idx]['sl']} | Reset {results[idx]['reset_trades']}",
        )
        if st.button("Generar nuevo ejemplo"):
            combo = results[selected_index]
            account = next((account for account in selected_accounts if _format_account_name(account) == combo.get("account_name", "")), None)
            if account is None:
                account = selected_accounts[0] if selected_accounts else (filtered_accounts[0] if filtered_accounts else accounts[0])
            seed = int(st.session_state.get("example_seed", 0)) + 1
            st.session_state["example_seed"] = seed
            trades = simulate_example(account, combo, seed=seed)
            st.session_state["example_trades"] = trades
            st.session_state["example_combo"] = combo

        if "example_trades" in st.session_state:
            st.subheader("Ejemplo de ejecución trade a trade")
            combo = st.session_state["example_combo"]
            context = build_example_context(account, combo) if "account" in locals() else build_example_context(selected_accounts[0], combo)
            st.markdown(
                f"""
                <div style="line-height:1.7;">
                <strong>Cuenta:</strong> {combo.get('account_name', st.session_state['account_name'])}<br>
                <strong>Configuración:</strong> Price {combo['price']} | Mode {combo['mode']} | TP {combo['tp']} | SL {combo['sl']} | Reset {combo['reset_trades']}<br>
                <strong>Parámetros por combinación:</strong> Price eval {context['price_eval']} | Reset cost {context['reset_cost']} | Comisión {context['commission']:.0f} | Objetivo inicial {context['target_initial']:.0f} | Objetivo consistencia {context['target_consist']:.0f} | Objetivo evaluación {context['target_eval']:.0f} | Coste activación {context['activation_cost']:.0f}<br>
                <strong>Resultados:</strong> Probabilidad de pasar {combo['prob_pass']:.2%} | Coste fundado {combo['cost_fund']:.2f}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.dataframe(st.session_state["example_trades"], use_container_width=True)


if __name__ == "__main__":
    main()
