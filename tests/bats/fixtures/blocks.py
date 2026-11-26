# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""Blocks of a download committed into the repository at PATH as arco-make commits them: each on
the run's branch, its interval in the commit's metadata; then `main` moved to the run's last
commit and the branch deleted (the run complete), unless --running. What the stand-in arco-make
of tests/bats/progress.bats writes. Usage: blocks.py PATH [--running] START/END..."""

import sys

import icechunk
import numpy as np
import xarray as xr
from arcomake import icechunk_utils

path, *blocks = sys.argv[1:]
running = "--running" in blocks
blocks = [block for block in blocks if block != "--running"]
repo = icechunk.Repository.open_or_create(icechunk.local_filesystem_storage(path))
label = icechunk_utils.run_label("download")
branch = f"run/{label}"
repo.create_branch(branch, repo.lookup_branch("main"))
for block in blocks:
  start, end = block.split("/")
  session = repo.writable_session(branch)
  xr.Dataset({"x": ("t", np.zeros(1))}).to_zarr(session.store, mode="w", consolidated=False)
  session.commit(
    f"download [{start}, {end})",
    metadata={
      icechunk_utils.RUN_KEY: label,
      icechunk_utils.BLOCK_KEY: f"{start}T00:00/{end}T00:00",
    },
  )
if not running:
  repo.reset_branch("main", repo.lookup_branch(branch))
  repo.delete_branch(branch)
