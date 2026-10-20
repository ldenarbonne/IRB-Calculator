"""Unit tests. Run with:  python -m pytest -q"""
import math

import pandas as pd
import pytest

from capital_engine import (capital_k, compute_portfolio, correlation, maturity_adjustment,
                            output_floor, provisions_vs_el)
from capital_engine.engine import sme_supporting_factor

# Reference values from the author's 2021 Excel IRB calculator (legacy calibration,
# 1.06 scaling factor included), PD = 30 %, LGD = 40 %.
EXCEL_2021 = {
    "RET_OTHER": 0.0866677791723818,
    "CORP_M1": 0.1779786077762703,
    "SME_S40_M1": 0.17135629272162417,
    "RET_RRE": 0.1980549759018316,
    "RET_QRRE": 0.10094241434972834,
    "FSE_LARGE_M1": 0.19805500419594685,
}


def test_reconciliation_with_excel_2021():
    p, l = 0.30, 0.40
    got = {
        "RET_OTHER": capital_k(p, l, correlation("RET_OTHER", p)),
        "CORP_M1": capital_k(p, l, correlation("CORP", p), maturity_adjustment(p, 1)),
        "SME_S40_M1": capital_k(p, l, correlation("CORP", p, 40), maturity_adjustment(p, 1)),
        "RET_RRE": capital_k(p, l, correlation("RET_RRE", p)),
        "RET_QRRE": capital_k(p, l, correlation("RET_QRRE_REV", p)),
        "FSE_LARGE_M1": capital_k(p, l, correlation("FSE_LARGE", p), maturity_adjustment(p, 1)),
    }
    for key, ref in EXCEL_2021.items():
        assert 1.06 * got[key] == pytest.approx(ref, rel=1e-12), key


def test_basel_reference_corporate():
    # BCBS illustrative: PD 1 %, LGD 45 %, M 2.5 -> RW ~ 92.3 % (without 1.06)
    p = 0.01
    k = capital_k(p, 0.45, correlation("CORP", p), maturity_adjustment(p, 2.5))
    assert 12.5 * k == pytest.approx(0.9232, abs=5e-4)


def test_crr3_floors_and_no_scaling():
    df = pd.DataFrame([{"exposure_class": "CORP", "approach": "AIRB", "pd": 0.0001,
                        "lgd": 0.10, "drawn": 1_000_000, "maturity": 2.5}])
    r = compute_portfolio(df, "CRR3").iloc[0]
    assert r.pd_used == pytest.approx(0.0005)
    assert r.lgd_used == pytest.approx(0.25)
    expected = 12.5 * capital_k(0.0005, 0.25, correlation("CORP", 0.0005),
                                maturity_adjustment(0.0005, 2.5))
    assert r.rw_irb == pytest.approx(expected)


def test_firb_secured_lgd():
    # EAD 100, RRE collateral 100 -> ES = 60 after 40 % haircut
    df = pd.DataFrame([{"exposure_class": "CORP", "approach": "FIRB", "pd": 0.01,
                        "drawn": 100.0, "collateral_type": "rre", "collateral_value": 100.0}])
    r = compute_portfolio(df, "CRR3").iloc[0]
    assert r.lgd_used == pytest.approx((40 * 0.40 + 60 * 0.20) / 100)


def test_large_corporate_forced_to_firb():
    df = pd.DataFrame([{"exposure_class": "CORP", "approach": "AIRB", "pd": 0.01, "lgd": 0.2,
                        "drawn": 1e6, "turnover_m": 800}])
    r = compute_portfolio(df, "CRR3").iloc[0]
    assert r.approach_applied == "FIRB" and r.lgd_used == pytest.approx(0.40)


def test_sme_supporting_factor():
    assert sme_supporting_factor(1e6) == pytest.approx(0.7619)
    assert sme_supporting_factor(5e6) == pytest.approx((2.5e6 * 0.7619 + 2.5e6 * 0.85) / 5e6)


def test_sa_rre_loan_splitting():
    df = pd.DataFrame([{"exposure_class": "RET_RRE", "pd": 0.01, "lgd": 0.15,
                        "drawn": 80.0, "property_value": 100.0}])
    r = compute_portfolio(df, "CRR3").iloc[0]
    assert r.rwa_sa == pytest.approx(55 * 0.20 + 25 * 0.75)


def test_output_floor_phase_in_and_cap():
    f = output_floor(100.0, 200.0, 2026)
    assert f.factor == 0.55 and f.trea == pytest.approx(110.0) and f.floor_binding
    f = output_floor(100.0, 300.0, 2027, transitional_cap=True)
    assert f.trea == pytest.approx(125.0) and f.cap_applied
    assert output_floor(100.0, 300.0, 2031).factor == 0.725


def test_defaulted_airb():
    df = pd.DataFrame([{"exposure_class": "CORP", "approach": "AIRB", "pd": 1.0, "lgd": 0.6,
                        "elbe": 0.5, "drawn": 100.0, "provisions": 45.0}])
    res = compute_portfolio(df, "CRR3")
    r = res.iloc[0]
    assert r.K == pytest.approx(0.10) and r.el == pytest.approx(50.0)
    pe = provisions_vs_el(res, res.rwa_irb.sum(), 0.006)
    assert pe["shortfall_cet1_deduction"] == pytest.approx(5.0)
