"""IRB & SA Credit-Risk Capital Calculator (CRR3) - Streamlit app.

Author: Laurent Motais de Narbonne
Run locally:  streamlit run app.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from capital_engine import (capital_k, compute_portfolio, correlation, maturity_adjustment,
                            output_floor, own_funds, provisions_vs_el)
from capital_engine import parameters as P

st.set_page_config(page_title="IRB Capital Calculator (CRR3)", layout="wide")

IRB_COLOR, SA_COLOR, FLOOR_COLOR = "#2a78d6", "#eb6834", "#52514e"
CLASS_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
SAMPLE = Path(__file__).parent / "data" / "sample_portfolio.csv"
CHART_LAYOUT = dict(template="plotly_white", margin=dict(l=10, r=10, t=40, b=10),
                    hovermode="x unified", legend=dict(orientation="h", y=-0.2))


def eur(x: float) -> str:
    if abs(x) >= 1e9:
        return f"€{x / 1e9:,.2f}bn"
    if abs(x) >= 1e6:
        return f"€{x / 1e6:,.2f}m"
    return f"€{x:,.0f}"


# --------------------------------------------------------------------------- #
# Sidebar - regulatory settings
# --------------------------------------------------------------------------- #
st.sidebar.title("Settings")
regime = st.sidebar.selectbox(
    "Regulatory regime", ["CRR3", "LEGACY"],
    help="CRR3 = Regulation (EU) 2024/1623. LEGACY = pre-CRR3 IRB calibration "
         "(1.06 scaling, 0.03 % PD floor, no LGD/CCF input floors) for reconciliation only.")
year = st.sidebar.selectbox("Reporting year (output-floor phase-in)",
                            [2025, 2026, 2027, 2028, 2029, 2030], index=1)
st.sidebar.caption(f"Output floor factor: **{P.output_floor_factor(year):.1%}**")

with st.sidebar.expander("Calculation options", expanded=False):
    transitional_cap = st.checkbox("Art. 465(2) cap: TREA <= 125 % of U-TREA (to 2029)", False)
    sa_ig = st.checkbox("Art. 465(3): 65 % RW for unrated IG corporates (to 2032)", True)
    sa_rre_trans = st.checkbox("Art. 465(5): transitional RRE treatment in SA", False)
    force_m25 = st.checkbox("F-IRB: supervisory maturity M = 2.5 years", False)
    sme_sf = st.checkbox("Apply SME supporting factor (Art. 501)", True)

with st.sidebar.expander("Capital requirements & buffers", expanded=False):
    p2r = st.number_input("Pillar 2 requirement (P2R, %)", 0.0, 10.0, 2.0, 0.25) / 100
    ccyb = st.number_input("Countercyclical buffer (%)", 0.0, 3.0, 1.0, 0.25,
                           help="France: 1 % (HCSF, maintained in June 2026). "
                                "Use the exposure-weighted rate for your portfolio.") / 100
    syst = st.number_input("Systemic buffers (O-SII / G-SII / SyRB, %)", 0.0, 5.0, 0.0, 0.25) / 100
settings = P.CapitalSettings(p2r=p2r, countercyclical_buffer=ccyb, systemic_buffer=syst)

opts = dict(force_firb_m25=force_m25, apply_sme_sf=sme_sf,
            sa_ig_transitional=sa_ig, sa_rre_transitional=sa_rre_trans)

st.title("IRB & Standardised Credit-Risk Capital Calculator")
st.caption("PD, LGD, EAD -> K, RWA, expected loss, SA-CR, output floor and own funds requirements "
           "under CRR3. Educational tool - not a regulatory reporting system.")

tab_single, tab_port, tab_cap, tab_sens, tab_method = st.tabs(
    ["Single exposure", "Portfolio", "Output floor & capital", "Sensitivity", "Methodology"])

# --------------------------------------------------------------------------- #
# 1. Single exposure
# --------------------------------------------------------------------------- #
with tab_single:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Obligor & approach")
        cls = st.selectbox("Exposure class", list(P.EXPOSURE_CLASSES),
                           format_func=lambda k: f"{k} - {P.EXPOSURE_CLASSES[k]}")
        is_corp = cls in P.CORPORATE_CLASSES
        approach = st.radio("Approach", ["FIRB", "AIRB"], horizontal=True, index=1,
                            disabled=not is_corp)
        pd_in = st.number_input("PD (%)", 0.0, 100.0, 1.0, 0.05, format="%.3f") / 100
        lgd_in = st.number_input("LGD - own estimate (%)", 0.0, 100.0, 45.0, 1.0,
                                 disabled=is_corp and approach == "FIRB") / 100
        seniority = st.selectbox("Seniority (F-IRB)", ["senior", "subordinated"])
        maturity = st.slider("Effective maturity M (years)", 1.0, 5.0, 2.5, 0.25,
                             disabled=not is_corp)
        turnover = st.number_input("Annual turnover (EUR m, 0 = n/a)", 0.0, 100000.0, 0.0, 1.0)
    with c2:
        st.subheader("Exposure")
        drawn = st.number_input("Drawn amount (EUR)", 0.0, 1e12, 1_000_000.0, 10_000.0)
        undrawn = st.number_input("Undrawn commitment (EUR)", 0.0, 1e12, 0.0, 10_000.0)
        ccf_sa = st.selectbox("SA CCF bucket", [1.0, 0.5, 0.4, 0.2, 0.1], index=2,
                              format_func=lambda v: f"{v:.0%}")
        ccf_irb = st.number_input("Own-estimate CCF (%) - A-IRB", 0.0, 100.0, ccf_sa * 100, 5.0) / 100
        provisions = st.number_input("Specific provisions (EUR)", 0.0, 1e12, 0.0, 1_000.0)
        defaulted = st.checkbox("Defaulted exposure")
        elbe = st.number_input("ELBE (%) - defaulted, A-IRB", 0.0, 100.0, 40.0, 1.0,
                               disabled=not defaulted) / 100
    with c3:
        st.subheader("Collateral & SA data")
        ctype = st.selectbox("Collateral type", P.COLLATERAL_TYPES)
        cvalue = st.number_input("Collateral value (EUR; financial = haircut-adjusted)",
                                 0.0, 1e12, 0.0, 10_000.0)
        pv = st.number_input("Property value (EUR) - SA real estate", 0.0, 1e12, 0.0, 10_000.0)
        ipre = st.checkbox("Income-producing real estate (IPRE)")
        cqs = st.selectbox("External rating - credit quality step", [0, 1, 2, 3, 4, 5, 6],
                           format_func=lambda v: "Unrated" if v == 0 else f"CQS {v}")
        ig = st.checkbox("Internally assessed investment grade (Art. 465(3))")
        sf_flag = st.checkbox("SME supporting factor eligible")

    row = pd.DataFrame([{
        "id": "SINGLE", "exposure_class": cls, "approach": approach, "pd": pd_in, "lgd": lgd_in,
        "seniority": seniority, "collateral_type": ctype, "collateral_value": cvalue,
        "property_value": pv, "ipre": int(ipre), "maturity": maturity,
        "turnover_m": turnover if turnover > 0 else np.nan, "drawn": drawn, "undrawn": undrawn,
        "ccf_irb": ccf_irb, "ccf_sa": ccf_sa, "defaulted": int(defaulted),
        "elbe": elbe if defaulted else np.nan, "provisions": provisions,
        "sa_cqs": cqs, "sa_ig": int(ig), "sme_sf": int(sf_flag)}])
    try:
        r = compute_portfolio(row, regime, **opts).iloc[0]
        st.divider()
        m = st.columns(5)
        m[0].metric("EAD (IRB)", eur(r.ead_irb))
        m[1].metric("Capital K", f"{r.K:.4%}")
        m[2].metric("Risk weight (IRB)", f"{r.rw_irb * r.sme_factor:.2%}")
        m[3].metric("RWA (IRB)", eur(r.rwa_irb))
        m[4].metric("Expected loss", eur(r.el))
        m = st.columns(5)
        m[0].metric("EAD (SA)", eur(r.ead_sa))
        m[1].metric("Risk weight (SA)", f"{r.rw_sa:.2%}")
        m[2].metric("RWA (SA)", eur(r.rwa_sa))
        m[3].metric(f"Floored SA RWA ({P.output_floor_factor(year):.1%})",
                    eur(P.output_floor_factor(year) * r.rwa_sa))
        m[4].metric("Own funds at 8 % (IRB)", eur(0.08 * r.rwa_irb))
        detail = {
            "Approach applied": r.approach_applied, "PD used": f"{r.pd_used:.4%}",
            "LGD used": f"{r.lgd_used:.2%}", "CCF used (IRB)": f"{r.ccf_irb_used:.0%}",
            "Correlation R": "-" if pd.isna(r.correlation_R) else f"{r.correlation_R:.4%}",
            "Maturity M": "-" if pd.isna(r.maturity_used) else f"{r.maturity_used:.2f}",
            "Maturity adjustment": "-" if pd.isna(r.maturity_adj) else f"{r.maturity_adj:.4f}",
            "SME supporting factor": f"{r.sme_factor:.4f}",
            "SA treatment": r.sa_treatment, "Flags": r["flags"] or "-"}
        st.dataframe(pd.DataFrame(detail.items(), columns=["Item", "Value"]),
                     hide_index=True, width="stretch")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Calculation error: {exc}")

# --------------------------------------------------------------------------- #
# 2. Portfolio
# --------------------------------------------------------------------------- #
with tab_port:
    st.markdown("Upload a CSV portfolio (one row per exposure) or use the sample portfolio. "
                "Only `exposure_class`, `pd` and `drawn` are mandatory; other columns take "
                "defaults (see *Methodology*).")
    cc = st.columns([2, 1])
    upload = cc[0].file_uploader("Portfolio CSV", type="csv")
    cc[1].download_button("Download template / sample", SAMPLE.read_bytes(),
                          "sample_portfolio.csv", "text/csv")
    raw = pd.read_csv(upload) if upload else pd.read_csv(SAMPLE)
    if not upload:
        st.info("Showing the sample portfolio (15 exposures).")
    try:
        res = compute_portfolio(raw, regime, **opts)
        st.session_state["res"] = res
    except Exception as exc:  # noqa: BLE001
        st.error(f"Input error: {exc}")
        res = None

    if res is not None:
        tot = st.columns(5)
        tot[0].metric("EAD (IRB)", eur(res.ead_irb.sum()))
        tot[1].metric("RWA (IRB)", eur(res.rwa_irb.sum()))
        tot[2].metric("Avg RW (IRB)", f"{res.rwa_irb.sum() / res.ead_irb.sum():.1%}")
        tot[3].metric("RWA (SA)", eur(res.rwa_sa.sum()))
        tot[4].metric("Expected loss", eur(res.el.sum()))

        by = res.groupby("exposure_class")[["ead_irb", "rwa_irb", "el", "ead_sa", "rwa_sa"]].sum()
        by["rw_irb"] = by.rwa_irb / by.ead_irb
        by["rw_sa"] = by.rwa_sa / by.ead_sa
        fig = go.Figure()
        fig.add_bar(x=by.index, y=by.rw_irb * 100, name="IRB", marker_color=IRB_COLOR,
                    customdata=by.rwa_irb, text=[f"{v:.0%}" for v in by.rw_irb],
                    textposition="outside",
                    hovertemplate="%{x}<br>IRB RW: %{y:.1f}%<br>RWA: %{customdata:,.0f}<extra></extra>")
        fig.add_bar(x=by.index, y=by.rw_sa * 100, name="SA", marker_color=SA_COLOR,
                    customdata=by.rwa_sa, text=[f"{v:.0%}" for v in by.rw_sa],
                    textposition="outside",
                    hovertemplate="%{x}<br>SA RW: %{y:.1f}%<br>RWA: %{customdata:,.0f}<extra></extra>")
        fig.update_layout(title="Average risk weight by exposure class: IRB vs SA", barmode="group",
                          bargap=0.3, bargroupgap=0.05, yaxis_title="Risk weight (%)",
                          **{**CHART_LAYOUT, "hovermode": "closest"})
        st.plotly_chart(fig, width="stretch")
        st.dataframe(by.style.format({"ead_irb": "{:,.0f}", "rwa_irb": "{:,.0f}", "el": "{:,.0f}",
                                      "ead_sa": "{:,.0f}", "rwa_sa": "{:,.0f}",
                                      "rw_irb": "{:.1%}", "rw_sa": "{:.1%}"}),
                     width="stretch")
        show = ["id", "exposure_class", "approach_applied", "ead_irb", "pd_used", "lgd_used",
                "maturity_used", "correlation_R", "K", "rw_irb", "sme_factor", "rwa_irb", "el",
                "ead_sa", "rw_sa", "rwa_sa", "sa_treatment", "flags"]
        st.subheader("Exposure-level results")
        st.dataframe(res[show], hide_index=True, width="stretch")
        st.download_button("Download results (CSV)", res.to_csv(index=False).encode(),
                           "capital_results.csv", "text/csv")

# --------------------------------------------------------------------------- #
# 3. Output floor & capital
# --------------------------------------------------------------------------- #
with tab_cap:
    res = st.session_state.get("res")
    if res is None:
        st.warning("Load a portfolio in the *Portfolio* tab first.")
    else:
        st.markdown("Credit risk comes from the portfolio. Add the other risk types to apply the "
                    "output floor at total-RWA level (Art. 92(3) CRR).")
        oc = st.columns(2)
        other_u = oc[0].number_input("Other RWA - as reported with models (market, op., CVA)",
                                     0.0, 1e13, 0.0, 1e6)
        other_s = oc[1].number_input("Other RWA - fully standardised", 0.0, 1e13, 0.0, 1e6)
        irb_rwa, sa_rwa = res.rwa_irb.sum(), res.rwa_sa.sum()
        fl = output_floor(irb_rwa, sa_rwa, year, other_u, other_s, transitional_cap)

        st.subheader(f"Output floor - {year}")
        k = st.columns(4)
        k[0].metric("U-TREA (modelled)", eur(fl.u_trea))
        k[1].metric("S-TREA (standardised)", eur(fl.s_trea))
        k[2].metric(f"{fl.factor:.1%} x S-TREA", eur(fl.floored))
        k[3].metric("TREA", eur(fl.trea),
                    delta=(f"{fl.trea / fl.u_trea - 1:+.1%} vs U-TREA"
                           if fl.u_trea and fl.trea > fl.u_trea else None),
                    delta_color="inverse")
        st.caption(("Floor is **binding**." if fl.floor_binding else "Floor is not binding.")
                   + (" Art. 465(2) cap applied." if fl.cap_applied else ""))

        years = [2025, 2026, 2027, 2028, 2029, 2030]
        path = [output_floor(irb_rwa, sa_rwa, y, other_u, other_s, transitional_cap) for y in years]
        fig = go.Figure()
        fig.add_scatter(x=years, y=[p.trea for p in path], name="TREA retained",
                        line=dict(color=FLOOR_COLOR, width=8), opacity=0.25, mode="lines")
        fig.add_scatter(x=years, y=[p.u_trea for p in path], name="U-TREA (models)",
                        line=dict(color=IRB_COLOR, width=2), mode="lines+markers")
        fig.add_scatter(x=years, y=[p.floored for p in path], name="Floored S-TREA",
                        line=dict(color=SA_COLOR, width=2), mode="lines+markers")
        fig.update_layout(title="Output-floor phase-in (Art. 465(1))", yaxis_title="EUR",
                          xaxis=dict(tickmode="array", tickvals=years,
                                     ticktext=[str(y) if y < 2030 else "2030+" for y in years]),
                          **CHART_LAYOUT)
        st.plotly_chart(fig, width="stretch")

        st.subheader("Expected loss vs provisions (IRB)")
        pe = provisions_vs_el(res, irb_rwa, settings.excess_provision_t2_cap)
        e = st.columns(4)
        e[0].metric("EL - non-defaulted", eur(pe["el_non_defaulted"]))
        e[1].metric("EL - defaulted", eur(pe["el_defaulted"]))
        e[2].metric("Shortfall -> CET1 deduction", eur(pe["shortfall_cet1_deduction"]))
        e[3].metric("Excess -> T2 (cap 0.6 % IRB RWA)", eur(pe["t2_addback"]))

        st.subheader("Own funds requirements")
        ac = st.columns(3)
        cet1 = ac[0].number_input("Available CET1 (before IRB shortfall), EUR", 0.0, 1e13, 0.0, 1e5)
        at1 = ac[1].number_input("Available AT1, EUR", 0.0, 1e13, 0.0, 1e5)
        t2 = ac[2].number_input("Available T2 (before excess provisions), EUR", 0.0, 1e13, 0.0, 1e5)
        of = own_funds(fl.trea, settings, cet1 if cet1 > 0 else None, at1, t2,
                       pe["shortfall_cet1_deduction"], pe["t2_addback"])
        fmt = {"Requirement (% TREA)": "{:.2%}", "Requirement (EUR)": "{:,.0f}",
               "Available (EUR)": "{:,.0f}", "Ratio": "{:.2%}", "Surplus / (deficit) (EUR)": "{:,.0f}"}
        st.dataframe(of.style.format({k: v for k, v in fmt.items() if k in of.columns}),
                     hide_index=True, width="stretch")
        st.caption(f"Combined buffer requirement: {settings.combined_buffer:.2%} "
                   f"(CCB 2.5 % + CCyB {ccyb:.2%} + systemic {syst:.2%}). P2R split "
                   "56.25 % CET1 / 75 % T1 (Art. 104a CRD).")

# --------------------------------------------------------------------------- #
# 4. Sensitivity
# --------------------------------------------------------------------------- #
with tab_sens:
    s = st.columns(3)
    lgd_s = s[0].slider("LGD", 0.05, 1.0, 0.45, 0.05)
    m_s = s[1].slider("Maturity (corporates)", 1.0, 5.0, 2.5, 0.5)
    to_s = s[2].slider("SME turnover (EUR m)", 5.0, 50.0, 5.0, 5.0)
    grid = np.unique(np.concatenate([np.linspace(0.0005, 0.02, 60), np.linspace(0.02, 0.30, 60)]))
    sc = P.REGIMES[regime].scaling_factor
    curves = {
        "Corporate": lambda p: capital_k(p, lgd_s, correlation("CORP", p), maturity_adjustment(p, m_s)),
        f"SME corporate (S = {to_s:.0f}m)": lambda p: capital_k(
            p, lgd_s, correlation("CORP", p, to_s), maturity_adjustment(p, m_s)),
        "Large / unregulated FSE": lambda p: capital_k(
            p, lgd_s, correlation("FSE_LARGE", p), maturity_adjustment(p, m_s)),
        "Retail - residential mortgage": lambda p: capital_k(p, lgd_s, 0.15),
        "Retail - QRRE": lambda p: capital_k(p, lgd_s, 0.04),
        "Retail - other": lambda p: capital_k(p, lgd_s, correlation("RET_OTHER", p)),
    }
    fig = go.Figure()
    for (name, f), col in zip(curves.items(), CLASS_COLORS):
        fig.add_scatter(x=grid * 100, y=[12.5 * sc * f(p) * 100 for p in grid], name=name,
                        line=dict(color=col, width=2), mode="lines",
                        hovertemplate="%{y:.1f}%<extra>" + name + "</extra>")
    fig.update_layout(title=f"IRB risk weight vs PD (LGD {lgd_s:.0%})",
                      xaxis_title="PD (%)", yaxis_title="Risk weight (%)", **CHART_LAYOUT)
    st.plotly_chart(fig, width="stretch")
    st.caption("Risk weight before SME supporting factor and input floors. The curves flatten at "
               "high PD because K covers unexpected loss only: as PD rises, a growing share of "
               "the loss is expected (EL) and must be covered by provisions.")

# --------------------------------------------------------------------------- #
# 5. Methodology
# --------------------------------------------------------------------------- #
with tab_method:
    st.markdown((Path(__file__).parent / "METHODOLOGY.md").read_text(encoding="utf-8"))
