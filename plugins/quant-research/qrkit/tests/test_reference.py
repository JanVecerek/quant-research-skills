"""Reference values against statsmodels / arch and published examples."""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats as st
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import adfuller, coint

from qrkit import meanrev, stats, validate


@pytest.fixture
def ar1():
    rng = np.random.default_rng(42)
    x = np.zeros(1000)
    for t in range(1, 1000):
        x[t] = 0.9 * x[t - 1] + rng.normal()
    return pd.Series(x)


def test_adf_matches_statsmodels(ar1):
    r = stats.adf(ar1)
    ref = adfuller(ar1.values, regression="c", autolag="AIC")
    assert r["statistic"] == pytest.approx(ref[0])
    assert r["p_value"] == pytest.approx(ref[1])


def test_stationarity_verdict(ar1):
    assert stats.stationarity(ar1)["verdict"].startswith("stationary")
    rw = pd.Series(np.cumsum(np.random.default_rng(1).normal(size=1000)))
    assert not stats.stationarity(rw)["verdict"].startswith("stationary")


def test_hac_mean_matches_statsmodels():
    y = np.random.default_rng(3).normal(0.05, 1, 500)
    r = stats.hac_mean(pd.Series(y), lags=5, alternative="two-sided")
    m = sm.OLS(y, np.ones(500)).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    assert r["statistic"] == pytest.approx(m.tvalues[0])
    assert r["p_value"] == pytest.approx(m.pvalues[0], rel=1e-6)


@pytest.mark.parametrize("method,ref", [("holm", "holm"), ("bh", "fdr_bh")])
def test_multiple_testing_matches_statsmodels(method, ref):
    p = {f"t{i}": v for i, v in enumerate([0.001, 0.01, 0.02, 0.04, 0.3])}
    r = stats.multiple(p, method)
    _, padj, _, _ = multipletests(list(p.values()), method=ref)
    assert [x["p_adjusted"] for x in r["results"]] == pytest.approx(list(padj))


def test_sharpe_iid_se_formula():
    y = np.random.default_rng(5).normal(0.001, 0.01, 2520)
    r = stats.sharpe(pd.Series(y), ppy=252)
    sr = y.mean() / y.std(ddof=1)
    assert r["se_iid_annualised"] == pytest.approx(np.sqrt((1 + sr**2 / 2) / len(y)) * np.sqrt(252))
    # on iid data the HAC (GMM) and iid standard errors agree closely (Lo 2002)
    assert r["se_hac_annualised"] == pytest.approx(r["se_iid_annualised"], rel=0.1)


def test_sharpe_hac_ci_coverage():
    """95% CI covers the true Sharpe in roughly 95% of AR(1) samples."""
    rng = np.random.default_rng(11)
    true_sr, hits = 0.05, 0
    for _ in range(300):
        e = rng.normal(size=1000)
        u = np.zeros(1000)
        for t in range(1, 1000):
            u[t] = 0.3 * u[t - 1] + e[t]
        u = u / np.sqrt(1 / (1 - 0.09))
        y = true_sr + u
        lo, hi = stats.sharpe(pd.Series(y), ppy=1)["ci_annualised_hac"]
        hits += lo <= true_sr <= hi
    assert 0.90 <= hits / 300 <= 0.99


def test_engle_granger_matches_coint():
    rng = np.random.default_rng(2)
    b = np.cumsum(rng.normal(size=800))
    a = 0.5 + 1.2 * b + rng.normal(size=800)
    r = meanrev.engle_granger(pd.Series(a), pd.Series(b))
    ref = coint(a, b, trend="c", autolag="aic")
    assert r["results"]["a_on_b"]["p_value"] == pytest.approx(ref[1])
    assert r["verdict"] == "cointegrated in both directions"


def test_variance_ratio_matches_arch():
    from arch.unitroot import VarianceRatio

    x = np.cumsum(np.random.default_rng(4).normal(size=1000))
    r = meanrev.variance_ratio(pd.Series(x), lags=4)
    ref = VarianceRatio(x, lags=4, trend="c", robust=True, overlap=True)
    assert r["vr"] == pytest.approx(ref.vr)
    assert r["p_value"] == pytest.approx(ref.pvalue)


def test_half_life_recovers_ou():
    rng = np.random.default_rng(9)
    phi = np.exp(-np.log(2) / 10)
    s = np.zeros(20000)
    for t in range(1, 20000):
        s[t] = phi * s[t - 1] + rng.normal()
    assert meanrev.half_life(pd.Series(s))["half_life"] == pytest.approx(10, rel=0.15)


def test_tls_hedge_is_symmetric():
    rng = np.random.default_rng(8)
    b = np.cumsum(rng.normal(size=2000))
    a = 2.0 * b + rng.normal(size=2000)
    _, beta_ab = meanrev._fit(a, b, "tls")
    _, beta_ba = meanrev._fit(b, a, "tls")
    assert beta_ab * beta_ba == pytest.approx(1.0, rel=1e-6)


def test_expected_max_sharpe_published_example():
    """Bailey & Lopez de Prado (2014), numerical example: N=100, V[SR]=0.5 annualised,
    daily data -> SR0 ~= 0.1132 per day."""
    sr0 = validate.expected_max_sharpe(100, 0.5 / 250)
    assert sr0 == pytest.approx(0.1132, abs=5e-4)


def test_psr_matches_closed_form():
    y = np.random.default_rng(1).normal(0.001, 0.01, 1000)
    sr = y.mean() / y.std(ddof=1)
    g3, g4 = st.skew(y), st.kurtosis(y, fisher=False)
    ref = st.norm.cdf(sr * np.sqrt(999) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr**2))
    assert validate.psr(pd.Series(y)) == pytest.approx(ref)
