# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""A download's progress: a JSON document that the ARCO-OCEAN web page reads, for a download run
once (the historical dataset's), as the forecast collection's heartbeat is for daily ones.

`scripts/download.sh --status-url URL` runs `arco-ocean progress` when the download starts, every
few minutes while it runs (a beat), and when it ends. Each call reads the progress from the
repository itself: arco-make commits each block of a download on the run's branch, the block's
interval in the commit's metadata (`arcomake_block`), and moves `main` to the run's last commit
when the run is complete. The newest block committed tells how far the download is, its commit
when. A download killed without notice stops beating: the page calls it stale.

The document is `Progress` (`arco-ocean progress-schema` prints its JSON Schema); the state
file, `ProgressState`, also holds the repository's path or URL, which is not published.
"""

import datetime
import json
import pathlib
from collections.abc import Callable
from typing import Literal, get_args

import click
from pydantic import BaseModel, Field

from arco_ocean.status import (
  MODEL_CONFIG,
  Files,
  Time,
  apply_settings,
  load_model,
  locked,
  now,
  pass_files,
  publish,
  write_atomically,
)

DownloadState = Literal["running", "finished", "failed"]
# The commands of arco-make's download runs (their branches: run/<command>-<time>).
COMMANDS = ("download", "download-extend")


class Reading(BaseModel):
  """What the repository tells of a download: the end of the newest block committed (on the
  run's branch while it runs, on `main` once it is complete), the blocks the run committed, and
  when the newest was."""

  done_until: datetime.date | None = None
  blocks: int = 0
  last_commit_at: Time | None = None


class Progress(BaseModel):
  """The published document."""

  model_config = MODEL_CONFIG | {"populate_by_name": True}

  schema_version: Literal[1] = Field(1, alias="schema")
  name: str = Field(description='The recipe: "historical_res-0p25"')
  state: DownloadState
  detail: str | None = None
  started_at: Time
  updated_at: Time = Field(description="The heartbeat: the last update")
  ended_at: Time | None = None
  heartbeat_seconds: int
  start: datetime.date | None = Field(description="The first day downloaded (unknown: none)")
  end: datetime.date = Field(description="The day after the last")
  done_until: datetime.date | None = Field(description="The end of the newest block committed")
  blocks: int = Field(description="The blocks this download committed")
  last_commit_at: Time | None = Field(description="When the newest block was committed")
  error: str | None = Field(None, description="Why the repository could not be read")


class ProgressState(Progress):
  """The state file: the document, and where the repository is."""

  repository: str

  def public(self) -> str:
    shown = self.model_dump(mode="json", by_alias=True, exclude={"repository"})
    return json.dumps(shown, indent=2) + "\n"


def block_end(key: object) -> datetime.date | None:
  """The end of a block named as arco-make names it ("1993-01-01T00:00/1993-02-02T00:00")."""
  # The module: `arcomake.download` is also the name of its click command.
  from arcomake.download import block_end as arcomake_block_end

  end = arcomake_block_end(str(key))
  return None if end is None else end.date()


def read_progress(path: str) -> Reading:
  """The download's progress in the repository at `path` (local or s3://)."""
  from arcomake import icechunk_utils

  repo = icechunk_utils.existing_repository(path)
  if repo is None:
    return Reading()
  run = icechunk_utils.waiting_run(repo, *COMMANDS)
  if run is not None and run.blocks:
    tip = next(iter(repo.ancestry(branch=run.branch)))
    return Reading(
      done_until=block_end(run.blocks[-1]), blocks=len(run.blocks), last_commit_at=tip.written_at
    )
  # No run's branch with blocks: the run is complete (`main` at its last block), or has not
  # committed one yet.
  tip = next(iter(repo.ancestry(branch=icechunk_utils.BRANCH)))
  key = (tip.metadata or {}).get(icechunk_utils.BLOCK_KEY)
  if key is None:
    return Reading()
  return Reading(done_until=block_end(key), last_commit_at=tip.written_at)


def refresh(state: ProgressState) -> None:
  """Read the progress again into `state`; a failure is recorded, not raised: the heartbeat never
  stops a download."""
  try:
    reading = read_progress(state.repository)
  except Exception as error:  # noqa: BLE001 (reported in the document)
    state.error = f"the repository could not be read: {type(error).__name__}"
    return
  state.done_until = reading.done_until
  state.last_commit_at = reading.last_commit_at
  # The blocks of this run: a finished run's are counted while it ran (its branch is gone).
  state.blocks = reading.blocks or state.blocks
  state.error = None


def update(
  files: Files,
  change: Callable[[ProgressState | None], ProgressState | None],
  fresh: bool = False,
) -> None:
  """Apply `change` to the state file, under its lock, then publish the document. `fresh`: a
  download starts, and replaces a state file that is not one (`status.load_model`)."""
  # Before any read: the repository may be in the bucket.
  apply_settings()
  with locked(files.state_file):
    state = change(load_model(ProgressState, files.state_file, fresh))
    if state is None:
      return
    state.updated_at = now()
    write_atomically(files.state_file, state.model_dump_json(indent=2, by_alias=True) + "\n")
    if files.publish is not None:
      publish(files.publish, state.public())


def started(state: ProgressState | None, files: Files) -> ProgressState:
  if state is None:
    raise click.ClickException(f"no download started: {files.state_file} is missing")
  return state


@click.group()
@click.option(
  "--state-file", type=click.Path(path_type=pathlib.Path), required=True, help="The state file."
)
@click.option("--publish", help="s3:// URL or local path of the published document.")
@click.pass_context
def progress(context: click.Context, state_file: pathlib.Path, publish: str | None) -> None:
  """A download's progress (scripts/download.sh --status-url)."""
  context.obj = Files(state_file, publish)


@progress.command()
@click.option("--name", required=True, help="The recipe's name.")
@click.option("--repo", "repository", required=True, help="The output repository.")
@click.option("--start", type=click.DateTime(["%Y-%m-%d"]), help="The first day (YYYY-MM-DD).")
@click.option(
  "--end", type=click.DateTime(["%Y-%m-%d"]), required=True, help="The day after the last."
)
@click.option("--heartbeat-seconds", type=int, default=300, show_default=True)
@pass_files
def start(
  files: Files,
  name: str,
  repository: str,
  start: datetime.datetime | None,
  end: datetime.datetime,
  heartbeat_seconds: int,
) -> None:
  """A download starts. Without --start (an extension), the first day is where the repository
  ends now."""

  def change(_: ProgressState | None) -> ProgressState:
    state = ProgressState(
      name=name,
      state="running",
      started_at=now(),
      updated_at=now(),
      heartbeat_seconds=heartbeat_seconds,
      start=start.date() if start else None,
      end=end.date(),
      done_until=None,
      blocks=0,
      last_commit_at=None,
      repository=repository,
    )
    refresh(state)
    if state.start is None:
      state.start = state.done_until
    return state

  update(files, change, fresh=True)


@progress.command()
@pass_files
def beat(files: Files) -> None:
  """The download is still running."""

  def change(state: ProgressState | None) -> ProgressState | None:
    state = started(state, files)
    # A late beat of an ended download would make it look as if it were running again.
    if state.state != "running":
      return None
    refresh(state)
    return state

  update(files, change)


@progress.command()
@click.argument(
  "new_state",
  metavar="STATE",
  type=click.Choice([state for state in get_args(DownloadState) if state != "running"]),
)
@click.option("--detail", help="What the page shows next to the state.")
@pass_files
def end(files: Files, new_state: DownloadState, detail: str | None) -> None:
  """The download ends."""

  def change(state: ProgressState | None) -> ProgressState:
    state = started(state, files)
    refresh(state)
    state.state = new_state
    state.detail = detail
    state.ended_at = now()
    return state

  update(files, change)


def json_schema() -> str:
  """The published document's JSON Schema."""
  return json.dumps(Progress.model_json_schema(by_alias=True, mode="serialization"), indent=2)
