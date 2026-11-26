# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/forecast.sh's heartbeat, with a stand-in for scripts/download.sh: the states it
publishes when the downloads succeed, wait for a run, fail, or when the collection is killed, and
its exit status when the collection finishes behind."""

import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

import pytest

SCRIPTS = pathlib.Path(__file__).parents[2] / "scripts"

# Records its arguments in $CALLS, if set; stores in its repository (DATA_ROOT/forecast/res=RES,
# from --data-root) runs up to the day given for its resolution (FAKE_LATEST="1p0=2026-11-24";
# default none); exits with the code given for it (FAKE_CODES="1p0=75,0p5=1"; default 0), after
# FAKE_SLEEP seconds.
FAKE_DOWNLOAD = """#!/usr/bin/env bash
if [[ -n "${CALLS:-}" ]]; then echo "$*" >> "${CALLS}"; fi
RECIPE="${@: -1}"
RES="${RECIPE#forecast_res-}"
ROOT=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == --data-root ]]; then ROOT="$2"; fi
    shift
done
sleep "${FAKE_SLEEP:-0}"
for PAIR in ${FAKE_LATEST//,/ }; do
    if [[ "${PAIR%%=*}" == "${RES}" ]]; then
        "${FAKE_PYTHON}" "${FAKE_STORE}" "${ROOT}/forecast/res=${RES}" "${PAIR#*=}" || exit 1
    fi
done
for PAIR in ${FAKE_CODES//,/ }; do
    if [[ "${PAIR%%=*}" == "${RES}" ]]; then exit "${PAIR#*=}"; fi
done
exit 0
"""

# A forecast repository with two runs, the newest the given day, and a flag.
STORE = """import sys

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
"""

# Every run stored, up to the newest asked for (--end 2026-11-25: the run of the 24th).
STORED = "0p5=2026-11-24,1p0=2026-11-24"

pytestmark = pytest.mark.skipif(
  shutil.which("flock") is None or sys.platform != "linux", reason="needs Linux (flock, date -d)"
)


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
  scripts = tmp_path / "scripts"
  scripts.mkdir()
  for name in ("forecast.sh", "settings.sh", ".env"):
    shutil.copy(SCRIPTS / name, scripts / name)
  (scripts / "download.sh").write_text(FAKE_DOWNLOAD)
  (scripts / "download.sh").chmod(0o755)
  (tmp_path / "store.py").write_text(STORE)
  return tmp_path


def start(project: pathlib.Path, *args: str, **env: str) -> subprocess.Popen:
  # The heartbeat runs the `arco-ocean` of this interpreter's environment.
  cli = pathlib.Path(sys.prefix) / "bin" / "arco-ocean"
  fakes = {"FAKE_PYTHON": sys.executable, "FAKE_STORE": str(project / "store.py")}
  return subprocess.Popen(
    [
      "bash", str(project / "scripts" / "forecast.sh"), "--project-dir", str(project),
      "--status-url", str(project / "www" / "forecast.json"),
      "--res", "0p5,1p0", "--end", "2026-11-25", *args,
    ],
    env={**os.environ, "DATA_ROOT": str(project), "ARCO_OCEAN_CLI": str(cli), **fakes, **env},
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    start_new_session=True,  # its own process group, signalled as a whole
  )  # fmt: skip


def published(project: pathlib.Path) -> dict:
  return json.loads((project / "www" / "forecast.json").read_text())


def states(document: dict) -> dict[str, str]:
  return {entry["res"]: entry["state"] for entry in document["resolutions"]}


def test_a_collection_that_finishes(project) -> None:
  process = start(project, FAKE_LATEST=STORED)
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 0, output
  document = published(project)
  assert document["state"] == "finished"
  assert document["detail"] is None
  assert document["target_run"] == "2026-11-24"
  assert states(document) == {"0p5": "finished", "1p0": "finished"}
  assert document["resolutions"][0]["latest_run"] == "2026-11-24"
  assert str(project) not in (project / "www" / "forecast.json").read_text()


def test_a_collection_finished_behind_fails(project) -> None:
  # Stored, but a source stopped: its runs come in without it, days late; or nothing stored. The
  # page calls it stale, and the unit fails, for its alert (scripts/alert.sh).
  process = start(project, FAKE_LATEST="0p5=2026-11-24,1p0=2026-11-20")
  output, _ = process.communicate(timeout=120)
  # 3: behind, for the alert to tell it from a failed download.
  assert process.returncode == 3, output
  assert "finished behind: 1.0°'s newest run is 2026-11-20, 4 days before the newest" in output
  assert published(project)["state"] == "finished"
  nothing = start(project, "--data-root", str(project / "empty"))
  output, _ = nothing.communicate(timeout=120)
  assert nothing.returncode == 3 and "0.5° has no run stored" in output


def test_a_run_not_published_yet_finishes_with_a_detail(project) -> None:
  process = start(project, FAKE_CODES="1p0=75", FAKE_LATEST="0p5=2026-11-24,1p0=2026-11-23")
  output, _ = process.communicate(timeout=120)
  # 75, not a failure: the systemd unit counts it a success.
  assert process.returncode == 75, output
  document = published(project)
  assert document["state"] == "finished"
  assert "not published the newest run yet (1p0)" in document["detail"]
  assert states(document) == {"0p5": "finished", "1p0": "not_published"}


def test_a_failed_download_aborts(project) -> None:
  process = start(project, FAKE_CODES="0p5=1")
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 1, output
  document = published(project)
  assert document["state"] == "aborted"
  assert "failed at 0p5" in document["detail"]
  assert states(document) == {"0p5": "failed", "1p0": "finished"}


def test_the_heartbeat_beats_and_a_killed_collection_aborts(project) -> None:
  process = start(project, "--heartbeat", "1", FAKE_SLEEP="30")
  deadline = time.monotonic() + 60
  while time.monotonic() < deadline:
    path = project / "www" / "forecast.json"
    if path.exists() and states(published(project)).get("0p5") == "downloading":
      break
    time.sleep(0.2)
  first = published(project)["updated_at"]
  assert first is not None
  # The beat moves the heartbeat on (to the second) while the download runs.
  deadline = time.monotonic() + 30
  while published(project)["updated_at"] == first and time.monotonic() < deadline:
    time.sleep(0.2)
  assert published(project)["updated_at"] != first
  assert published(project)["state"] == "running"

  # Killing a collection (Ctrl-C, systemd, kill of the job) signals its process group.
  os.killpg(process.pid, signal.SIGTERM)
  output, _ = process.communicate(timeout=60)
  assert process.returncode == 143, output
  document = published(project)
  assert document["state"] == "aborted"
  assert "exit status 143" in document["detail"]
  assert states(document)["0p5"] == "failed"
  # No beat is left behind, and the heartbeat stays as it ended.
  time.sleep(2.5)
  assert published(project) == document


def test_without_status_url_there_is_no_heartbeat(project) -> None:
  process = subprocess.run(
    [
      "bash", str(project / "scripts" / "forecast.sh"), "--project-dir", str(project),
      "--virtual-env", str(sys.prefix), "--res", "1p0", "--end", "2026-11-25",
    ],
    capture_output=True, text=True, timeout=120,
  )  # fmt: skip
  # Without a heartbeat, nothing tells it behind: nothing is stored, and it succeeds.
  assert process.returncode == 0, process.stdout + process.stderr
  assert not (project / "www").exists()
  assert not (project / "logs" / "forecast" / "status.json").exists()


def test_a_data_root_goes_to_the_downloads_and_the_heartbeat(project) -> None:
  # A local root: the heartbeat really reads there, offline.
  calls, root = project / "calls", project / "store"
  process = start(project, "--data-root", str(root), CALLS=str(calls), FAKE_LATEST=STORED)
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 0, output
  lines = calls.read_text().splitlines()
  assert len(lines) == 2
  assert all(f"--data-root {root}" in line for line in lines)
  # The heartbeat reads the repositories where the downloads write them (kept in the state
  # file, not published).
  state = json.loads((project / "logs" / "forecast" / "status.json").read_text())
  assert state["repositories"] == {
    "0p5": f"{root}/forecast/res=0p5",
    "1p0": f"{root}/forecast/res=1p0",
  }
  assert published(project)["resolutions"][1]["latest_run"] == "2026-11-24"
  assert str(root) not in (project / "www" / "forecast.json").read_text()


@pytest.mark.parametrize("value", ["0", "0.0", "-1", "two"])
def test_missing_after_must_be_a_positive_number_of_days(project, value) -> None:
  # 0 would fail every collection a day behind, the normal wait for today's run (the page reads
  # it as its default, two days).
  process = start(project, "--missing-after", value)
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 1 and "takes a positive number of days" in output


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_the_heartbeat_runs_in_the_checkouts_environment(tmp_path) -> None:
  # As the unit runs it: forecast.sh of the checkout, its heartbeat through `uv run` (no
  # ARCO_OCEAN_CLI), its downloads through download.sh with a stand-in arco-make, nothing stored.
  arco_make = tmp_path / "venv" / "bin" / "arco-make"
  arco_make.parent.mkdir(parents=True)
  arco_make.write_text("#!/usr/bin/env bash\nexit 0\n")
  arco_make.chmod(0o755)
  (tmp_path / "configs" / "download").mkdir(parents=True)
  (tmp_path / "configs" / "download" / "forecast_res-1p0.toml").write_text("")
  environ = {k: v for k, v in os.environ.items() if k != "ARCO_OCEAN_CLI"}
  process = subprocess.run(
    [
      "bash", str(SCRIPTS / "forecast.sh"), "--project-dir", str(tmp_path),
      "--virtual-env", str(tmp_path / "venv"), "--env-file", "", "--attempts", "1",
      "--status-url", str(tmp_path / "www" / "forecast.json"), "--res", "1p0",
      "--end", "2026-11-25",
    ],
    env={**environ, "DATA_ROOT": str(tmp_path / "store"), "PYTHONPATH": str(tmp_path)},
    capture_output=True, text=True, timeout=300,
  )  # fmt: skip
  output = process.stdout + process.stderr
  assert process.returncode == 3 and "1.0° has no run stored" in output, output
  document = json.loads((tmp_path / "www" / "forecast.json").read_text())
  assert document["state"] == "finished" and states(document) == {"1p0": "finished"}


def test_an_empty_data_root_is_refused(project) -> None:
  # Empty, it would fall back to the local disk silently.
  process = start(project, "--data-root=")
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 1
  assert "--data-root" in output
