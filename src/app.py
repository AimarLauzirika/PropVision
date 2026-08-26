from __future__ import annotations

import streamlit as st

from src.evaluation_accounts import render_evaluation_page
from src.funded_accounts import render_funded_page
from src.account_simulations import render_account_simulations_page
from src.results import render_results_page


def main() -> None:
    st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")

    selected_page = st.sidebar.radio(
        "Navegación",
        ["Evaluaciones", "Cuentas fondeadas", "Simulaciones de cuentas", "Resultados"],
        index=0,
    )

    if selected_page == "Evaluaciones":
        render_evaluation_page()
    elif selected_page == "Cuentas fondeadas":
        render_funded_page()
    elif selected_page == "Simulaciones de cuentas":
        render_account_simulations_page()
    else:
        render_results_page()


if __name__ == "__main__":
    main()
