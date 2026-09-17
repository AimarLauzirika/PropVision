from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.propvision.data import _format_account_name, load_accounts_with_status, load_all_accounts_results
from src.propvision.db import supabase


DISPLAY_COLUMNS = [
    "company_name",
    "account_name",
    "current_price",
    "price",
    "criteria",
    "roi",
    "funded_profit",
    "mdd",
    "pass_prob",
    "f_payout_prob",
    "a_payout_prob",
    "max_a_without_payout",
]


DEFAULT_ACCOUNT_CRITERIA = ["total_profits", "p_prob/payouts", "payouts/month"]


def _build_account_selection_options(dataframe: pd.DataFrame) -> List[Dict[str, Any]]:
    if dataframe.empty:
        return []

    account_rows = (
        dataframe.loc[:, ["account_id", "company_name", "account_name"]]
        .dropna(subset=["account_id"])
        .drop_duplicates()
        .sort_values(["company_name", "account_name", "account_id"], kind="mergesort")
        .to_dict("records")
    )

    options: List[Dict[str, Any]] = []
    for row in account_rows:
        company_name = row.get("company_name") or "Sin compañía"
        account_name = row.get("account_name") or f"Cuenta {row.get('account_id')}"
        options.append(
            {
                "account_id": int(row["account_id"]),
                "company_name": company_name,
                "account_name": account_name,
                "label": f"{company_name} | {account_name}",
            }
        )
    return options


def _build_account_price_options(
    dataframe: pd.DataFrame,
    account_id: int | str,
    accounts: List[Dict[str, Any]] | None = None,
) -> List[Any]:
    account = None
    if accounts is not None:
        account = next((item for item in accounts if int(item.get("id")) == int(account_id)), None)

    if account is not None:
        eval_conditions = account.get("eval1_conditions") or {}
        raw_prices = eval_conditions.get("eval_prices") or []
        if raw_prices:
            price_values = sorted({float(price) for price in raw_prices})
            if account.get("current_price") is not None:
                try:
                    current_price = float(account.get("current_price"))
                except (TypeError, ValueError):
                    current_price = None
                if current_price is not None and current_price not in price_values:
                    price_values.insert(0, current_price)
            return price_values

    account_rows = dataframe[dataframe["account_id"] == account_id].copy()
    if account_rows.empty:
        return []

    prices = pd.to_numeric(account_rows["price"], errors="coerce").dropna().unique().tolist()
    return sorted({float(price) for price in prices})


def _format_price_option(price: Any, current_price: Any = None) -> str:
    value = float(price)
    if current_price is not None:
        try:
            current_value = float(current_price)
        except (TypeError, ValueError):
            current_value = None
        if current_value is not None and value == current_value:
            return f"{value:.2f} (actual)"
    return f"{value:.2f}"


def _parse_price_option(value: str) -> float:
    return float(value.replace(" (actual)", ""))


def _get_account_criteria_options(
    dataframe: pd.DataFrame, account_id: int | str, selected_price: Any
) -> List[str]:
    _ = dataframe, account_id, selected_price
    return list(DEFAULT_ACCOUNT_CRITERIA)


def _filter_account_result_rows(
    dataframe: pd.DataFrame, account_id: int | str, selected_price: Any, selected_criteria: Any
) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    base = dataframe[dataframe["account_id"] == account_id].copy()
    if selected_price is None:
        return base

    selected_price_value = pd.to_numeric(selected_price, errors="coerce")
    filtered = base[
        pd.to_numeric(base["price"], errors="coerce") == selected_price_value
    ].copy()
    if selected_criteria is None:
        return filtered

    filtered = filtered[filtered["criteria"].astype(str) == str(selected_criteria)]
    return filtered


def _load_results() -> List[Dict[str, Any]]:
    response = load_all_accounts_results()
    if response.get("exc"):
        st.error(f"No se pudieron cargar los resultados: {response['exc']}")
        return []
    return response.get("results", [])


def _with_account_metadata(
    results: List[Dict[str, Any]], accounts: List[Dict[str, Any]]
) -> pd.DataFrame:
    accounts_by_id = {account.get("id"): account for account in accounts}
    rows = []
    for result in results:
        account = accounts_by_id.get(result.get("account_id"), {})
        company = account.get("company") or {}
        row = dict(result)
        row["account_name"] = account.get("name", f"Cuenta {result.get('account_id', '?')}")
        row["company_name"] = (
            company.get("long_name") or company.get("short_name") or "Sin compañía"
        )
        row["current_price"] = account.get("current_price")
        rows.append(row)
    return pd.DataFrame(rows)


def _find_accounts_with_invalid_prices(
    dataframe: pd.DataFrame, accounts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if dataframe.empty or "account_id" not in dataframe.columns:
        return []

    result_account_ids = set(
        pd.to_numeric(dataframe["account_id"], errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )
    invalid_accounts = []

    for account in accounts:
        account_id = account.get("id")
        if account_id is None or int(account_id) not in result_account_ids:
            continue

        eval_conditions = account.get("eval1_conditions") or {}
        eval_prices = eval_conditions.get("eval_prices") or []
        valid_prices = []
        for price in eval_prices:
            try:
                valid_prices.append(float(price))
            except (TypeError, ValueError):
                continue

        try:
            current_price = float(account.get("current_price"))
        except (TypeError, ValueError):
            current_price = None

        if current_price is None or current_price not in valid_prices:
            invalid_accounts.append(account)

    return invalid_accounts


def _format_conditions(conditions: Any) -> Dict[str, Any]:
    if not isinstance(conditions, dict):
        return {"estado": "No hay condiciones disponibles"}
    return conditions


def _filter_by_price_view(dataframe: pd.DataFrame, price_view: str) -> pd.DataFrame:
    if price_view == "Todos los resultados":
        return dataframe

    prices = pd.to_numeric(dataframe["price"], errors="coerce")
    if price_view == "Precios actuales":
        current_prices = pd.to_numeric(dataframe["current_price"], errors="coerce")
        return dataframe[prices.eq(current_prices)]

    minimum_prices = prices.groupby(dataframe["account_id"]).transform("min")
    return dataframe[prices.eq(minimum_prices)]


def render_results_page() -> None:
    st.title("PropVision — Resultados")

    accounts, connection_status = load_accounts_with_status()
    if "Conectado" in connection_status:
        st.success(connection_status)
    else:
        st.warning(connection_status)

    dataframe = _with_account_metadata(_load_results(), accounts)
    if dataframe.empty:
        st.info("No hay resultados de cuentas para mostrar.")
        return

    invalid_price_accounts = _find_accounts_with_invalid_prices(dataframe, accounts)
    if invalid_price_accounts:
        st.warning(
            "Hay cuentas con resultados cuyo precio actual no coincide con "
            "ningún precio disponible en eval1_conditions.eval_prices. "
            "Selecciona un precio válido para continuar."
        )
        pending_updates = False
        for account in invalid_price_accounts:
            account_id = account["id"]
            company = account.get("company") or {}
            company_name = company.get("long_name") or company.get("short_name") or "Sin compañía"
            account_name = account.get("name") or f"Cuenta {account_id}"
            eval_conditions = account.get("eval1_conditions") or {}
            eval_prices = []
            for price in eval_conditions.get("eval_prices") or []:
                try:
                    numeric_price = float(price)
                except (TypeError, ValueError):
                    continue
                if numeric_price not in eval_prices:
                    eval_prices.append(numeric_price)

            with st.container(border=True):
                st.markdown(f"**{company_name} | {account_name}**")
                if not eval_prices:
                    st.error("Esta cuenta no tiene precios válidos en eval_prices para seleccionar.")
                    pending_updates = True
                    continue

                pending_updates = True
                with st.form(f"set_current_price_{account_id}"):
                    selected_price = st.segmented_control(
                        "Precio actual",
                        options=sorted(eval_prices),
                        default=sorted(eval_prices)[0],
                    )
                    save_price = st.form_submit_button("Guardar precio", type="primary")

                if save_price:
                    try:
                        query = (
                            supabase.table("accounts")
                            .update({"current_price": selected_price})
                            .eq("id", account_id)
                            .select("id,current_price")
                            .execute()
                        )
                        if query.data:
                            st.success("Precio actual guardado correctamente.")
                            st.rerun()
                        st.error("No se encontró la cuenta para actualizar.")
                    except Exception as exc:
                        st.error(f"No se pudo guardar el precio actual: {exc}")

        if pending_updates:
            return

    with st.sidebar:
        st.subheader("Filtros")
        price_view = st.segmented_control(
            "Precios a mostrar",
            ["Precios actuales", "Precio menor", "Todos los resultados"],
            default="Precios actuales",
        )
        price_filtered = _filter_by_price_view(dataframe, price_view)

        company_options = sorted(price_filtered["company_name"].dropna().unique().tolist())
        selected_companies = st.multiselect("Compañía", company_options)

        company_filtered = price_filtered
        if selected_companies:
            company_filtered = price_filtered[price_filtered["company_name"].isin(selected_companies)]

        name_options = sorted(company_filtered["account_name"].dropna().unique().tolist())
        selected_names = st.multiselect("Nombre", name_options)
        criteria_options = sorted(price_filtered["criteria"].dropna().unique().tolist())
        selected_criteria = st.multiselect("Criterio", criteria_options)

        sort_options = [column for column in dataframe.columns if column not in {"account_id"}]
        sort_column = st.selectbox("Ordenar por", sort_options, index=sort_options.index("roi") if "roi" in sort_options else 0)
        descending = st.toggle("Orden descendente", value=True)

    filtered = _filter_by_price_view(dataframe, price_view)
    if selected_companies:
        filtered = filtered[filtered["company_name"].isin(selected_companies)]
    if selected_names:
        filtered = filtered[filtered["account_name"].isin(selected_names)]
    if selected_criteria:
        filtered = filtered[filtered["criteria"].isin(selected_criteria)]
    filtered = filtered.sort_values(sort_column, ascending=not descending, na_position="last")

    st.caption(f"{len(filtered)} resultados mostrados de {len(dataframe)}")
    visible_columns = [column for column in DISPLAY_COLUMNS if column in filtered.columns]
    st.dataframe(
        filtered[visible_columns],
        hide_index=True,
        width="stretch",
        column_config={
            "current_price": st.column_config.NumberColumn("Precio actual", format="$%.2f"),
            "price": st.column_config.NumberColumn("Precio simulado", format="$%.2f"),
            "roi": st.column_config.NumberColumn("ROI", format="%.2f"),
            "funded_profit": st.column_config.NumberColumn("Beneficio fondeada", format="$%.2f"),
            "mdd": st.column_config.NumberColumn("Drawdown", format="$%.2f"),
            "pass_prob": st.column_config.NumberColumn("Prob. superar", format="%.3f"),
            "f_payout_prob": st.column_config.NumberColumn("Prob. payout", format="%.3f"),
            "a_payout_prob": st.column_config.NumberColumn("Prob. cuenta rentable", format="%.3f"),
        },
    )

    account_options = _build_account_selection_options(filtered)
    if not account_options:
        st.info("No hay resultados que coincidan con los filtros.")
        return

    selected_account_option = st.selectbox(
        "Seleccionar cuenta",
        account_options,
        format_func=lambda option: option["label"],
    )
    selected_account_id = selected_account_option["account_id"]
    selected_account_rows = dataframe[dataframe["account_id"] == selected_account_id].copy()
    selected_account = next(
        account for account in accounts if account.get("id") == selected_account_id
    )

    price_options = _build_account_price_options(
        dataframe,
        selected_account_id,
        accounts=accounts,
    )
    if not price_options:
        st.warning("La cuenta seleccionada no tiene precios disponibles para mostrar.")
        return

    current_account_price = selected_account.get("current_price")
    try:
        current_price_value = float(current_account_price) if current_account_price is not None else None
    except (TypeError, ValueError):
        current_price_value = None

    price_labels = [
        _format_price_option(price, current_account_price)
        for price in price_options
    ]
    if current_price_value is not None and current_price_value in price_options:
        default_selected_label = _format_price_option(current_price_value, current_account_price)
    else:
        default_selected_label = price_labels[0]

    selected_price_label = st.segmented_control(
        "Precio",
        options=price_labels,
        default=default_selected_label,
    )
    selected_price = _parse_price_option(selected_price_label)
    st.caption("El precio actual aparece destacado con la etiqueta '(actual)'.")

    criteria_options = _get_account_criteria_options(dataframe, selected_account_id, selected_price)
    if not criteria_options:
        st.warning("La cuenta seleccionada no tiene criterios disponibles para el precio elegido.")
        return

    selected_criteria = st.segmented_control(
        "Criterio",
        options=criteria_options,
        default=criteria_options[0],
    )

    matched_results = _filter_account_result_rows(
        dataframe,
        selected_account_id,
        selected_price,
        selected_criteria,
    )
    if matched_results.empty:
        st.warning("No hay resultados que coincidan con la cuenta, precio y criterio seleccionados.")
        st.write("Resultados buscados en la lista completa de la cuenta:")
        st.dataframe(selected_account_rows, hide_index=True)
        return

    selected_result = matched_results.iloc[0].to_dict()
    st.subheader("Cuenta seleccionada")
    with st.container(border=True):
        st.write(_format_account_name(selected_account))
        st.write(selected_result)

        if selected_account.get("current_price") is not None:
            try:
                current_price_value = float(selected_account.get("current_price"))
            except (TypeError, ValueError):
                current_price_value = float(selected_price)

            eval_conditions = selected_account.get("eval1_conditions") or {}
            possible_prices = list(dict.fromkeys(eval_conditions.get("eval_prices") or []))
            if current_price_value not in possible_prices:
                possible_prices.insert(0, current_price_value)

            with st.form("update_current_price"):
                current_price = st.segmented_control(
                    f"Precio actual de la cuenta (${current_price_value})",
                    options=possible_prices,
                    default=current_price_value,
                )
                update_price = st.form_submit_button("Actualizar precio", type="primary")

            if update_price:
                try:
                    query = (
                        supabase.table("accounts")
                        .update({"current_price": current_price})
                        .eq("id", selected_account_id)
                        .select("id,current_price")
                        .execute()
                    )
                    if query.data:
                        st.success("Precio actualizado correctamente.")
                        st.rerun()
                    else:
                        st.warning("No se encontró la cuenta seleccionada para actualizar.")
                except Exception as exc:
                    st.error(f"No se pudo actualizar el precio: {exc}")

    eval_conditions = selected_account.get("eval1_conditions")
    funded_conditions = selected_account.get("funded_conditions")
    conditions_col1, conditions_col2 = st.columns(2)
    with conditions_col1:
        with st.expander("eval1_conditions", expanded=True):
            st.json(_format_conditions(eval_conditions))
    with conditions_col2:
        with st.expander("funded_conditions", expanded=True):
            st.json(_format_conditions(funded_conditions))


if __name__ == "__main__":
    st.set_page_config(page_title="PropVision", page_icon="📈", layout="wide")
    render_results_page()