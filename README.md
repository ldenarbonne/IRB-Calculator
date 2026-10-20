# IRB & Standardised Credit-Risk Capital Calculator (CRR3)

A Streamlit application computing **regulatory capital for credit risk** from PD, LGD and EAD inputs:

* **IRB** - Foundation and Advanced approaches, corporates (incl. SME and large/unregulated financial sector entities) and retail (residential mortgages, QRRE revolvers and transactors, other retail);
* **CRR3 features** - removal of the 1.06 scaling factor, PD / LGD / CCF input floors, Art. 147a approach restrictions;
* **Standardised approach (SA-CR)** - the benchmark needed for the **output floor**, with its 2025-2030 phase-in and transitional provisions;
* **Expected loss vs provisions**, CET1 deduction / T2 add-back, and **own funds requirements** (Pillar 1, P2R, combined buffer);
* **Sensitivity** charts of the risk-weight curves.

It closes the chain started by my companion projects:
[PD models for French SMEs](https://github.com/ldenarbonne/PD-models-for-French-SMEs) ->
[LGD modelling](https://github.com/ldenarbonne/lgd-modelling) -> EAD calculator -> **capital**.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q          # unit tests
```

## Validation

The IRB formulas are reconciled to 1e-12 with my 2021 Excel/VBA IRB calculator (run in `LEGACY` mode, which re-introduces the 1.06 factor), and with the Basel reference value (PD 1 %, LGD 45 %, M 2.5 -> RW 92.3 %). See `tests/test_engine.py`.

## Structure

```
app.py                      Streamlit UI
capital_engine/parameters.py  Regulatory parameters (CRR3 and legacy)
capital_engine/engine.py      IRB, SA-CR, output floor, provisions, own funds
data/sample_portfolio.csv     15-exposure sample / template
METHODOLOGY.md                Formulas, references, limitations
tests/test_engine.py          Unit tests
```

## Disclaimer

Educational tool. It is not a regulatory reporting system and does not replace the legal text of Regulation (EU) No 575/2013 as amended by Regulation (EU) 2024/1623.

Author: Laurent Motais de Narbonne
