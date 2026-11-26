# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""A download's progress (`arco-ocean progress`), read from repositories committed as arco-make
commits a download: each block on the run's branch, its interval in the commit's metadata, `main`
moved to the run's last commit when it is complete."""

import datetime
import json
import pathlib

import icechunk
import numpy as np
import pytest
import xarray as xr
from arcomake import icechunk_utils
from click.testing import CliRunner

from arco_ocean import progress
from arco_ocean.cli import cli


class Run:
  """A run of arco-make's download into a local repository: its branch from `main`'s tip, a commit
  per block, `main` moved to its last commit when it finishes."""

  def __init__(self, path: pathlib.Path, command: str = "download") -> None:
    self.repo = icechunk.Repository.open_or_create(icechunk.local_filesystem_storage(str(path)))
    self.label = icechunk_utils.run_label(command)
    self.branch = f"run/{self.label}"
    self.repo.create_branch(self.branch, self.repo.lookup_branch("main"))

  def block(self, start: str, end: str) -> None:
    session = self.repo.writable_session(self.branch)
    xr.Dataset({"x": ("t", np.zeros(1))}).to_zarr(session.store, mode="w", consolidated=False)
    key = f"{start}T00:00/{end}T00:00"
    session.commit(
      f"download [{start}, {end})",
      metadata={icechunk_utils.RUN_KEY: self.label, icechunk_utils.BLOCK_KEY: key},
    )

  def finish(self) -> None:
    self.repo.reset_branch("main", self.repo.lookup_branch(self.branch))
    self.repo.delete_branch(self.branch)


def complete(path: pathlib.Path, *blocks: tuple[str, str]) -> None:
  """A run that stored `blocks` and finished."""
  run = Run(path)
  for block in blocks:
    run.block(*block)
  run.finish()


def follow(path: pathlib.Path, extension: bool = False) -> progress.ProgressState:
  """A download's state into the repository at `path`, as `start` makes it (read once)."""
  now = datetime.datetime.now(datetime.UTC)
  state = progress.ProgressState(
    name="n", state="running", started_at=now, updated_at=now, heartbeat_seconds=300,
    start=None if extension else datetime.date(1993, 1, 1), end=datetime.date(2026, 7, 1),
    done_until=None, last_commit_at=None, repository=str(path), extension=extension,
  )  # fmt: skip
  progress.refresh(state)
  return state


def stored_until(state: progress.ProgressState, finished: bool = False) -> datetime.date | None:
  progress.refresh(state, finished)
  assert state.error is None
  return state.done_until


def test_no_repository_no_progress(tmp_path) -> None:
  state = follow(tmp_path / "none")
  assert (state.ready, state.base, state.known, state.done_until) == (True, None, {}, None)


def test_the_newest_block_on_the_runs_branch_then_main(tmp_path) -> None:
  path = tmp_path / "repo"
  run = Run(path)
  state = follow(path)
  # The branch, without a commit of its own yet: nothing stored.
  assert stored_until(state) is None
  run.block("1993-01-01", "1993-02-02")
  run.block("1993-02-02", "1993-03-06")
  assert stored_until(state) == datetime.date(1993, 3, 6) and state.branch == run.branch
  assert state.last_commit_at is not None
  # Complete: main at the last block, the branch gone (a beat reading it then reads main).
  run.finish()
  assert stored_until(state) == datetime.date(1993, 3, 6)
  assert stored_until(state, finished=True) == datetime.date(1993, 3, 6)


def test_a_replace_beside_a_failed_run_is_its_own(tmp_path) -> None:
  path = tmp_path / "repo"
  complete(path, ("1993-01-01", "1993-02-02"))
  # A run failed with main where it started: arco-make's --replace starts a new branch beside it.
  failed = Run(path)
  failed.block("1993-01-01", "1997-03-14")
  state = follow(path)
  replace = Run(path)
  # Neither the failed run's blocks nor the output it replaces.
  assert stored_until(state) is None and state.branch == replace.branch
  replace.block("1993-01-01", "1993-01-15")
  assert stored_until(state) == datetime.date(1993, 1, 15)


def test_a_run_of_the_other_command_is_not_this_downloads(tmp_path) -> None:
  path = tmp_path / "repo"
  complete(path, ("1993-01-01", "1993-02-02"))
  state = follow(path)
  extension = Run(path, "download-extend")
  extension.block("1993-02-02", "1993-03-06")
  assert stored_until(state) is None and state.branch is None


def test_a_resumed_run_counts_from_its_next_block(tmp_path) -> None:
  path = tmp_path / "repo"
  failed = Run(path)
  failed.block("1993-01-01", "1993-02-02")
  state = follow(path)
  assert stored_until(state) is None
  # --resume continues the branch: its blocks so far count with its next.
  failed.block("1993-02-02", "1993-03-06")
  assert stored_until(state) == datetime.date(1993, 3, 6) and state.branch == failed.branch


def test_an_extension_counts_what_main_holds(tmp_path) -> None:
  path = tmp_path / "repo"
  complete(path, ("1993-01-01", "1993-02-02"))
  state = follow(path, extension=True)
  assert (state.start, state.done_until) == (datetime.date(1993, 2, 2),) * 2
  assert follow(path).done_until is None


def test_a_first_read_that_fails_is_made_again(tmp_path, monkeypatch) -> None:
  from arcomake import icechunk_utils

  path = tmp_path / "repo"
  complete(path, ("1993-01-01", "1993-02-02"))
  opened = icechunk_utils.existing_repository

  def unreachable(where: str):
    raise OSError(f"cannot reach {where}")

  monkeypatch.setattr(icechunk_utils, "existing_repository", unreachable)
  state = follow(path, extension=True)
  assert state.error == "the repository could not be read: OSError" and not state.ready
  monkeypatch.setattr(icechunk_utils, "existing_repository", opened)
  assert stored_until(state) == datetime.date(1993, 2, 2)
  assert state.ready and state.start == datetime.date(1993, 2, 2)


def invoke(state: pathlib.Path, published: pathlib.Path, *args: str):
  return CliRunner().invoke(
    cli, ["progress", "--state-file", str(state), "--publish", str(published), *args]
  )


def run(state: pathlib.Path, published: pathlib.Path, *args: str) -> dict:
  result = invoke(state, published, *args)
  assert result.exit_code == 0, result.output
  document = json.loads(published.read_text())
  progress.Progress.model_validate(document)
  return document


@pytest.fixture
def files(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
  return tmp_path / "logs" / "progress.json", tmp_path / "www" / "historical.json"


def test_a_download_from_start_to_end(tmp_path, files) -> None:
  state, published = files
  repo = tmp_path / "historical" / "res=0p25"
  document = run(
    state, published, "start", "--name", "historical_res-0p25", "--repo", str(repo),
    "--start", "1993-01-01", "--end", "2026-07-01",
  )  # fmt: skip
  assert document["state"] == "running" and document["name"] == "historical_res-0p25"
  assert document["start"] == "1993-01-01" and document["end"] == "2026-07-01"
  assert document["done_until"] is None
  # The repository's path and the run's identity are not published; the state file keeps them.
  assert set(document).isdisjoint(progress.PRIVATE)
  assert str(repo) not in published.read_text()
  kept = json.loads(state.read_text())
  assert kept["repository"] == str(repo) and kept["base"] is None and kept["extension"] is False

  download = Run(repo)
  download.block("1993-01-01", "1993-02-02")
  document = run(state, published, "beat")
  assert document["done_until"] == "1993-02-02" and document["last_commit_at"].endswith("Z")
  assert json.loads(state.read_text())["branch"] == download.branch
  download.block("1993-02-02", "1993-03-06")
  download.finish()
  document = run(state, published, "end", "finished")
  assert document["state"] == "finished" and document["ended_at"] is not None
  assert document["done_until"] == "1993-03-06"
  ended = published.read_text()
  # A late beat does not bring an ended download back to life.
  run(state, published, "beat")
  assert published.read_text() == ended


def test_an_extension_starts_where_main_ends(tmp_path, files) -> None:
  state, published = files
  repo = tmp_path / "repo"
  complete(repo, ("1993-01-01", "1993-02-02"))
  # A failed extension left blocks: the next one resumes it, and starts where main ends.
  failed = Run(repo, "download-extend")
  failed.block("1993-02-02", "1993-03-06")
  document = run(
    state, published, "start", "--name", "x_res-1p0", "--repo", str(repo), "--end", "1993-06-01"
  )
  # The failed extension's blocks count from its next.
  assert document["start"] == "1993-02-02" and document["done_until"] == "1993-02-02"
  failed.block("1993-03-06", "1993-04-07")
  assert run(state, published, "beat")["done_until"] == "1993-04-07"


def test_a_failed_download_and_an_unreadable_repository(tmp_path, files, monkeypatch) -> None:
  from arcomake import icechunk_utils

  state, published = files

  def unreadable(path: str):
    raise OSError(f"cannot reach {path}")

  monkeypatch.setattr(icechunk_utils, "existing_repository", unreadable)
  document = run(state, published, "start", "--name", "n", "--repo", "/x", "--end", "1993-06-01")
  # The error names no path.
  assert document["error"] == "the repository could not be read: OSError"
  document = run(state, published, "end", "failed", "--detail", "Killed.")
  assert document["state"] == "failed" and document["detail"] == "Killed."
  assert document["error"] == "the repository could not be read: OSError"


def test_steps_need_a_started_download(files) -> None:
  state, published = files
  result = invoke(state, published, "beat")
  assert result.exit_code == 1 and "no run started" in result.output
  result = invoke(state, published, "end", "running")
  assert result.exit_code == 2


def test_a_state_file_not_one_is_replaced_at_start(files) -> None:
  state, published = files
  state.parent.mkdir(parents=True)
  state.write_text('{"state": "running"}')
  result = invoke(state, published, "beat")
  assert result.exit_code == 1 and "is not a heartbeat's state" in result.output
  result = invoke(
    state, published, "start", "--name", "n", "--repo", "/nowhere", "--end", "1993-06-01"
  )
  assert result.exit_code == 0 and "a new one is written" in result.output


def test_the_schema_describes_the_published_document() -> None:
  result = CliRunner().invoke(cli, ["progress-schema"])
  assert result.exit_code == 0, result.output
  schema = json.loads(result.output)
  assert set(schema["properties"]).isdisjoint(progress.PRIVATE)
  assert set(schema["required"]) == set(schema["properties"])
  assert schema["properties"]["state"]["enum"] == ["running", "finished", "failed"]


def test_the_statistics_have_a_state_not_a_progress(tmp_path, files) -> None:
  state, published = files
  repo = tmp_path / "statistics" / "res=1p0"
  document = run(
    state, published, "start", "--kind", "statistics", "--name", "historical_res-1p0",
    "--repo", str(repo),
  )  # fmt: skip
  assert (document["kind"], document["state"]) == ("statistics", "running")
  assert (document["start"], document["end"], document["done_until"]) == (None, None, None)
  # Written in one commit at the end: nothing to read while they run.
  complete(repo, ("1993-01-01", "1993-02-02"))
  document = run(state, published, "beat")
  assert (document["done_until"], document["last_commit_at"]) == (None, None)
  document = run(state, published, "end", "finished")
  assert document["state"] == "finished" and document["last_commit_at"].endswith("Z")
  assert document["done_until"] is None


def test_the_kinds_take_their_dates(files) -> None:
  state, published = files
  result = invoke(state, published, "start", "--name", "n", "--repo", "/x")
  assert result.exit_code == 2 and "a download needs --end" in result.output
  result = invoke(
    state, published, "start", "--kind", "statistics", "--name", "n", "--repo", "/x",
    "--end", "1993-06-01",
  )  # fmt: skip
  assert result.exit_code == 2 and "the statistics take no --start nor --end" in result.output


def test_the_summary_for_an_issue(tmp_path, files) -> None:
  state, published = files
  run(
    state, published, "start", "--name", "historical_res-0p25", "--repo", str(tmp_path / "r"),
    "--start", "1993-01-01", "--end", "2026-07-01",
  )  # fmt: skip
  run(state, published, "end", "failed", "--detail", "Stopped (exit status 1) <b>@team</b>.")
  result = invoke(state, published, "summary")
  assert result.exit_code == 0, result.output
  assert result.output.startswith(r"**Download historical\_res-0p25: failed.** Stopped")
  # Inert in Markdown, and no path of the machine.
  assert "<b>" not in result.output and str(tmp_path) not in result.output
  assert (
    "- Period: 1993-01-01 to 2026-07-01 (excluded), stored up to: – (excluded)" in result.output
  )
  statistics = state.with_name("statistics.json")
  CliRunner().invoke(
    cli,
    ["progress", "--state-file", str(statistics), "start", "--kind", "statistics",
     "--name", "historical_res-1p0", "--repo", "/x"],
  )  # fmt: skip
  result = CliRunner().invoke(cli, ["progress", "--state-file", str(statistics), "summary"])
  assert result.output.startswith(r"**Statistics historical\_res-1p0: running.**")
  assert "Period" not in result.output
