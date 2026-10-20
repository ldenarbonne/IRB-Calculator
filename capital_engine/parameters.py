"""Regulatory parameters for the credit-risk capital engine.

Two regimes are provided:

* ``CRR3`` – Regulation (EU) No 575/2013 as amended by Regulation (EU) 2024/1623
  (Basel III final / "Basel IV"), applicable since 1 January 2025.
* ``LEGACY`` – pre-CRR3 IRB calibration (1.06 scaling factor, 0.03 % PD floor,
  no LGD/CCF input floors). Kept only to reconcile with older tools such as the
  author's 2021 Excel IRB calculator.

All rates are decimals (0.40 = 40 %). Amounts are in EUR; turnover in EUR million.
"""

from dataclasses import dataclass, field
from typing import Dict

# --------------------------------------------------------------------------- #
# Exposure classes accepted by the engine
# --------------------------------------------------------------------------- #
EXPOSURE_CLASSES: Dict[str, str] = {
    "CORP": "Corporate (incl. SME corporate via turnover; large corporate > EUR 500m)",
    "FSE": "Financial sector entity (non-large, regulated)",
    "FSE_LARGE": "Large (total assets >= EUR 70bn) or unregulated financial sector entity",
    "RET_RRE": "Retail secured by residential real estate",
    "RET_QRRE_REV": "Qualifying revolving retail - revolver",
    "RET_QRRE_TRANS": "Qualifying revolving retail - transactor",
    "RET_OTHER": "Other retail (incl. retail SME)",
}
CORPORATE_CLASSES = {"CORP", "FSE", "FSE_LARGE"}
RETAIL_CLASSES = {"RET_RRE", "RET_QRRE_REV", "RET_QRRE_TRANS", "RET_OTHER"}

COLLATERAL_TYPES = ("none", "financial", "receivables", "rre", "cre", "other_physical")

# Output-floor phase-in, CRR Art. 465(1)
OUTPUT_FLOOR_PHASE_IN = {2025: 0.50, 2026: 0.55, 2027: 0.60, 2028: 0.65, 2029: 0.70, 2030: 0.725}


def output_floor_factor(year: int) -> float:
    if year <= 2025:
        return OUTPUT_FLOOR_PHASE_IN[2025]
    return OUTPUT_FLOOR_PHASE_IN.get(year, 0.725)


@dataclass(frozen=True)
class Regime:
    name: str
    scaling_factor: float                  # 1.06 removed by CRR3
    pd_floor_corporate: float
    pd_floor_retail: float
    pd_floor_qrre_revolver: float
    # A-IRB LGD input floors (Art. 161(5) and 164(4))
    lgd_floor_corp_unsecured: float
    lgd_floor_retail_other_unsecured: float
    lgd_floor_qrre: float
    lgd_floor_rre: float
    lgd_floor_secured: Dict[str, float]    # LGDS floors by collateral type
    # F-IRB supervisory LGDs (Art. 161(1)) and collateral (Art. 230)
    firb_lgd_senior_corp: float
    firb_lgd_senior_fse: float
    firb_lgd_subordinated: float
    firb_lgds: Dict[str, float]
    firb_haircut: Dict[str, float]
    ccf_floor_share_of_sa: float           # A-IRB CCF >= x * SA CCF
    apply_input_floors: bool = True


CRR3 = Regime(
    name="CRR3",
    scaling_factor=1.0,
    pd_floor_corporate=0.0005,
    pd_floor_retail=0.0005,
    pd_floor_qrre_revolver=0.0010,
    lgd_floor_corp_unsecured=0.25,
    lgd_floor_retail_other_unsecured=0.30,
    lgd_floor_qrre=0.50,
    lgd_floor_rre=0.05,
    lgd_floor_secured={"none": 0.25, "financial": 0.0, "receivables": 0.10,
                       "rre": 0.10, "cre": 0.10, "other_physical": 0.15},
    firb_lgd_senior_corp=0.40,
    firb_lgd_senior_fse=0.45,
    firb_lgd_subordinated=0.75,
    firb_lgds={"financial": 0.0, "receivables": 0.20, "rre": 0.20, "cre": 0.20,
               "other_physical": 0.25},
    # financial collateral is entered already haircut-adjusted (C x (1 - Hc - Hfx))
    firb_haircut={"financial": 0.0, "receivables": 0.40, "rre": 0.40, "cre": 0.40,
                  "other_physical": 0.40},
    ccf_floor_share_of_sa=0.50,
)

LEGACY = Regime(
    name="LEGACY",
    scaling_factor=1.06,
    pd_floor_corporate=0.0003,
    pd_floor_retail=0.0003,
    pd_floor_qrre_revolver=0.0003,
    lgd_floor_corp_unsecured=0.0,
    lgd_floor_retail_other_unsecured=0.0,
    lgd_floor_qrre=0.0,
    lgd_floor_rre=0.0,
    lgd_floor_secured={k: 0.0 for k in COLLATERAL_TYPES},
    firb_lgd_senior_corp=0.45,
    firb_lgd_senior_fse=0.45,
    firb_lgd_subordinated=0.75,
    firb_lgds={"financial": 0.0, "receivables": 0.35, "rre": 0.35, "cre": 0.35,
               "other_physical": 0.40},
    firb_haircut={"financial": 0.0, "receivables": 0.40, "rre": 0.40, "cre": 0.40,
                  "other_physical": 0.40},
    ccf_floor_share_of_sa=0.0,
    apply_input_floors=False,
)

REGIMES = {"CRR3": CRR3, "LEGACY": LEGACY}

# --------------------------------------------------------------------------- #
# Standardised approach (SA-CR) risk weights - CRR3
# --------------------------------------------------------------------------- #
SA_CORP_CQS = {1: 0.20, 2: 0.50, 3: 0.75, 4: 1.00, 5: 1.50, 6: 1.50}   # Art. 122(1)
SA_CORP_UNRATED = 1.00                                                 # Art. 122(2)
SA_CORP_IG_TRANSITIONAL = 0.65                                         # Art. 465(3), to 2032
SA_RETAIL_REGULATORY = 0.75                                            # Art. 123
SA_RETAIL_TRANSACTOR = 0.45
SA_RETAIL_NON_REGULATORY = 1.00
SA_RETAIL_MAX_AMOUNT = 1_000_000                                       # EUR 1m threshold
# Residential real estate, not materially dependent on cash flows (Art. 125(1))
SA_RRE_SECURED_RW = 0.20
SA_RRE_SECURED_SHARE = 0.55
# Commercial real estate, not IPRE (Art. 126(1))
SA_CRE_SECURED_RW = 0.60
SA_CRE_SECURED_SHARE = 0.55
# IPRE whole-loan tables (Basel CRE20.82 / CRE20.87 calibration)
SA_RRE_IPRE_TABLE = [(0.50, 0.30), (0.60, 0.35), (0.80, 0.45), (0.90, 0.60), (1.00, 0.75),
                     (float("inf"), 1.05)]
SA_CRE_IPRE_TABLE = [(0.60, 0.70), (0.80, 0.90), (float("inf"), 1.10)]
# Art. 465(5) transitional treatment for RRE under the output floor
SA_RRE_TRANSITIONAL_LOW = 0.10      # portion up to 55 % of property value
SA_RRE_TRANSITIONAL_MID = 0.45      # portion between 55 % and 80 %
# Defaulted exposures (Art. 127)
SA_DEFAULT_LOW_PROV = 1.50
SA_DEFAULT_HIGH_PROV = 1.00
SA_DEFAULT_PROV_THRESHOLD = 0.20

# SME supporting factor (Art. 501)
SME_SF_THRESHOLD = 2_500_000
SME_SF_LOW = 0.7619
SME_SF_HIGH = 0.85
SME_SF_MAX_TURNOVER_M = 50.0

# --------------------------------------------------------------------------- #
# Own funds requirements (Art. 92 CRR, Arts. 128-142 CRD)
# --------------------------------------------------------------------------- #
@dataclass
class CapitalSettings:
    cet1_min: float = 0.045
    t1_min: float = 0.06
    total_min: float = 0.08
    p2r: float = 0.0
    conservation_buffer: float = 0.025
    countercyclical_buffer: float = 0.01   # France: 1 % (HCSF, maintained June 2026)
    systemic_buffer: float = 0.0           # max(G-SII/O-SII, SyRB) simplified
    excess_provision_t2_cap: float = 0.006 # Art. 62(d): 0.6 % of IRB credit RWA

    @property
    def combined_buffer(self) -> float:
        return self.conservation_buffer + self.countercyclical_buffer + self.systemic_buffer

    def requirements(self) -> Dict[str, float]:
        cbr = self.combined_buffer
        return {
            "CET1": self.cet1_min + 0.5625 * self.p2r + cbr,
            "Tier 1": self.t1_min + 0.75 * self.p2r + cbr,
            "Total capital": self.total_min + self.p2r + cbr,
        }
