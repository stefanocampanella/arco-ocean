# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/forecast.sh's heartbeat, with a stand-in for scripts/download.sh: the states it
publishes when the downloads succeed, wait for a run, fail, or when the collection is killed."""

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

# Records its arguments in $CALLS, if set; exits with the code given for its recipe's resolution
# (FAKE_CODES="1p0=75,0p5=1"; default 0), after FAKE_SLEEP seconds.
FAKE_DOWNLOAD = """#!/usr/bin/env bash
if [[ -n "${CALLS:-}" ]]; then echo "$*" >> "${CALLS}"; fi
RECIPE="${@: -1}"
RES="${RECIPE#forecast_res-}"
sleep "${FAKE_SLEEP:-0}"
for PAIR in ${FAKE_CODES//,/ }; do
    if [[ "${PAIR%%=*}" == "${RES}" ]]; then exit "${PAIR#*=}"; fi
done
exit 0
"""

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
  return tmp_path


def start(project: pathlib.Path, *args: str, **env: str) -> subprocess.Popen:
  # The heartbeat runs the `arco-ocean` of this interpreter's environment.
  cli = pathlib.Path(sys.prefix) / "bin" / "arco-ocean"
  return subprocess.Popen(
    [
      "bash", str(project / "scripts" / "forecast.sh"), "--project-dir", str(project),
      "--status-url", str(project / "www" / "forecast.json"),
      "--res", "0p5,1p0", "--end", "2026-11-25", *args,
    ],
    env={**os.environ, "DATA_ROOT": str(project), "ARCO_OCEAN_CLI": str(cli), **env},
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
  process = start(project)
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 0, output
  document = published(project)
  assert document["state"] == "finished"
  assert document["detail"] is None
  assert document["target_run"] == "2026-11-24"
  assert states(document) == {"0p5": "finished", "1p0": "finished"}
  # No repository was written by the stand-in: nothing stored, and no path published.
  assert document["resolutions"][0]["latest_run"] is None
  assert str(project) not in (project / "www" / "forecast.json").read_text()


def test_a_run_not_published_yet_finishes_with_a_detail(project) -> None:
  process = start(project, FAKE_CODES="1p0=75")
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
  assert process.returncode == 0, process.stdout + process.stderr
  assert not (project / "www").exists()
  assert not (project / "logs" / "forecast" / "status.json").exists()


def test_a_data_root_goes_to_the_downloads_and_the_heartbeat(project) -> None:
  # A local root: the heartbeat really reads there (no repository, nothing stored), offline.
  calls, root = project / "calls", project / "store"
  process = start(project, "--data-root", str(root), CALLS=str(calls))
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
  assert str(root) not in (project / "www" / "forecast.json").read_text()


def test_an_empty_data_root_is_refused(project) -> None:
  # Empty, it would fall back to the local disk silently.
  process = start(project, "--data-root=")
  output, _ = process.communicate(timeout=120)
  assert process.returncode == 1
  assert "--data-root" in output
