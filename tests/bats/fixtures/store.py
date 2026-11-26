# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""A forecast repository at PATH with two runs, the newest LATEST (YYYY-MM-DD), and a flag: what
the stand-in download.sh of tests/bats/forecast.bats stores. Usage: store.py PATH LATEST."""

import sys

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

path, latest = sys.argv[1:]
init = pd.date_range(end=latest, periods=2, freq="D").values
lead = pd.to_timedelta([0, 1], unit="D").values
flag = (("init_time", "lead_time"), np.ones((2, 2), dtype=bool))
dataset = xr.Dataset({"ifs_forecast": flag}, coords={"init_time": init, "lead_time": lead})
repo = icechunk.Repository.open_or_create(icechunk.local_filesystem_storage(path))
session = repo.writable_session("main")
dataset.to_zarr(session.store, mode="w", consolidated=False)
session.commit("forecast")
