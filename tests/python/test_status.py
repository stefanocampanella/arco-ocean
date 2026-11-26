# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The forecast collection's heartbeat (`arco-ocean status`), on a local forecast repository and
a local published file."""

import datetime
import json
import os
import pathlib
import re
import tomllib

import icechunk
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from click.testing import CliRunner

from arco_ocean import status
from arco_ocean.cli import cli

ROOT = pathlib.Path(__file__).parents[2]


def forecast_repository(path: pathlib.Path, runs: list[str], glo12: list[bool]) -> None:
  """A forecast repository as arco-make writes it: runs along init_time, 3 lead days, two flags
  (GLO12's given per lead day of the newest run) and a variable."""
  init = pd.to_datetime(runs).values
  lead = pd.to_timedelta([0, 1, 2], unit="D").values
  shape = (len(init), len(lead))
  glo12_flag = np.ones(shape, dtype=bool)
  glo12_flag[-1] = glo12
  dataset = xr.Dataset(
    {
      "thetao": (("init_time", "lead_time"), np.zeros(shape, dtype="float32")),
      "ifs_forecast": (("init_time", "lead_time"), np.ones(shape, dtype=bool)),
      "glo12_forecast": (("init_time", "lead_time"), glo12_flag),
      "lsm": ((), np.float32(0.5)),
    },
    coords={"init_time": init, "lead_time": lead},
  )
  repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))
  session = repo.writable_session("main")
  dataset.to_zarr(session.store, mode="w", consolidated=False)
  session.commit("forecast")


def invoke(state: pathlib.Path, *args: str, published: pathlib.Path | None = None):
  options = ["--state-file", str(state)]
  if published is not None:
    options += ["--publish", str(published)]
  return CliRunner().invoke(cli, ["status", *options, *args])


def run(state: pathlib.Path, published: pathlib.Path, *args: str) -> dict:
  result = invoke(state, *args, published=published)
  assert result.exit_code == 0, result.output
  document = json.loads(published.read_text())
  # Every published document is a valid heartbeat.
  status.Heartbeat.model_validate(document)
  return document


@pytest.fixture
def files(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
  return tmp_path / "logs" / "status.json", tmp_path / "www" / "forecast.json"


def test_a_collection_from_start_to_end(tmp_path, files) -> None:
  state, published = files
  repo = tmp_path / "forecast" / "res=1p0"
  forecast_repository(repo, ["2026-11-22", "2026-11-23"], [False, True, True])
  missing = tmp_path / "forecast" / "res=0p5"

  document = run(
    state, published, "start", "--target-run", "2026-11-24",
    "--repo", f"1p0={repo}", "--repo", f"0p5={missing}",
  )  # fmt: skip
  assert document["schema"] == 1
  assert document["state"] == "running"
  assert document["target_run"] == "2026-11-24"
  assert document["heartbeat_seconds"] == 300
  assert document["stale_after_hours"] == 30.0
  # Times in UTC, to the second, as the page reads them.
  assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", document["started_at"])
  # Local paths are not published; the state file keeps them.
  assert "repositories" not in document
  assert str(repo) not in published.read_text()
  assert json.loads(state.read_text())["repositories"]["1p0"] == str(repo)
  one, half = document["resolutions"]
  assert one["res"] == "1p0" and one["state"] == "pending"
  assert one["latest_run"] == "2026-11-23" and one["runs"] == 2
  # The share of the newest run's lead times that are its own forecast; `lsm`, `thetao` are no
  # flags.
  assert one["flags"] == {"ifs_forecast": 1.0, "glo12_forecast": pytest.approx(0.667)}
  assert half["latest_run"] is None and half["runs"] is None and half["flags"] == {}

  document = run(state, published, "res", "1p0", "downloading")
  assert document["resolutions"][0]["state"] == "downloading"
  assert document["resolutions"][0]["started_at"] is not None

  # The run of the 24th is stored by the download.
  forecast_repository(
    tmp_path / "next", ["2026-11-22", "2026-11-23", "2026-11-24"], [True, True, True]
  )
  repo.rename(tmp_path / "old")
  (tmp_path / "next").rename(repo)
  document = run(state, published, "res", "1p0", "finished")
  assert document["resolutions"][0]["state"] == "finished"
  assert document["resolutions"][0]["latest_run"] == "2026-11-24"
  assert document["resolutions"][0]["runs"] == 3
  assert document["resolutions"][0]["flags"]["glo12_forecast"] == 1.0

  document = run(state, published, "beat")
  assert document["state"] == "running"

  document = run(state, published, "end", "finished")
  assert document["state"] == "finished"
  assert document["ended_at"] is not None
  ended = published.read_text()

  # A late beat does not bring an ended collection back to life.
  run(state, published, "beat")
  assert published.read_text() == ended


def test_an_aborted_collection_fails_the_resolution_downloading(files) -> None:
  state, published = files
  run(state, published, "start", "--target-run", "2026-11-24", "--repo", "1p0=/nowhere")
  run(state, published, "res", "1p0", "downloading")
  document = run(state, published, "end", "aborted", "--detail", "Killed.")
  assert document["state"] == "aborted"
  assert document["detail"] == "Killed."
  assert document["resolutions"][0]["state"] == "failed"


def test_only_an_aborted_collection_fails_the_resolution_downloading(files) -> None:
  state, published = files
  run(state, published, "start", "--target-run", "2026-11-24", "--repo", "1p0=/nowhere")
  run(state, published, "res", "1p0", "downloading")
  document = run(state, published, "end", "finished")
  assert document["resolutions"][0]["state"] == "downloading"


def test_a_new_collection_keeps_the_newest_runs_known(tmp_path, files, monkeypatch) -> None:
  state, published = files
  repo = tmp_path / "res=1p0"
  forecast_repository(repo, ["2026-11-23"], [True, True, True])
  run(state, published, "start", "--target-run", "2026-11-23", "--repo", f"1p0={repo}")
  run(state, published, "end", "finished")

  # The repository cannot be read at the next start (S3 down, say): what was known stays, with
  # the error, which names no path.
  def unreadable(path: str) -> dict:
    raise OSError(f"cannot reach {path}")

  monkeypatch.setattr(status, "repository_summary", unreadable)
  document = run(state, published, "start", "--target-run", "2026-11-24", "--repo", f"1p0={repo}")
  entry = document["resolutions"][0]
  assert entry["latest_run"] == "2026-11-23"
  assert entry["error"] is not None and str(repo) not in entry["error"]
  assert document["state"] == "running" and document["ended_at"] is None


def test_the_settings_apply_before_the_repositories_are_read(tmp_path, files, monkeypatch) -> None:
  # The units run without the shell's environment: the AWS profile of ~/.arcomakerc must reach
  # the reads of repositories in the bucket, not only the upload (25 Nov).
  state, published = files
  rc = tmp_path / "arcomakerc"
  rc.write_text("AWS_PROFILE=probe-profile\n")
  rc.chmod(0o600)
  monkeypatch.setenv("ARCOMAKE_RC", str(rc))
  monkeypatch.delenv("AWS_PROFILE", raising=False)
  monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
  seen = []

  def summary(path: str) -> dict:
    seen.append(os.environ.get("AWS_PROFILE"))
    return status.RepositorySummary()

  monkeypatch.setattr(status, "repository_summary", summary)
  run(state, published, "start", "--target-run", "2026-11-24", "--repo", "1p0=s3://bucket/x")
  assert seen == ["probe-profile"]


def test_steps_need_a_started_collection(files) -> None:
  state, published = files
  result = invoke(state, "beat")
  assert result.exit_code == 1 and "no collection started" in result.output
  run(state, published, "start", "--target-run", "2026-11-24", "--repo", "1p0=/nowhere")
  result = invoke(state, "res", "0p25", "finished")
  assert result.exit_code == 1 and "unknown resolution" in result.output


@pytest.mark.parametrize(
  "args",
  [
    ["start", "--target-run", "2026-11-24", "--repo", "1p0"],
    ["start", "--target-run", "24 Nov 2026"],
    ["res", "1p0", "done"],
    ["end", "running"],
  ],
)
def test_wrong_arguments_are_refused(files, args) -> None:
  state, _ = files
  result = invoke(state, *args)
  assert result.exit_code == 2, result.output
  assert not state.exists()


def test_a_resolution_waits_from_its_first_collection_not_published(files) -> None:
  state, published = files

  def collection(target: str, outcome: str) -> dict:
    run(state, published, "start", "--target-run", target, "--repo", "1p0=/nowhere")
    run(state, published, "res", "1p0", "downloading")
    run(state, published, "res", "1p0", outcome)
    return run(state, published, "end", "finished")["resolutions"][0]

  first = collection("2026-11-22", "not_published")
  assert first["waiting_since"] is not None
  # Still waiting the next day: since the first; a failure changes nothing; stored, it stops.
  assert collection("2026-11-23", "not_published")["waiting_since"] == first["waiting_since"]
  assert collection("2026-11-24", "failed")["waiting_since"] == first["waiting_since"]
  assert collection("2026-11-25", "finished")["waiting_since"] is None


def test_a_state_file_of_the_script_before_is_read(files) -> None:
  # scripts/forecast_status.py wrote the same document (until 26 Nov 2026): a collection it
  # started goes on with the package.
  state, published = files
  state.parent.mkdir(parents=True)
  state.write_text(
    json.dumps(
      {
        "schema": 1, "state": "running", "detail": None,
        "started_at": "2026-11-25T12:00:03Z", "updated_at": "2026-11-25T12:05:03Z",
        "ended_at": None, "heartbeat_seconds": 300, "stale_after_hours": 30.0,
        "missing_after_days": 2.0, "target_run": "2026-11-25",
        "resolutions": [
          {
            "res": "1p0", "state": "downloading", "started_at": "2026-11-25T12:00:04Z",
            "ended_at": None, "latest_run": "2026-11-24", "runs": 3,
            "flags": {"ifs_forecast": 1.0}, "waiting_since": None, "error": None,
          }
        ],
        "repositories": {"1p0": "/nowhere"},
      }
    )
  )  # fmt: skip
  document = run(state, published, "end", "finished")
  assert document["started_at"] == "2026-11-25T12:00:03Z"
  assert document["resolutions"][0]["latest_run"] == "2026-11-24"


def test_the_schema_describes_the_published_document() -> None:
  result = CliRunner().invoke(cli, ["heartbeat-schema"])
  assert result.exit_code == 0, result.output
  schema = json.loads(result.output)
  assert "schema" in schema["properties"] and "repositories" not in schema["properties"]
  assert schema["$defs"]["Resolution"]["properties"]["state"]["enum"] == [
    "pending", "downloading", "finished", "not_published", "failed",
  ]  # fmt: skip


def test_the_published_missing_after_is_the_recipes(files) -> None:
  # The page judges lags and waits by it: forecast.sh's default must be the recipes' value.
  script = (ROOT / "scripts" / "forecast.sh").read_text()
  match = re.search(r"^MISSING_AFTER=([0-9.]+)$", script, re.MULTILINE)
  assert match is not None
  default = float(match.group(1))
  recipes = sorted((ROOT / "configs" / "download").glob("forecast_res-*.toml"))
  assert recipes
  for recipe in recipes:
    value = tomllib.loads(recipe.read_text())["forecast"]["missing_after"]
    assert pd.to_timedelta(value) == pd.Timedelta(days=default), recipe.name
  state, published = files
  document = run(
    state, published, "start", "--target-run", "2026-11-24", "--missing-after-days", "2"
  )
  assert document["missing_after_days"] == 2.0


NOW = datetime.datetime(2026, 11, 24, 13, 0, tzinfo=datetime.UTC)


def finished(latest: str | None, **fields) -> status.Heartbeat:
  """A collection that finished at 12:20 on 24 Nov 2026, 0.25° with its newest run `latest`
  (the same cases as the page's tests, tests/js/forecast.test.js)."""
  document = {
    "schema": 1,
    "state": "finished",
    "started_at": "2026-11-24T12:00:00Z",
    "updated_at": "2026-11-24T12:20:00Z",
    "ended_at": "2026-11-24T12:20:00Z",
    "heartbeat_seconds": 300,
    "stale_after_hours": 30.0,
    "missing_after_days": 2.0,
    "target_run": "2026-11-24",
    "resolutions": [
      {"res": "0p25", "state": "not_published", "latest_run": latest, "runs": 147},
      {"res": "1p0", "state": "finished", "latest_run": "2026-11-24", "runs": 147},
    ],
  }
  return status.Heartbeat.model_validate(document | fields)


def test_behind_as_the_page_judges_it() -> None:
  # Two days behind: runs younger than missing_after may wait for their sources.
  assert status.behind(finished("2026-11-22"), NOW) == []
  assert status.behind(finished("2026-11-21"), NOW) == [
    "0.25°'s newest run is 2026-11-21, 3 days before the newest"
  ]
  # The heartbeat's missing_after decides.
  assert status.behind(finished("2026-11-21", missing_after_days=3), NOW) == []
  assert status.behind(finished("2026-11-22", missing_after_days=1), NOW) != []
  # A repository without runs (missing, or unreadable) is behind too.
  assert status.behind(finished(None), NOW) == ["0.25° has no run stored"]


def test_a_resolution_waiting_longer_than_missing_after_is_behind() -> None:
  # A source that stopped: its older runs are stored without it, so the lag stays at two days,
  # but the resolution waits every day.
  waiting = finished("2026-11-22")
  waiting.resolutions[0].waiting_since = datetime.datetime(
    2026, 11, 22, 13, 30, tzinfo=datetime.UTC
  )
  assert status.behind(waiting, NOW) == []
  assert status.behind(waiting, NOW + datetime.timedelta(hours=1)) == [
    "0.25° has waited for a source for 2 d"
  ]


def test_overdue_fails_only_a_collection_finished_behind(files) -> None:
  state, _ = files
  state.parent.mkdir(parents=True)
  for document, code in (
    (finished("2026-11-24"), 0),
    (finished("2026-11-21"), status.BEHIND_EXIT),
    # Aborted, a collection fails by itself (forecast.sh exits 1).
    (finished("2026-11-21", state="aborted"), 0),
  ):
    state.write_text(document.model_dump_json(by_alias=True))
    result = invoke(state, "overdue")
    assert result.exit_code == code, result.output
  state.write_text(finished("2026-11-21").model_dump_json(by_alias=True))
  assert "finished behind: 0.25°'s newest run is 2026-11-21" in invoke(state, "overdue").output


def test_the_summary_shows_the_public_content_inert(files) -> None:
  state, _ = files
  state.parent.mkdir(parents=True)
  document = status.State.model_validate(
    finished("2026-11-24", detail="Late <b>@someone</b> #12 `x` | y").model_dump(by_alias=True)
    | {"repositories": {"0p25": "/data/private/path"}}
  )
  document.resolutions[0].error = "the repository could not be read: OSError"
  state.write_text(document.model_dump_json(by_alias=True))
  result = invoke(state, "summary")
  assert result.exit_code == 0, result.output
  text = result.output
  assert text.startswith("**Collection finished.** Late &lt;b&gt;@⁠someone&lt;/b&gt; #⁠12")
  assert "'x' \\| y" in text
  assert "- Started: 2026-11-24 12:00 UTC, last heartbeat: 2026-11-24 12:20 UTC" in text
  assert (
    "| 0.25° | not\\_published | 2026-11-24 | 147 | the repository could not be read: OSError |"
    in text
  )
  # The repositories' paths are not public.
  assert "/data/private" not in text
  assert invoke(state.with_name("none.json"), "summary").exit_code == 1


def test_durations_as_the_page_writes_them() -> None:
  minutes = datetime.timedelta(minutes=1)
  assert status.duration(3 * minutes) == "3 min"
  assert status.duration(125 * minutes) == "2 h 5 min"
  assert status.duration(27 * 60 * minutes) == "1 d 3 h"
  assert status.duration(48 * 60 * minutes) == "2 d"
  assert status.duration(-minutes) == "0 min"


def test_a_state_file_not_a_heartbeats_is_replaced_at_start(files) -> None:
  # Another version's, or damaged: every step would fail on it until removed by hand.
  state, published = files
  state.parent.mkdir(parents=True)
  state.write_text('{"schema": 1, "state": "running", "new_key": true}')
  result = invoke(state, "beat")
  assert result.exit_code == 1 and "is not a heartbeat's state" in result.output
  result = invoke(state, "start", "--target-run", "2026-11-24", published=published)
  assert result.exit_code == 0, result.output
  assert "a new one is written" in result.output
  assert run(state, published, "beat")["state"] == "running"


def test_a_run_without_lead_times_has_no_flag_share(tmp_path, files) -> None:
  # The mean of no lead times is NaN, which JSON writes as null: no flag's value.
  repo = tmp_path / "res=1p0"
  forecast_repository(repo, ["2026-11-23"], [True, True, True])
  stored = status.repository_summary(str(repo))
  assert stored.flags["ifs_forecast"] == 1.0
  dataset = xr.Dataset(
    {"ifs_forecast": (("init_time", "lead_time"), np.full((1, 3), np.nan) > 0)},
    coords={"init_time": pd.to_datetime(["2026-11-23"]).values, "lead_time": [0, 1, 2]},
  )
  empty = tmp_path / "empty"
  storage = icechunk.Repository.create(icechunk.local_filesystem_storage(str(empty)))
  session = storage.writable_session("main")
  dataset.isel(lead_time=slice(0, 0)).to_zarr(session.store, mode="w", consolidated=False)
  session.commit("no lead times")
  summary = status.repository_summary(str(empty))
  assert summary.latest_run == datetime.date(2026, 11, 23) and summary.flags == {}
  state, published = files
  run(state, published, "start", "--target-run", "2026-11-24", "--repo", f"1p0={empty}")
  assert run(state, published, "beat")["resolutions"][0]["flags"] == {}


def test_the_schema_requires_every_key_and_utc_times() -> None:
  schema = status.Heartbeat.model_json_schema(by_alias=True, mode="serialization")
  assert set(schema["required"]) == set(schema["properties"])
  resolution = schema["$defs"]["Resolution"]
  assert set(resolution["required"]) == set(resolution["properties"])
  assert schema["properties"]["updated_at"]["pattern"].endswith("Z$")


def test_plain_text_is_inert_markdown() -> None:
  assert (
    status.plain("a\\| [x](y) *b* _c_ ~d~ !e")
    == "a\\\\\\| \\[x\\]\\(y\\) \\*b\\* \\_c\\_ \\~d\\~ \\!e"
  )
  assert status.plain(None) == "–"
  assert status.plain("two\n lines") == "two lines"
