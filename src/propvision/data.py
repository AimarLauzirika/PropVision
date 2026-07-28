from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()


def _format_account_name(account: Dict[str, Any]) -> str:
    company = account.get("company") or {}
    short_name = company.get("short_name") or f"C{account.get('company_id', '?')}"
    company_id = company.get("id") or account.get("company_id") or "?"
    account_id = account.get("id") or "?"
    return f"{short_name} ({company_id}) - {account.get('name', 'Cuenta')} ({account_id})"


def get_supabase_key() -> str | None:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")


def _mock_accounts() -> List[Dict[str, Any]]:
    return [
        {
            "id": 1,
            "name": "GAUU50",
            "company_id": 1,
            "initial_balance": 10000,
            "e1_target_usd": 12000,
            "e_mdd_type": "static",
            "a_mdd_usd": 8000,
            "e_ddd_usd": None,
            "e_highest_mdd_account": 9000,
            "e_consistency_pct": None,
            "e_min_days": 5,
            "e_min_profit_days": 0,
            "a_profit_day_usd": 50,
            "e_suscription_type": "one_time_30_days",
            "activation_fee_usd": 100,
            "activation_fee_type": "always",
            "e_tps_usd": [100, 150],
            "e_sls_usd": [100, 150],
            "reset_prices": None,
            "eval_prices": [50, 75],
            "company": {"id": 1, "short_name": "E2T"},
        }
    ]


def load_accounts_with_status() -> Tuple[List[Dict[str, Any]], str]:
    url = os.getenv("SUPABASE_URL")
    key = get_supabase_key()
    if not url or not key:
        return _mock_accounts(), "No hay URL o clave de Supabase configuradas; se están mostrando cuentas de ejemplo locales."

    try:
        # Companies endpoint
        response_companies = requests.get(
            f"{url}/rest/v1/companies?select=id,short_name,long_name,ddd_soft_breach",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if response_companies.status_code >= 400:
            error_text = response_companies.text[:200]
            return _mock_accounts(), f"Supabase devolvió {response_companies.status_code}: {error_text}"

        companies = {company["id"]: company for company in response_companies.json()}

        # Accounts endpoint
        response_accounts = requests.get(
            f"{url}/rest/v1/accounts?select=id,name,company_id,initial_balance,eval1_id",
            # f"{url}/rest/v1/accounts?select=id,name,company_id,initial_balance,e1_target_usd,e_mdd_type,a_mdd_usd,e_ddd_usd,e_consistency_pct,e_min_days,e_min_profit_days,a_profit_day_usd,e_suscription_type,activation_fee_usd,e_tps_usd,e_sls_usd,reset_prices,eval_prices,eval1_id",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if response_accounts.status_code >= 400:
            error_text = response_accounts.text[:200]
            return _mock_accounts(), f"Supabase devolvió {response_accounts.status_code}: {error_text}"

        # Eval conditions endpoint
        response_evals = requests.get(
            f"{url}/rest/v1/evals?select=id,name,e_target_usd,e_mdd_type,e_mdd_usd,e_ddd_usd,e_consistency_pct,e_min_days,e_min_profit_days,e_profit_day_usd,e_suscription_type,activation_fee_usd,e_tps_usd,e_sls_usd,reset_prices,eval_prices",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if response_evals.status_code >= 400:
            error_text = response_evals.text[:200]
            return _mock_accounts(), f"Supabase devolvió {response_evals.status_code}: {error_text}"

        evals = {condition["id"]: condition for condition in response_evals.json()}

        accounts = response_accounts.json()
        for account in accounts:
            company_id = account.get("company_id")
            company = companies.get(company_id)
            # company = companies.get(company_id) or {
            #     "id": company_id,
            #     "short_name": "UNK",
            #     "long_name": "Sin empresa",
            # }
            # if "long_name" not in company:
            #     company["long_name"] = company.get("short_name") or "Sin empresa"
            account["company"] = company
            eval1_id = account.get("eval1_id")
            eval1_conditions = evals.get(eval1_id)
            account["eval1_conditions"] = eval1_conditions
        accounts.sort(key=lambda item: (item.get("company", {}).get("short_name", ""), item.get("name", "")))
        return accounts, f"Conectado a Supabase correctamente ({len(accounts)} cuentas cargadas)."
    except requests.RequestException as exc:
        return _mock_accounts(), f"No se pudo contactar con Supabase: {exc}"
    except Exception as exc:
        return _mock_accounts(), f"Error inesperado al cargar cuentas de Supabase: {exc}"


# def load_accounts() -> List[Dict[str, Any]]:
#     accounts, _ = load_accounts_with_status()
#     return accounts


# def get_account_groups(accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#     grouped: Dict[str, List[Dict[str, Any]]] = {}
#     for account in accounts:
#         company = account.get("company") or {}
#         company_key = company.get("short_name") or f"C{account.get('company_id', '?')}"
#         grouped.setdefault(company_key, []).append(account)

#     groups = []
#     for key in sorted(grouped):
#         group_accounts = sorted(grouped[key], key=lambda item: item.get("name", ""))
#         groups.append({"company_name": key, "accounts": group_accounts})
#     return groups
