"""Credit-risk capital engine: IRB (F-IRB / A-IRB), SA-CR, output floor and own funds.

Every function works on one exposure (a ``dict``/``pd.Series``) so the logic stays
readable and auditable; ``compute_portfolio`` vectorises over a DataFrame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import parameters as P

Q999 = norm.ppf(0.999)

# --------------------------------------------------------------------------- #
# Input schema
# --------------------------------------------------------------------------- #
DEFAULTS = {
    "id": None,
    "exposure_class": "CORP",
    "approach": "AIRB",          # FIRB | AIRB (retail always uses own estimates)
    "pd": 0.01,
    "lgd": 0.45,                 # own estimate (A-IRB / retail); ignored in F-IRB
    "seniority": "senior",       # senior | subordinated (F-IRB)
    "collateral_type": "none",
    "collateral_value": 0.0,     # financial: haircut-adjusted value; others: market value
    "property_value": 0.0,       # for SA real-estate treatment (LTV)
    "ipre": 0,                   # income-producing real estate (SA)
    "maturity": 2.5,             # effective maturity in years (corporates)
    "turnover_m": np.nan,        # annual turnover, EUR million
    "drawn": 0.0,
    "undrawn": 0.0,
    "ccf_irb": np.nan,           # own-estimate CCF (A-IRB); default = SA CCF
    "ccf_sa": 0.40,              # SA CCF bucket: 1.00 / 0.50 / 0.40 / 0.20 / 0.10
    "defaulted": 0,
    "elbe": np.nan,              # best estimate of EL for defaulted exposures (A-IRB)
    "provisions": 0.0,           # specific credit risk adjustments
    "sa_cqs": 0,                 # 0 = unrated, 1..6 = credit quality step
    "sa_ig": 0,                  # Art. 465(3): internally assessed IG (PD <= 0.5 %)
    "sme_sf": 0,                 # eligible for the SME supporting factor (Art. 501)
}
REQUIRED = ["exposure_class", "pd", "drawn"]


def normalise_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")
    for col, default in DEFAULTS.items():
        if col not in df.columns:
            df[col] = default
        elif default is not None and not isinstance(default, str):
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if not (isinstance(default, float) and math.isnan(default)):
                df[col] = df[col].fillna(default)
        elif isinstance(default, str):
            df[col] = df[col].fillna(default).astype(str).str.strip()
    if df["id"].isna().all():
        df["id"] = [f"EXP{i+1:04d}" for i in range(len(df))]
    df["exposure_class"] = df["exposure_class"].str.upper()
    df["approach"] = df["approach"].str.upper().str.replace("-", "")
    df["collateral_type"] = df["collateral_type"].str.lower()
    df["seniority"] = df["seniority"].str.lower()
    bad = sorted(set(df["exposure_class"]) - set(P.EXPOSURE_CLASSES))
    if bad:
        raise ValueError(f"Unknown exposure_class value(s): {bad}")
    bad = sorted(set(df["collateral_type"]) - set(P.COLLATERAL_TYPES))
    if bad:
        raise ValueError(f"Unknown collateral_type value(s): {bad}")
    return df


# --------------------------------------------------------------------------- #
# IRB building blocks
# --------------------------------------------------------------------------- #
def _weight(pd_: float, k: float) -> float:
    return (1 - math.exp(-k * pd_)) / (1 - math.exp(-k))


def correlation(exposure_class: str, pd_: float, turnover_m: float = np.nan) -> float:
    """Asset correlation R (Art. 153(2)-(4) and Art. 154(1)-(4))."""
    if exposure_class in P.CORPORATE_CLASSES:
        w = _weight(pd_, 50)
        r = 0.12 * w + 0.24 * (1 - w)
        if exposure_class == "FSE_LARGE":
            r *= 1.25
        elif exposure_class == "CORP" and not np.isnan(turnover_m) and turnover_m <= 50:
            s = min(max(turnover_m, 5.0), 50.0)
            r -= 0.04 * (1 - (s - 5) / 45)
        return r
    if exposure_class == "RET_RRE":
        return 0.15
    if exposure_class in ("RET_QRRE_REV", "RET_QRRE_TRANS"):
        return 0.04
    w = _weight(pd_, 35)
    return 0.03 * w + 0.16 * (1 - w)


def maturity_adjustment(pd_: float, m: float) -> float:
    b = (0.11852 - 0.05478 * math.log(pd_)) ** 2
    return (1 + (m - 2.5) * b) / (1 - 1.5 * b)


def capital_k(pd_: float, lgd: float, r: float, ma: float = 1.0) -> float:
    """Unexpected-loss capital requirement K per unit of EAD (non-defaulted)."""
    cond = norm.cdf((norm.ppf(pd_) + math.sqrt(r) * Q999) / math.sqrt(1 - r))
    return max(0.0, (lgd * cond - pd_ * lgd) * ma)


def sme_supporting_factor(amount: float) -> float:
    if amount <= 0:
        return 1.0
    low = min(amount, P.SME_SF_THRESHOLD)
    return (low * P.SME_SF_LOW + max(amount - P.SME_SF_THRESHOLD, 0) * P.SME_SF_HIGH) / amount


def _secured_split(ead: float, ctype: str, cvalue: float, haircut: Dict[str, float]):
    """Return (E_secured, E_unsecured) after collateral haircut."""
    if ctype == "none" or cvalue <= 0 or ead <= 0:
        return 0.0, ead
    es = min(cvalue * (1 - haircut.get(ctype, 0.0)), ead)
    return es, ead - es


# --------------------------------------------------------------------------- #
# Single-exposure calculation
# --------------------------------------------------------------------------- #
def compute_exposure(x: dict, regime: P.Regime, force_firb_m25: bool = False,
                     apply_sme_sf: bool = True, sa_ig_transitional: bool = True,
                     sa_rre_transitional: bool = False) -> dict:
    cls = x["exposure_class"]
    is_corp = cls in P.CORPORATE_CLASSES
    flags: List[str] = []
    approach = x["approach"] if is_corp else "AIRB"
    if not is_corp and x["approach"] == "FIRB":
        flags.append("Retail: own PD/LGD/CCF estimates required - A-IRB applied")
    if regime.name == "CRR3" and is_corp and approach == "AIRB":
        if cls in ("FSE", "FSE_LARGE"):
            approach = "FIRB"
            flags.append("Art. 147a: financial sector entity - F-IRB applied")
        elif not np.isnan(x["turnover_m"]) and x["turnover_m"] > 500:
            approach = "FIRB"
            flags.append("Art. 147a: large corporate (turnover > EUR 500m) - F-IRB applied")

    defaulted = bool(x["defaulted"]) or x["pd"] >= 1.0
    drawn, undrawn = float(x["drawn"]), float(x["undrawn"])
    ccf_sa = float(x["ccf_sa"])

    # ---- EAD ------------------------------------------------------------- #
    if approach == "FIRB":
        ccf_irb = ccf_sa                                     # Art. 166(8)
    else:
        ccf_irb = ccf_sa if np.isnan(x["ccf_irb"]) else float(x["ccf_irb"])
        floor = regime.ccf_floor_share_of_sa * ccf_sa
        if regime.apply_input_floors and ccf_irb < floor:
            flags.append(f"CCF floored at {floor:.0%} (50 % of SA CCF)")
            ccf_irb = floor
    ead = drawn + ccf_irb * undrawn

    # ---- PD -------------------------------------------------------------- #
    if is_corp:
        pd_floor = regime.pd_floor_corporate
    elif cls == "RET_QRRE_REV":
        pd_floor = regime.pd_floor_qrre_revolver
    else:
        pd_floor = regime.pd_floor_retail
    pd_used = 1.0 if defaulted else max(float(x["pd"]), pd_floor)
    if not defaulted and x["pd"] < pd_floor:
        flags.append(f"PD floored at {pd_floor:.2%}")

    # ---- LGD ------------------------------------------------------------- #
    ctype, cvalue = x["collateral_type"], float(x["collateral_value"])
    if approach == "FIRB":
        if x["seniority"] == "subordinated":
            lgdu = regime.firb_lgd_subordinated
        elif cls in ("FSE", "FSE_LARGE"):
            lgdu = regime.firb_lgd_senior_fse
        else:
            lgdu = regime.firb_lgd_senior_corp
        es, eu = _secured_split(ead, ctype, cvalue, regime.firb_haircut)
        lgds = regime.firb_lgds.get(ctype, lgdu)
        lgd_used = (eu * lgdu + es * lgds) / ead if ead > 0 else lgdu
    else:
        lgd_used = float(x["lgd"])
        if regime.apply_input_floors:
            if cls == "RET_RRE":
                lfloor = regime.lgd_floor_rre
            elif cls in ("RET_QRRE_REV", "RET_QRRE_TRANS"):
                lfloor = regime.lgd_floor_qrre
            else:
                lgdu_f = (regime.lgd_floor_corp_unsecured if is_corp
                          else regime.lgd_floor_retail_other_unsecured)
                es, eu = _secured_split(ead, ctype, cvalue, regime.firb_haircut)
                lgds_f = regime.lgd_floor_secured.get(ctype, lgdu_f)
                lfloor = (eu * lgdu_f + es * lgds_f) / ead if ead > 0 else lgdu_f
            if not defaulted and lgd_used < lfloor:
                flags.append(f"LGD floored at {lfloor:.2%}")
                lgd_used = lfloor

    # ---- Maturity -------------------------------------------------------- #
    m = np.nan
    if is_corp:
        m = 2.5 if (approach == "FIRB" and force_firb_m25) else min(max(float(x["maturity"]), 1.0), 5.0)

    # ---- K, RWA, EL ------------------------------------------------------ #
    if defaulted:
        r, ma = np.nan, np.nan
        if approach == "FIRB":
            k = 0.0
            el_rate = lgd_used
        else:
            elbe = lgd_used if np.isnan(x["elbe"]) else float(x["elbe"])
            k = max(0.0, lgd_used - elbe)
            el_rate = elbe
    else:
        r = correlation(cls, pd_used, x["turnover_m"])
        ma = maturity_adjustment(pd_used, m) if is_corp else 1.0
        k = capital_k(pd_used, lgd_used, r, ma)
        el_rate = pd_used * lgd_used

    sme_eligible = (apply_sme_sf and bool(x["sme_sf"]) and not defaulted
                    and not np.isnan(x["turnover_m"]) and x["turnover_m"] <= P.SME_SF_MAX_TURNOVER_M)
    sf = sme_supporting_factor(ead) if sme_eligible else 1.0

    rw_irb = 12.5 * k * regime.scaling_factor
    rwa_irb = rw_irb * ead * sf
    el = el_rate * ead

    # ---- Standardised approach ------------------------------------------ #
    sa = compute_sa(x, cls, defaulted, drawn, undrawn, ccf_sa,
                    sa_ig_transitional=sa_ig_transitional,
                    sa_rre_transitional=sa_rre_transitional)
    sf_sa = sme_supporting_factor(sa["ead_sa"]) if sme_eligible else 1.0
    rwa_sa = sa["rwa_sa_pre_sf"] * sf_sa

    return {
        "approach_applied": approach,
        "defaulted_flag": int(defaulted),
        "ccf_irb_used": ccf_irb,
        "ead_irb": ead,
        "pd_used": pd_used,
        "lgd_used": lgd_used,
        "maturity_used": m,
        "correlation_R": r,
        "maturity_adj": ma,
        "K": k,
        "rw_irb": rw_irb,
        "sme_factor": sf,
        "rwa_irb": rwa_irb,
        "el": el,
        "ead_sa": sa["ead_sa"],
        "rw_sa": rwa_sa / sa["ead_sa"] if sa["ead_sa"] > 0 else 0.0,
        "rwa_sa": rwa_sa,
        "sa_treatment": sa["treatment"],
        "flags": "; ".join(flags),
    }


def _ipre_rw(ltv: float, table) -> float:
    for bound, rw in table:
        if ltv <= bound:
            return rw
    return table[-1][1]


def _counterparty_rw_corp(x: dict, sa_ig_transitional: bool) -> (float, str):
    cqs = int(x["sa_cqs"]) if not np.isnan(x["sa_cqs"]) else 0
    if cqs in P.SA_CORP_CQS:
        return P.SA_CORP_CQS[cqs], f"Corporate CQS {cqs}"
    if sa_ig_transitional and bool(x["sa_ig"]):
        return P.SA_CORP_IG_TRANSITIONAL, "Unrated IG corporate (Art. 465(3))"
    return P.SA_CORP_UNRATED, "Unrated corporate"


def compute_sa(x: dict, cls: str, defaulted: bool, drawn: float, undrawn: float, ccf_sa: float,
               sa_ig_transitional: bool = True, sa_rre_transitional: bool = False) -> dict:
    prov = float(x["provisions"])
    gross = drawn + ccf_sa * undrawn
    ead_sa = max(drawn - prov, 0.0) + ccf_sa * undrawn          # Art. 111: net of SCRA
    ctype, cvalue = x["collateral_type"], float(x["collateral_value"])
    pv = float(x["property_value"])
    ipre = bool(x["ipre"])

    # Financial collateral - comprehensive method with haircut-adjusted value
    exposure = ead_sa
    note = ""
    if ctype == "financial" and cvalue > 0:
        exposure = max(ead_sa - cvalue, 0.0)
        note = " + financial collateral"

    if defaulted:
        if cls == "RET_RRE" and not ipre:
            return {"ead_sa": ead_sa, "rwa_sa_pre_sf": exposure * 1.0,
                    "treatment": "Defaulted RRE (100 %)"}
        rw = (P.SA_DEFAULT_HIGH_PROV if gross > 0 and prov / gross >= P.SA_DEFAULT_PROV_THRESHOLD
              else P.SA_DEFAULT_LOW_PROV)
        return {"ead_sa": ead_sa, "rwa_sa_pre_sf": exposure * rw,
                "treatment": f"Defaulted ({rw:.0%})" + note}

    # Counterparty risk weight
    if cls in P.CORPORATE_CLASSES:
        cp_rw, label = _counterparty_rw_corp(x, sa_ig_transitional)
    elif cls == "RET_QRRE_TRANS":
        cp_rw, label = P.SA_RETAIL_TRANSACTOR, "QRRE transactor (45 %)"
    elif ead_sa > P.SA_RETAIL_MAX_AMOUNT:
        cp_rw, label = P.SA_RETAIL_NON_REGULATORY, "Retail > EUR 1m (100 %)"
    else:
        cp_rw, label = P.SA_RETAIL_REGULATORY, "Regulatory retail (75 %)"

    # Real estate treatment
    is_rre = cls == "RET_RRE" or (ctype == "rre" and pv > 0)
    is_cre = ctype == "cre" and pv > 0 and cls != "RET_RRE"
    if is_rre and pv > 0:
        ltv = exposure / pv
        if ipre:
            rw = _ipre_rw(ltv, P.SA_RRE_IPRE_TABLE)
            return {"ead_sa": ead_sa, "rwa_sa_pre_sf": exposure * rw,
                    "treatment": f"RRE IPRE whole loan, LTV {ltv:.0%} ({rw:.0%})"}
        if sa_rre_transitional:
            p1 = min(exposure, 0.55 * pv)
            p2 = min(max(exposure - p1, 0.0), 0.25 * pv)
            p3 = exposure - p1 - p2
            rwa = (p1 * P.SA_RRE_TRANSITIONAL_LOW + p2 * min(P.SA_RRE_TRANSITIONAL_MID, cp_rw)
                   + p3 * cp_rw)
            return {"ead_sa": ead_sa, "rwa_sa_pre_sf": rwa,
                    "treatment": f"RRE loan-splitting, Art. 465(5) transitional, LTV {ltv:.0%}"}
        sec = min(exposure, P.SA_RRE_SECURED_SHARE * pv)
        rwa = sec * P.SA_RRE_SECURED_RW + (exposure - sec) * cp_rw
        return {"ead_sa": ead_sa, "rwa_sa_pre_sf": rwa,
                "treatment": f"RRE loan-splitting, LTV {ltv:.0%}"}
    if is_cre:
        ltv = exposure / pv
        if ipre:
            rw = _ipre_rw(ltv, P.SA_CRE_IPRE_TABLE)
            return {"ead_sa": ead_sa, "rwa_sa_pre_sf": exposure * rw,
                    "treatment": f"CRE IPRE whole loan, LTV {ltv:.0%} ({rw:.0%})"}
        sec = min(exposure, P.SA_CRE_SECURED_SHARE * pv)
        rwa = sec * min(P.SA_CRE_SECURED_RW, cp_rw) + (exposure - sec) * cp_rw
        return {"ead_sa": ead_sa, "rwa_sa_pre_sf": rwa,
                "treatment": f"CRE loan-splitting, LTV {ltv:.0%}"}
    if cls == "RET_RRE":
        label = "RRE without property value - counterparty RW"
    return {"ead_sa": ead_sa, "rwa_sa_pre_sf": exposure * cp_rw, "treatment": label + note}


# --------------------------------------------------------------------------- #
# Portfolio, output floor and own funds
# --------------------------------------------------------------------------- #
def compute_portfolio(df: pd.DataFrame, regime_name: str = "CRR3", **kwargs) -> pd.DataFrame:
    regime = P.REGIMES[regime_name]
    df = normalise_portfolio(df)
    rows = [compute_exposure(r, regime, **kwargs) for r in df.to_dict("records")]
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


@dataclass
class FloorResult:
    year: int
    factor: float
    u_trea: float
    s_trea: float
    floored: float
    trea: float
    floor_binding: bool
    cap_applied: bool


def output_floor(irb_credit_rwa: float, sa_credit_rwa: float, year: int,
                 other_modelled_rwa: float = 0.0, other_standardised_rwa: float = 0.0,
                 transitional_cap: bool = False) -> FloorResult:
    """TREA = max(U-TREA ; x * S-TREA) - Art. 92(3), Art. 465(1)-(2)."""
    x = P.output_floor_factor(year)
    u = irb_credit_rwa + other_modelled_rwa
    s = sa_credit_rwa + other_standardised_rwa
    floored = x * s
    trea = max(u, floored)
    cap = False
    if transitional_cap and year <= 2029 and trea > 1.25 * u:
        trea, cap = 1.25 * u, True
    return FloorResult(year, x, u, s, floored, trea, floored > u, cap)


def provisions_vs_el(res: pd.DataFrame, irb_credit_rwa: float, cap_rate: float) -> Dict[str, float]:
    """IRB EL vs credit risk adjustments (Art. 159, 36(1)(d), 62(d))."""
    d = res["defaulted_flag"] == 1
    diff_nd = res.loc[~d, "provisions"].sum() - res.loc[~d, "el"].sum()
    diff_d = res.loc[d, "provisions"].sum() - res.loc[d, "el"].sum()
    if diff_nd < 0:  # excess on defaulted cannot cover a non-defaulted shortfall
        shortfall, excess = -diff_nd + max(-diff_d, 0.0), 0.0
    else:
        net = diff_nd + diff_d
        shortfall, excess = max(-net, 0.0), max(net, 0.0)
    t2_addback = min(excess, cap_rate * irb_credit_rwa)
    return {"el_non_defaulted": res.loc[~d, "el"].sum(), "el_defaulted": res.loc[d, "el"].sum(),
            "prov_non_defaulted": res.loc[~d, "provisions"].sum(),
            "prov_defaulted": res.loc[d, "provisions"].sum(),
            "shortfall_cet1_deduction": shortfall, "excess": excess, "t2_addback": t2_addback}


def own_funds(trea: float, settings: P.CapitalSettings, cet1: Optional[float] = None,
              at1: float = 0.0, t2: float = 0.0, shortfall: float = 0.0,
              t2_addback: float = 0.0) -> pd.DataFrame:
    req = settings.requirements()
    rows = []
    avail = None
    if cet1 is not None:
        c = cet1 - shortfall
        avail = {"CET1": c, "Tier 1": c + at1, "Total capital": c + at1 + t2 + t2_addback}
    for tier, rate in req.items():
        row = {"Tier": tier, "Requirement (% TREA)": rate, "Requirement (EUR)": rate * trea}
        if avail is not None:
            row["Available (EUR)"] = avail[tier]
            row["Ratio"] = avail[tier] / trea if trea > 0 else np.nan
            row["Surplus / (deficit) (EUR)"] = avail[tier] - rate * trea
        rows.append(row)
    return pd.DataFrame(rows)
