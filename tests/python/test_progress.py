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


class Download:
  """A download into a local repository, written block by block as arco-make writes one."""

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
    tip = self.repo.lookup_branch(self.branch)
    self.repo.reset_branch("main", tip)
    self.repo.delete_branch(self.branch)


def test_no_repository_no_progress(tmp_path) -> None:
  assert progress.read_progress(str(tmp_path / "none")) == progress.Reading()


def test_the_newest_block_on_the_runs_branch(tmp_path) -> None:
  download = Download(tmp_path / "repo")
  assert progress.read_progress(str(tmp_path / "repo")) == progress.Reading()
  download.block("1993-01-01", "1993-02-02")
  download.block("1993-02-02", "1993-03-06")
  reading = progress.read_progress(str(tmp_path / "repo"))
  assert reading.done_until == datetime.date(1993, 3, 6) and reading.blocks == 2
  assert reading.last_commit_at is not None
  # Complete: main at the last block, the branch gone.
  download.finish()
  reading = progress.read_progress(str(tmp_path / "repo"))
  assert reading.done_until == datetime.date(1993, 3, 6) and reading.blocks == 0


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
  assert document["done_until"] is None and document["blocks"] == 0
  # The repository's path is not published; the state file keeps it.
  assert "repository" not in document and str(repo) not in published.read_text()
  assert json.loads(state.read_text())["repository"] == str(repo)

  download = Download(repo)
  download.block("1993-01-01", "1993-02-02")
  document = run(state, published, "beat")
  assert document["done_until"] == "1993-02-02" and document["blocks"] == 1
  assert document["last_commit_at"].endswith("Z")
  download.block("1993-02-02", "1993-03-06")
  download.finish()
  document = run(state, published, "end", "finished")
  assert document["state"] == "finished" and document["ended_at"] is not None
  # The run's branch is gone: its blocks were counted while it ran.
  assert document["done_until"] == "1993-03-06" and document["blocks"] == 1
  ended = published.read_text()
  # A late beat does not bring an ended download back to life.
  run(state, published, "beat")
  assert published.read_text() == ended


def test_an_extension_starts_where_the_repository_ends(tmp_path, files) -> None:
  state, published = files
  repo = tmp_path / "repo"
  first = Download(repo)
  first.block("1993-01-01", "1993-02-02")
  first.finish()
  document = run(
    state, published, "start", "--name", "x_res-1p0", "--repo", str(repo), "--end", "1993-06-01"
  )
  assert document["start"] == "1993-02-02" and document["done_until"] == "1993-02-02"
  extension = Download(repo, "download-extend")
  extension.block("1993-02-02", "1993-03-06")
  assert run(state, published, "beat")["done_until"] == "1993-03-06"


def test_a_failed_download_and_an_unreadable_repository(tmp_path, files, monkeypatch) -> None:
  state, published = files
  run(state, published, "start", "--name", "n", "--repo", "/nowhere", "--end", "1993-06-01")

  def unreadable(path: str) -> progress.Reading:
    raise OSError(f"cannot reach {path}")

  monkeypatch.setattr(progress, "read_progress", unreadable)
  document = run(state, published, "end", "failed", "--detail", "Killed.")
  assert document["state"] == "failed" and document["detail"] == "Killed."
  # The error names no path.
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
  assert "repository" not in schema["properties"]
  assert set(schema["required"]) == set(schema["properties"])
  assert schema["properties"]["state"]["enum"] == ["running", "finished", "failed"]
