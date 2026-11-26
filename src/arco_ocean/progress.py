# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""A download's progress: a JSON document that the ARCO-OCEAN web page reads, for a download run
once (the historical dataset's), as the forecast collection's heartbeat is for daily ones.

`scripts/download.sh --status-url URL` runs `arco-ocean progress` when the download starts, every
few minutes while it runs (a beat), and when it ends. Each call reads the progress from the
repository itself, as arco-make records it: each block of a download is a commit on the run's
branch (`run/<label>`, each commit's `arcomake_run` the label), the block's interval in the
commit's metadata (`arcomake_block`), and `main` moves to the run's last commit when the run is
complete. The newest block committed tells how far the download is, its commit when. A download
killed without notice stops beating: the page calls it stale.

Which run is this download's: one whose branch started from `main` as it was when the download
started (recorded then), a run resumed included; a branch of an earlier run that `main` has moved
past since is not. Before its first block, nothing is stored by the download, unless it extends
the repository (then what `main` holds counts); a download that replaces an output does not show
the old one's end. Once the run's branch is known, a beat reads only its tip.

The document is `Progress` (`arco-ocean progress-schema` prints its JSON Schema); the state
file, `ProgressState`, also holds the repository's path or URL and what identifies the run, which
are not published.
"""

import dataclasses
import datetime
import json
import pathlib
from typing import Any, Literal, get_args

import click
from pydantic import BaseModel, Field

from arco_ocean.status import (
  MODEL_CONFIG,
  Files,
  Time,
  load_model,
  now,
  pass_files,
  require_started,
  update_state,
)

DownloadState = Literal["running", "finished", "failed"]
# The commands of arco-make's download runs (their branches: run/<command>-<time>).
COMMANDS = ("download", "download-extend")


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
  done_until: datetime.date | None = Field(description="The end of the newest block stored")
  last_commit_at: Time | None = Field(description="When the newest block was committed")
  error: str | None = Field(None, description="Why the repository could not be read")


PRIVATE = {"repository", "base", "extension", "branch"}


class ProgressState(Progress):
  """The state file: the document, where the repository is, and what identifies the run."""

  repository: str
  base: str | None = Field(description="main's tip when the download started (no repository: none)")
  extension: bool = Field(description="Whether the download extends the repository")
  branch: str | None = Field(None, description="The run's branch, once found")

  def public(self) -> str:
    shown = self.model_dump(mode="json", by_alias=True, exclude=PRIVATE)
    return json.dumps(shown, indent=2) + "\n"


def block_end(key: object) -> datetime.date | None:
  """The end of a block named as arco-make names it ("1993-01-01T00:00/1993-02-02T00:00")."""
  # The module: `arcomake.download` is also the name of its click command.
  from arcomake.download import block_end as arcomake_block_end

  end = arcomake_block_end(str(key)) if key is not None else None
  return None if end is None else end.date()


@dataclasses.dataclass(frozen=True)
class Reading:
  """What the repository tells of a download: the end of the newest block it stored, when that
  was committed, and the run's branch, if found."""

  done_until: datetime.date | None = None
  last_commit_at: datetime.datetime | None = None
  branch: str | None = None


def tip(repo: Any, branch: str) -> Any:
  """The commit a branch points to (its snapshot's information)."""
  return next(iter(repo.ancestry(branch=branch)))


def stored(snapshot: Any) -> Reading:
  """The block a commit records, if any."""
  from arcomake import icechunk_utils

  end = block_end((snapshot.metadata or {}).get(icechunk_utils.BLOCK_KEY))
  return Reading(end, snapshot.written_at) if end is not None else Reading()


@dataclasses.dataclass(frozen=True)
class Main:
  """`main` when a download starts: its tip (none without a repository) and its block."""

  base: str | None = None
  stored: Reading = Reading()


def read_main(path: str) -> Main:
  from arcomake import icechunk_utils

  repo = icechunk_utils.existing_repository(path)
  if repo is None:
    return Main()
  snapshot = tip(repo, icechunk_utils.BRANCH)
  return Main(str(snapshot.id), stored(snapshot))


def read_progress(
  path: str, *, base: str | None, extension: bool, branch: str | None, finished: bool = False
) -> Reading:
  """The progress of the download that started with `main` at `base`, in the repository at
  `path` (local or s3://); `branch`, its run's branch if already found. `finished`: the run is
  complete, `main` holds it."""
  from arcomake import icechunk_utils

  repo = icechunk_utils.existing_repository(path)
  if repo is None:
    return Reading()
  if branch is None and not finished:
    run = icechunk_utils.waiting_run(repo, *COMMANDS)
    if run is not None and run.current and (base is None or run.base == base):
      branch = run.branch
  if branch is not None and not finished and branch in repo.list_branches():
    snapshot = tip(repo, branch)
    # The run's own commit: a branch without one yet points to `main`'s.
    label = branch.removeprefix("run/")
    if (snapshot.metadata or {}).get(icechunk_utils.RUN_KEY) == label:
      reading = stored(snapshot)
      if reading.done_until is not None:
        return dataclasses.replace(reading, branch=branch)
  snapshot = tip(repo, icechunk_utils.BRANCH)
  # `main` counts once the run moved it (or the run is complete), or for an extension.
  if finished or extension or str(snapshot.id) != base:
    return dataclasses.replace(stored(snapshot), branch=branch)
  return Reading(branch=branch)


def failure(error: Exception) -> str:
  return f"the repository could not be read: {type(error).__name__}"


def refresh(state: ProgressState, finished: bool = False) -> None:
  """Read the progress again into `state`; a failure is recorded, not raised: the progress never
  stops a download."""
  try:
    reading = read_progress(
      state.repository,
      base=state.base,
      extension=state.extension,
      branch=state.branch,
      finished=finished,
    )
  except Exception as error:  # noqa: BLE001 (reported in the document)
    state.error = failure(error)
    return
  state.done_until = reading.done_until
  state.last_commit_at = reading.last_commit_at
  state.branch = reading.branch
  state.error = None


def load(state_file: pathlib.Path, fresh: bool) -> ProgressState | None:
  return load_model(ProgressState, state_file, fresh)


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
  ends now (`main`, also when the extension resumes a failed one)."""

  def change(_: ProgressState | None) -> ProgressState:
    error = None
    try:
      main = read_main(repository)
    except Exception as caught:  # noqa: BLE001 (reported in the document)
      main, error = Main(), failure(caught)
    state = ProgressState(
      name=name,
      state="running",
      started_at=now(),
      updated_at=now(),
      heartbeat_seconds=heartbeat_seconds,
      start=start.date() if start else main.stored.done_until,
      end=end.date(),
      done_until=None,
      last_commit_at=None,
      repository=repository,
      base=main.base,
      extension=start is None,
    )
    if error is None:
      refresh(state)
    else:
      state.error = error
    return state

  update_state(files, load, change, fresh=True)


@progress.command()
@pass_files
def beat(files: Files) -> None:
  """The download is still running."""

  def change(state: ProgressState | None) -> ProgressState | None:
    state = require_started(state, files, "download")
    # A late beat of an ended download would make it look as if it were running again.
    if state.state != "running":
      return None
    refresh(state)
    return state

  update_state(files, load, change, fresh=False)


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
    state = require_started(state, files, "download")
    refresh(state, finished=new_state == "finished")
    state.state = new_state
    state.detail = detail
    state.ended_at = now()
    return state

  update_state(files, load, change, fresh=False)


def json_schema() -> str:
  """The published document's JSON Schema."""
  return json.dumps(Progress.model_json_schema(by_alias=True, mode="serialization"), indent=2)
