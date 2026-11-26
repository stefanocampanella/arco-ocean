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


def read(path: pathlib.Path, extension: bool = False, **options) -> progress.Reading:
  """The progress of a download that starts now (`main` read first), after `options`' runs."""
  main = progress.read_main(str(path))
  return progress.read_progress(str(path), base=main.base, extension=extension, branch=None)


def test_no_repository_no_progress(tmp_path) -> None:
  assert progress.read_main(str(tmp_path / "none")) == progress.Main()
  reading = progress.read_progress(str(tmp_path / "none"), base=None, extension=False, branch=None)
  assert reading == progress.Reading()


def test_the_newest_block_on_the_runs_branch_then_main(tmp_path) -> None:
  path = tmp_path / "repo"
  run = Run(path)
  main = progress.read_main(str(path))

  def reading(finished: bool = False, branch: str | None = None) -> progress.Reading:
    return progress.read_progress(
      str(path), base=main.base, extension=False, branch=branch, finished=finished
    )

  # The branch, without a commit of its own yet: nothing stored.
  assert reading().done_until is None
  run.block("1993-01-01", "1993-02-02")
  run.block("1993-02-02", "1993-03-06")
  first = reading()
  assert first.done_until == datetime.date(1993, 3, 6) and first.branch == run.branch
  assert first.last_commit_at is not None
  # Once found, the branch is read by its tip.
  assert reading(branch=run.branch) == first
  # Complete: main at the last block, the branch gone.
  run.finish()
  assert reading(branch=run.branch).done_until == datetime.date(1993, 3, 6)
  assert reading(finished=True).done_until == datetime.date(1993, 3, 6)


def test_a_branch_main_has_moved_past_is_not_this_downloads(tmp_path) -> None:
  path = tmp_path / "repo"
  # A run failed (its branch left), then another replaced the output.
  failed = Run(path)
  failed.block("1993-01-01", "1997-03-14")
  complete(path, ("1993-01-01", "1993-02-02"))
  # A new download, with --replace: neither the failed run's blocks nor the output it replaces.
  main = progress.read_main(str(path))
  run = Run(path)
  options = {"base": main.base, "extension": False}
  before = progress.read_progress(str(path), branch=None, **options)
  assert (before.done_until, before.last_commit_at) == (None, None)
  run.block("1993-01-01", "1993-01-15")
  reading = progress.read_progress(str(path), branch=None, **options)
  assert (reading.done_until, reading.branch) == (datetime.date(1993, 1, 15), run.branch)


def test_a_resumed_run_is_this_downloads(tmp_path) -> None:
  path = tmp_path / "repo"
  failed = Run(path)
  failed.block("1993-01-01", "1993-02-02")
  # --resume continues the branch: its blocks so far count.
  reading = read(path)
  assert (reading.done_until, reading.branch) == (datetime.date(1993, 2, 2), failed.branch)


def test_an_extension_counts_what_main_holds(tmp_path) -> None:
  path = tmp_path / "repo"
  complete(path, ("1993-01-01", "1993-02-02"))
  assert read(path, extension=True).done_until == datetime.date(1993, 2, 2)
  assert read(path).done_until is None


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
  assert document["start"] == "1993-02-02" and document["done_until"] == "1993-03-06"
  failed.block("1993-03-06", "1993-04-07")
  assert run(state, published, "beat")["done_until"] == "1993-04-07"


def test_a_failed_download_and_an_unreadable_repository(tmp_path, files, monkeypatch) -> None:
  state, published = files

  def unreadable(path: str, **_) -> progress.Reading:
    raise OSError(f"cannot reach {path}")

  monkeypatch.setattr(progress, "read_main", unreadable)
  document = run(state, published, "start", "--name", "n", "--repo", "/x", "--end", "1993-06-01")
  # The error names no path.
  assert document["error"] == "the repository could not be read: OSError"
  monkeypatch.setattr(progress, "read_progress", unreadable)
  document = run(state, published, "end", "failed", "--detail", "Killed.")
  assert document["state"] == "failed" and document["detail"] == "Killed."
  assert document["error"] == "the repository could not be read: OSError"


def test_steps_need_a_started_download(files) -> None:
  state, published = files
  result = invoke(state, published, "beat")
  assert result.exit_code == 1 and "no download started" in result.output
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
