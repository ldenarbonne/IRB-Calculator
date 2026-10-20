### 1. IRB capital requirement (Art. 153-154 CRR)

For a non-defaulted exposure:

$$K = \left[LGD \cdot N\!\left(\frac{N^{-1}(PD) + \sqrt{R}\,N^{-1}(0.999)}{\sqrt{1-R}}\right) - PD \cdot LGD\right] \cdot MA$$

$$RW = 12.5 \cdot K \cdot s, \qquad RWA = RW \cdot EAD \cdot f_{SME}, \qquad EL = PD \cdot LGD \cdot EAD$$

with $s = 1$ under CRR3 (the 1.06 scaling factor is removed; $s = 1.06$ in *LEGACY* mode).

| Class | Correlation R | Maturity adjustment |
|---|---|---|
| Corporate | $0.12\,w + 0.24\,(1-w)$, $w = \frac{1-e^{-50PD}}{1-e^{-50}}$ | $MA = \frac{1+(M-2.5)\,b}{1-1.5\,b}$, $b = (0.11852 - 0.05478 \ln PD)^2$ |
| SME corporate (S <= EUR 50m) | corporate R $- 0.04\left(1 - \frac{\min(\max(S,5),50)-5}{45}\right)$ | idem |
| Large (>= EUR 70bn) / unregulated FSE | 1.25 x corporate R | idem |
| Retail - residential mortgage | 0.15 | none |
| Retail - QRRE | 0.04 | none |
| Other retail | $0.03\,w + 0.16\,(1-w)$, $w = \frac{1-e^{-35PD}}{1-e^{-35}}$ | none |

M is bounded to [1 ; 5] years. **Defaulted exposures:** A-IRB / retail: $K = \max(0, LGD - ELBE)$, $EL = ELBE \cdot EAD$; F-IRB: $K = 0$, $EL = LGD_{F-IRB} \cdot EAD$.

### 2. CRR3 input floors and approach restrictions

* **PD floors:** 0.05 % (corporates, retail), 0.10 % (QRRE revolvers).
* **A-IRB LGD floors:** corporates unsecured 25 %; retail other unsecured 30 %; QRRE 50 %; retail RRE 5 %; secured part: financial 0 %, receivables 10 %, real estate 10 %, other physical 15 %. Partially secured: $LGD_{floor} = \frac{E_U \cdot LGD_U + E_S \cdot LGD_S}{E}$ (Art. 161(6)).
* **CCF floor:** own-estimate CCF >= 50 % of the SA CCF; F-IRB uses the SA CCF.
* **Art. 147a:** financial sector entities and large corporates (turnover > EUR 500m) are restricted to F-IRB; the tool switches them automatically and flags it.

### 3. F-IRB supervisory LGD (Art. 161(1), Art. 230)

Unsecured: 40 % senior corporates, 45 % financial sector entities, 75 % subordinated.
Secured: $LGD^* = \frac{E_U \cdot LGD_U + E_S \cdot LGD_S}{E}$, $E_S = \min(C(1-H_C), E)$, with $LGD_S$ = 0 % financial, 20 % receivables, 20 % real estate, 25 % other physical, and $H_C$ = 40 % (non-financial). Financial collateral is entered **already haircut-adjusted**.

### 4. Standardised approach (SA-CR)

* EAD$_{SA}$ = (drawn - specific provisions) + CCF$_{SA}$ x undrawn; financial collateral reduces the exposure (comprehensive method, adjusted value).
* Corporates: CQS 1-6 -> 20 / 50 / 75 / 100 / 150 / 150 %; unrated 100 %; unrated internally investment grade 65 % (Art. 465(3), transitional to 2032).
* Retail: 75 % regulatory retail (<= EUR 1m), 45 % QRRE transactors, 100 % otherwise.
* Residential real estate: loan-splitting, 20 % up to 55 % of property value, counterparty RW on the rest; optional Art. 465(5) transitional (10 % / 45 %). IPRE: whole-loan LTV table 30-105 %.
* Commercial real estate: min(60 %, counterparty RW) up to 55 % of property value; IPRE: 70 / 90 / 110 %.
* Defaulted: 100 % if specific provisions >= 20 % of the exposure, 150 % otherwise; 100 % for non-IPRE RRE.

### 5. SME supporting factor (Art. 501)

$f_{SME} = \frac{\min(E, 2.5m) \cdot 0.7619 + \max(E - 2.5m, 0) \cdot 0.85}{E}$, applied to IRB and SA RWA of eligible non-defaulted SMEs (turnover <= EUR 50m). Simplification: E is the exposure itself, not the total amount owed by the obligor group.

### 6. Output floor (Art. 92(3), Art. 465)

$TREA = \max(U\text{-}TREA \; ; \; x \cdot S\text{-}TREA)$ with $x$ = 50 % (2025), 55 %, 60 %, 65 %, 70 %, 72.5 % (2030+). Optional transitional cap: TREA <= 125 % U-TREA until 2029.

### 7. Provisions and own funds

IRB EL is compared with credit risk adjustments separately for defaulted and non-defaulted exposures (Art. 159): the shortfall is deducted from CET1 (Art. 36(1)(d)); the excess is added to T2 up to 0.6 % of IRB credit RWA (Art. 62(d)). Requirements: CET1 4.5 % + 56.25 % P2R + CBR; T1 6 % + 75 % P2R + CBR; total 8 % + P2R + CBR, CBR = 2.5 % CCB + CCyB + systemic buffers.

### 8. Input columns

`id, exposure_class, approach, pd, lgd, seniority, collateral_type, collateral_value, property_value, ipre, maturity, turnover_m, drawn, undrawn, ccf_irb, ccf_sa, defaulted, elbe, provisions, sa_cqs, sa_ig, sme_sf`

Exposure classes: `CORP, FSE, FSE_LARGE, RET_RRE, RET_QRRE_REV, RET_QRRE_TRANS, RET_OTHER`. Collateral types: `none, financial, receivables, rre, cre, other_physical`.

### 9. Scope and limitations

Not covered: sovereigns, institutions, specialised lending (slotting), equity, purchased receivables, securitisation, CCR/CVA, double default and guarantees (PD/RW substitution), maturity mismatch, FX haircuts, exposure-group SME thresholds. The IPRE residential table follows the Basel calibration (CRE20.82) and must be checked against the EU text (Art. 125(2)). F-IRB maturity: verify against Art. 162 whether the supervisory 2.5-year value is applicable in your context.
