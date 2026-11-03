# Sources of edge and base rates

Ranges are indicative, rounded from the cited sources, and gross of costs unless stated. They are for sanity checks, not targets. (Expert review of this file is planned before v1.0.)

## Contents
- Sources of edge
- Base rates: how often published effects survive
- Typical Sharpe ratios by strategy family
- Using the base rate

## Sources of edge

| Source | Mechanism | Counterparty | Typical failure mode |
|---|---|---|---|
| **Risk premium** | Compensation for bearing a risk others want to shed (equity, carry, crash, liquidity) | Hedgers and risk-averse investors paying for insurance | Large drawdowns exactly when the risk materialises; "alpha" is beta to a known factor |
| **Behavioural** | Systematic mistakes: under-reaction, over-extrapolation, disposition effect, lottery preference | Investors making the mistake | Decays once published and arbitraged (McLean & Pontiff 2016) |
| **Structural** | Rules or constraints force someone to trade: index rebalancing, roll schedules, mandate limits, liquidity demand | Constrained or urgent traders paying for immediacy | Small capacity; disappears when the rule changes |

No identifiable counterparty is itself the most informative answer: the result is then most likely noise or data error.

## Base rates: how often published effects survive

- Anomaly returns are about 26% lower out of sample and about 58% lower after publication (McLean & Pontiff 2016, *Journal of Finance* 71(1)).
- With hundreds of factors tried, a new factor needs a t-statistic above about 3.0, not 2.0 (Harvey, Liu & Zhu 2016, *Review of Financial Studies* 29(1)).
- In one large replication, a majority of 452 anomalies were insignificant at |t| ≥ 1.96 once micro-caps were controlled for (Hou, Xue & Zhang 2020, *Review of Financial Studies* 33(5)). Others find most replicate with original methods (Chen & Zimmermann 2022, *Critical Finance Review*); the disagreement is mainly about micro-caps and weighting.
- Backtest overfitting: with enough variants, a high in-sample Sharpe is expected under the null (Bailey, Borwein, López de Prado & Zhu 2014, *Notices of the AMS* 61(5)).

## Typical Sharpe ratios by strategy family

| Family | Indicative annualised Sharpe | Source |
|---|---|---|
| Broad equity market, excess return | 0.3–0.5 over long histories | Dimson, Marsh & Staunton, *Global Investment Returns Yearbook* |
| Single equity factor long-short (value, momentum) | 0.2–0.7 gross | Asness, Moskowitz & Pedersen 2013, *Journal of Finance* 68(3) |
| Equity momentum (US, 1927–2013) | ≈ 0.5 gross, with crashes | Daniel & Moskowitz 2016, *Journal of Financial Economics* 122(2) |
| Diversified time-series momentum across futures | ≈ 1 gross (1985–2009), weaker since | Moskowitz, Ooi & Pedersen 2012, *JFE* 104(2) |
| Diversified carry across asset classes | ≈ 0.8–1.2 gross | Koijen, Moskowitz, Pedersen & Vrugt 2018, *JFE* 127(2) |
| Equity pairs trading (distance method) | positive but declining over time | Gatev, Goetzmann & Rouwenhorst 2006, *RFS* 19(3); Do & Faff 2010, *FAJ* 66(4) |

A single-asset or single-pair strategy should sit at or below these diversified numbers. A daily net Sharpe above 2 is almost always an error: look-ahead, stale prices, survivorship or missing costs.

## Using the base rate

1. Name the closest family above and its range in the hypothesis rationale.
2. If the backtest Sharpe is more than about twice the family range, look for errors before celebrating (`qrkit red-flags`).
3. If the edge is behavioural and published, expect the post-publication decay above and set `min_effect` accordingly.
