import pandas as pd

from src.results import (
    _build_account_price_options,
    _build_account_selection_options,
    _filter_account_result_rows,
    _get_account_criteria_options,
    _find_accounts_with_invalid_prices,
)


def test_build_account_selection_options_groups_by_company_and_account():
    dataframe = pd.DataFrame(
        [
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 100, "criteria": "total_profits"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 120, "criteria": "total_profits"},
            {"account_id": 2, "company_name": "Acme", "account_name": "Beta", "price": 90, "criteria": "payouts/month"},
            {"account_id": 3, "company_name": "Nova", "account_name": "Gamma", "price": 130, "criteria": "total_profits"},
        ]
    )

    options = _build_account_selection_options(dataframe)

    assert [option["label"] for option in options] == ["Acme | Alpha", "Acme | Beta", "Nova | Gamma"]
    assert {option["account_id"] for option in options} == {1, 2, 3}


def test_account_price_and_criteria_are_selected_per_account():
    dataframe = pd.DataFrame(
        [
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 100, "criteria": "total_profits"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 120, "criteria": "total_profits"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 120, "criteria": "payouts/month"},
            {"account_id": 2, "company_name": "Acme", "account_name": "Beta", "price": 100, "criteria": "total_profits"},
        ]
    )
    accounts = [{
        "id": 1,
        "name": "Alpha",
        "current_price": 120,
        "eval1_conditions": {
            "eval_prices": [50, 100, 120],
        },
    }]

    assert _build_account_price_options(dataframe, 1, accounts=accounts) == [50.0, 100.0, 120.0]
    assert _get_account_criteria_options(dataframe, 1, 120) == ["total_profits", "p_prob/payouts", "payouts/month"]

    matches = _filter_account_result_rows(dataframe, 1, 120, "total_profits")
    assert len(matches) == 1
    assert matches.iloc[0]["criteria"] == "total_profits"
    assert matches.iloc[0]["price"] == 120


def test_results_search_uses_full_account_dataset_and_fixed_criteria():
    dataframe = pd.DataFrame(
        [
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 50, "criteria": "total_profits"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 75, "criteria": "p_prob/payouts"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 75, "criteria": "payouts/month"},
            {"account_id": 1, "company_name": "Acme", "account_name": "Alpha", "price": 100, "criteria": "total_profits"},
        ]
    )

    assert _get_account_criteria_options(dataframe, 1, 75) == ["total_profits", "p_prob/payouts", "payouts/month"]
    matches = _filter_account_result_rows(dataframe, 1, 75, "payouts/month")
    assert len(matches) == 1
    assert matches.iloc[0]["price"] == 75


def test_find_accounts_with_invalid_current_price():
    dataframe = pd.DataFrame(
        [
            {"account_id": 1},
            {"account_id": 2},
            {"account_id": 3},
        ]
    )
    accounts = [
        {"id": 1, "name": "Valid", "current_price": 50, "eval1_conditions": {"eval_prices": [50, 75]}},
        {"id": 2, "name": "Missing", "current_price": None, "eval1_conditions": {"eval_prices": [100, 125]}},
        {"id": 3, "name": "Invalid", "current_price": 90, "eval1_conditions": {"eval_prices": [100, 125]}},
    ]

    invalid = _find_accounts_with_invalid_prices(dataframe, accounts)

    assert [account["id"] for account in invalid] == [2, 3]
