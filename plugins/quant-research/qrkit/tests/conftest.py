import socket

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must not touch the network."""

    def guard(*a, **k):
        raise RuntimeError("network access attempted during tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QRKIT_OUTPUT", str(tmp_path / "qr-output"))
    return tmp_path


def make_panel(n=600, assets=4, seed=0):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2015-01-01", periods=n)
    rows = []
    for i in range(assets):
        p = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        rows.append(pd.DataFrame({"date": d, "asset": f"A{i}", "close": p, "volume": rng.integers(1e5, 1e6, n)}))
    return pd.concat(rows, ignore_index=True)
