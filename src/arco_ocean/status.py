# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The forecast collection's heartbeat: a JSON document that the ARCO-OCEAN web page reads.

`scripts/forecast.sh` runs `arco-ocean status` at each step of a collection, and every few
minutes while it runs. Each call updates a local state file and, with `--publish`, uploads the
document (to an `s3://` URL, or to a local path). The repositories (local or `s3://`) are read and
the document uploaded with arco-make's settings (`~/.arcomakerc`: the AWS profile), applied first.
The page tells from it whether the latest collection is running, finished or aborted, and calls it
stale when the heartbeat stops or no collection finished for too long: a collection killed without
notice (the machine down, a signal that cannot be trapped) stops beating.

The document is `Heartbeat` (`arco-ocean heartbeat-schema` prints its JSON Schema), all times in
UTC. A resolution's `waiting_since` is when its collections started to end with a run not
published (the first of them in a row), kept until one stores every run; `missing_after_days` is
the recipes' `[forecast] missing_after`. A page calls the collection stale when a resolution's
newest run is older than that, or has waited longer: a source that stopped publishing keeps a
resolution waiting (its older runs are stored without it, flagged), every day.

The state file is `State`: the document and the repositories' paths and URLs, which are not
published.
"""

import contextlib
import dataclasses
import datetime
import fcntl
import json
import math
import os
import pathlib
import tempfile
from collections.abc import Callable, Generator
from typing import Annotated, Literal, Protocol, get_args

import click
from pydantic import (
  AwareDatetime,
  BaseModel,
  ConfigDict,
  Field,
  PlainSerializer,
  ValidationError,
  WithJsonSchema,
)

SCHEMA = 1
CollectionState = Literal["running", "finished", "aborted"]
ResolutionState = Literal["pending", "downloading", "finished", "not_published", "failed"]
# The recipes' `[forecast] missing_after`, when a heartbeat gives none (the web page's too:
# docs/assets/js/status.js).
DEFAULT_MISSING_AFTER_DAYS = 2.0
# `arco-ocean status overdue`'s exit status for a collection that finished behind.
BEHIND_EXIT = 3
# Dimensions of the forecast recipes (arco-make's defaults).
INIT_DIM = "init_time"
LEAD_DIM = "lead_time"

# A time in UTC, to the second, as "2026-11-24T12:00:03Z" (the schema says so: the page reads it).
Time = Annotated[
  AwareDatetime,
  PlainSerializer(
    lambda value: value.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), return_type=str
  ),
  WithJsonSchema(
    {"type": "string", "format": "date-time", "pattern": r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"}
  ),
]
# Every key is written, null or not: the schema requires them all.
MODEL_CONFIG = ConfigDict(
  extra="forbid", validate_assignment=True, json_schema_serialization_defaults_required=True
)


def now() -> datetime.datetime:
  return datetime.datetime.now(datetime.UTC).replace(microsecond=0)


class Resolution(BaseModel):
  """One resolution of a collection: its download's state and its repository's newest run."""

  model_config = MODEL_CONFIG

  res: str = Field(description='The resolution, as in the repository\'s name: "0p25"')
  state: ResolutionState = "pending"
  started_at: Time | None = None
  ended_at: Time | None = None
  latest_run: datetime.date | None = Field(None, description="The newest run stored")
  runs: int | None = Field(None, description="The number of runs stored")
  flags: dict[str, float] = Field(
    default_factory=dict,
    description="Each flag variable: the share of the newest run's lead times that are true",
  )
  waiting_since: Time | None = None
  error: str | None = Field(None, description="Why the repository could not be read")


class Heartbeat(BaseModel):
  """The published document."""

  model_config = MODEL_CONFIG | ConfigDict(populate_by_name=True)

  schema_version: Literal[1] = Field(SCHEMA, alias="schema")
  state: CollectionState
  detail: str | None = None
  started_at: Time
  updated_at: Time = Field(description="The heartbeat: the last update")
  ended_at: Time | None = None
  heartbeat_seconds: int
  stale_after_hours: float
  missing_after_days: float
  target_run: datetime.date = Field(description="The newest run asked for")
  resolutions: list[Resolution]


class State(Heartbeat):
  """The state file: the document, and where each resolution's repository is."""

  repositories: dict[str, str] = Field(default_factory=dict)

  def public(self) -> str:
    """The published document, without the repositories' paths and URLs."""
    shown = self.model_dump(mode="json", by_alias=True, exclude={"repositories"})
    return json.dumps(shown, indent=2) + "\n"


@contextlib.contextmanager
def locked(state_file: pathlib.Path) -> Generator[None]:
  """The heartbeat loop and the steps of the collection update the state file in turn."""
  lock = state_file.with_name(state_file.name + ".lock")
  lock.parent.mkdir(parents=True, exist_ok=True)
  with lock.open("w") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    yield


def load_model[M: BaseModel](model: type[M], state_file: pathlib.Path, fresh: bool) -> M | None:
  """The state in `state_file`, as `model`, or None if there is none. A state file that is not
  one (another version's, damaged) is an error, unless a run starts anew (`fresh`): it is then
  replaced, as otherwise every heartbeat would fail until the file is removed by hand."""
  try:
    text = state_file.read_text()
  except FileNotFoundError:
    return None
  try:
    return model.model_validate_json(text)
  except ValidationError as error:
    problem = f"{state_file} is not a heartbeat's state ({error.error_count()} errors)"
    if fresh:
      click.echo(f"Warning: {problem}: a new one is written.", err=True)
      return None
    raise click.ClickException(f"{problem}: the next start replaces it") from error


def load(state_file: pathlib.Path, fresh: bool = False) -> State | None:
  """The forecast collection's state (`load_model`)."""
  return load_model(State, state_file, fresh)


def write_atomically(path: pathlib.Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as tmp:
    tmp.write(text)
  os.replace(tmp.name, path)


def publish(url: str, body: str) -> None:
  """Upload `body` to an `s3://` URL (never cached by browsers: the page polls it), or write it
  to a local path."""
  if not url.startswith("s3://"):
    write_atomically(pathlib.Path(url), body)
    return
  import botocore.session

  bucket, _, key = url.removeprefix("s3://").partition("/")
  if not bucket or not key:
    raise ValueError(f"not an object URL: {url}")
  session = botocore.session.Session()
  # botocore follows S3's redirect to the bucket's region, whatever the profile's.
  region = session.get_config_variable("region") or "us-east-1"
  client = session.create_client("s3", region_name=region)
  client.put_object(
    Bucket=bucket,
    Key=key,
    Body=body.encode(),
    ContentType="application/json",
    CacheControl="no-cache, max-age=0",
  )


class RepositorySummary(BaseModel):
  """What the heartbeat reads from a forecast repository."""

  latest_run: datetime.date | None = None
  runs: int | None = None
  flags: dict[str, float] = Field(default_factory=dict)


def repository_summary(path: str) -> RepositorySummary:
  """The newest run in the forecast repository at `path` (on `main`), the number of runs, and,
  for each flag variable (bool, init x lead), the share of that run's lead times flagged."""
  import xarray as xr
  from arcomake import icechunk_utils

  if not icechunk_utils.is_repository(path):
    return RepositorySummary()
  dataset = xr.open_zarr(icechunk_utils.readonly_store(path), consolidated=False)
  init = dataset[INIT_DIM]
  if init.size == 0:
    return RepositorySummary(runs=0)
  latest = init.values.max()
  flags = {}
  for name, variable in dataset.data_vars.items():
    if variable.dtype == bool and set(variable.dims) == {INIT_DIM, LEAD_DIM}:
      share = float(variable.sel({INIT_DIM: latest}).mean())
      # A run without lead times has no share: NaN would be written as null, which no flag is.
      if not math.isnan(share):
        flags[str(name)] = round(share, 3)
  day = datetime.date.fromisoformat(str(latest.astype("datetime64[D]")))
  return RepositorySummary(latest_run=day, runs=int(init.size), flags=flags)


def summarize(entry: Resolution, path: str | None) -> None:
  """Add the repository's summary to a resolution's entry; a failure is recorded, not raised:
  the heartbeat never stops a collection."""
  if path is None:
    return
  try:
    summary = repository_summary(path)
  except Exception as error:  # noqa: BLE001 (reported in the document)
    entry.error = f"the repository could not be read: {type(error).__name__}"
    return
  entry.latest_run = summary.latest_run
  entry.runs = summary.runs
  entry.flags = summary.flags
  entry.error = None


def apply_settings() -> None:
  """The AWS profile and other settings from ~/.arcomakerc, as arco-make itself reads them: the
  systemd units run without the shell's environment."""
  from arcomake import settings

  settings.apply(settings.read(settings.settings_path()))


@dataclasses.dataclass(frozen=True)
class Files:
  """Where the command keeps the state and publishes the document (the group's options)."""

  state_file: pathlib.Path
  publish: str | None


pass_files = click.make_pass_decorator(Files)


class StateFile(Protocol):
  """A state file's model (`State`, `progress.ProgressState`): the published document, and what
  stays private."""

  updated_at: datetime.datetime

  def public(self) -> str: ...

  def model_dump_json(self, *, indent: int | None = None, by_alias: bool | None = None) -> str: ...


def update_state[S: StateFile](
  files: Files,
  load_state: Callable[[pathlib.Path, bool], S | None],
  change: Callable[[S | None], S | None],
  fresh: bool,
) -> None:
  """Apply `change` to the state file (read by `load_state`), under its lock, then publish the
  document. A change that returns None leaves both as they are. `fresh`: see `load_model`."""
  # Before any read: the repositories may be in the bucket (DATA_ROOT, scripts/lib/common.sh).
  apply_settings()
  with locked(files.state_file):
    state = change(load_state(files.state_file, fresh))
    if state is None:
      return
    state.updated_at = now()
    write_atomically(files.state_file, state.model_dump_json(indent=2, by_alias=True) + "\n")
    if files.publish is not None:
      publish(files.publish, state.public())


def require_started[S](state: S | None, files: Files, what: str) -> S:
  """The state, or an error if `what` (a collection, a download) has not started."""
  if state is None:
    raise click.ClickException(f"no {what} started: {files.state_file} is missing")
  return state


def update(
  files: Files, change: Callable[[State | None], State | None], fresh: bool = False
) -> None:
  """`update_state` of the forecast collection's state."""
  update_state(files, load, change, fresh)


def started(state: State | None, files: Files) -> State:
  return require_started(state, files, "collection")


def repository_option(
  _context: click.Context, _parameter: click.Parameter, values: tuple[str, ...]
) -> dict[str, str]:
  repositories = {}
  for value in values:
    res, separator, path = value.partition("=")
    if not separator or not res or not path:
      raise click.BadParameter(f"{value!r} is not RES=PATH")
    repositories[res] = path
  return repositories


@click.group()
@click.option(
  "--state-file", type=click.Path(path_type=pathlib.Path), required=True, help="The state file."
)
@click.option("--publish", help="s3:// URL or local path of the published document.")
@click.pass_context
def status(context: click.Context, state_file: pathlib.Path, publish: str | None) -> None:
  """The forecast collection's heartbeat (scripts/forecast.sh)."""
  context.obj = Files(state_file, publish)


@status.command()
@click.option(
  "--target-run",
  type=click.DateTime(["%Y-%m-%d"]),
  required=True,
  help="The newest run asked for (YYYY-MM-DD).",
)
@click.option(
  "--repo",
  "repositories",
  multiple=True,
  callback=repository_option,
  help="RES=PATH, one per resolution.",
)
@click.option("--heartbeat-seconds", type=int, default=300, show_default=True)
@click.option("--stale-after-hours", type=float, default=30.0, show_default=True)
@click.option("--missing-after-days", type=float, default=2.0, show_default=True)
@pass_files
def start(
  files: Files,
  target_run: datetime.datetime,
  repositories: dict[str, str],
  heartbeat_seconds: int,
  stale_after_hours: float,
  missing_after_days: float,
) -> None:
  """A collection starts."""

  def change(state: State | None) -> State:
    previous = {entry.res: entry for entry in state.resolutions} if state else {}
    resolutions = []
    for res, path in repositories.items():
      # What was known stays (the newest run, the wait) if the repository cannot be read now.
      before = previous.get(res)
      fresh_state = {"state": "pending", "started_at": None, "ended_at": None, "error": None}
      entry = before.model_copy(update=fresh_state, deep=True) if before else Resolution(res=res)
      summarize(entry, path)
      resolutions.append(entry)
    return State(
      state="running",
      started_at=now(),
      updated_at=now(),
      heartbeat_seconds=heartbeat_seconds,
      stale_after_hours=stale_after_hours,
      missing_after_days=missing_after_days,
      target_run=target_run.date(),
      resolutions=resolutions,
      repositories=repositories,
    )

  update(files, change, fresh=True)


@status.command()
@pass_files
def beat(files: Files) -> None:
  """The collection is still running."""

  def change(state: State | None) -> State | None:
    state = started(state, files)
    # A late beat of an ended collection would make it look as if it were running again.
    return state if state.state == "running" else None

  update(files, change)


@status.command("res")
@click.argument("res")
@click.argument("new_state", metavar="STATE", type=click.Choice(get_args(ResolutionState)))
@pass_files
def resolution(files: Files, res: str, new_state: ResolutionState) -> None:
  """A resolution's download changes state."""

  def change(state: State | None) -> State:
    state = started(state, files)
    entries = {entry.res: entry for entry in state.resolutions}
    if res not in entries:
      raise click.ClickException(f"unknown resolution {res!r}: not in this collection")
    entry = entries[res]
    entry.state = new_state
    if new_state == "downloading":
      entry.started_at = now()
    elif new_state != "pending":
      entry.ended_at = now()
      # Waiting from the first collection in a row that ended with a run not published.
      if new_state == "not_published":
        entry.waiting_since = entry.waiting_since or now()
      elif new_state == "finished":
        entry.waiting_since = None
      summarize(entry, state.repositories.get(res))
    return state

  update(files, change)


@status.command()
@click.argument(
  "new_state",
  metavar="STATE",
  type=click.Choice([state for state in get_args(CollectionState) if state != "running"]),
)
@click.option("--detail", help="What the page shows next to the state.")
@pass_files
def end(files: Files, new_state: CollectionState, detail: str | None) -> None:
  """The collection ends."""

  def change(state: State | None) -> State:
    state = started(state, files)
    state.state = new_state
    state.detail = detail
    state.ended_at = now()
    for entry in state.resolutions:
      # A collection aborted while a resolution was downloading: that one failed.
      if new_state == "aborted" and entry.state == "downloading":
        entry.state = "failed"
        entry.ended_at = now()
    return state

  update(files, change)


def json_schema() -> str:
  """The published document's JSON Schema."""
  return json.dumps(Heartbeat.model_json_schema(by_alias=True, mode="serialization"), indent=2)


def resolution_label(res: str) -> str:
  """ "0p25" as "0.25°"."""
  return res.replace("p", ".", 1) + "°"


def duration(delta: datetime.timedelta) -> str:
  """ "3 min", "2 h 5 min", "1 d 3 h", as the web page writes durations."""
  minutes = max(0, int(delta.total_seconds() // 60))
  if minutes < 60:
    return f"{minutes} min"
  hours, minutes = divmod(minutes, 60)
  if hours < 24:
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"
  days, hours = divmod(hours, 24)
  return f"{days} d {hours} h" if hours else f"{days} d"


def behind(heartbeat: Heartbeat, at: datetime.datetime) -> list[str]:
  """Why the resolutions of a collection are behind, as the web page judges a finished one
  (`behind` in docs/assets/js/status.js): a newest stored run older than the recipes'
  `missing_after`
  before the newest asked for (runs that old are stored even without a source, flagged), none
  stored, or a resolution waiting for its sources for longer than that (a source that stopped
  publishing keeps it waiting every day, while its older runs are stored without it)."""
  # As the page: 0 (or none) is its default, two days.
  limit = heartbeat.missing_after_days or DEFAULT_MISSING_AFTER_DAYS
  reasons = []
  for entry in heartbeat.resolutions:
    label = resolution_label(entry.res)
    if entry.latest_run is None:
      reasons.append(f"{label} has no run stored")
      continue
    lag = (heartbeat.target_run - entry.latest_run).days
    if lag > limit:
      reasons.append(f"{label}'s newest run is {entry.latest_run}, {lag} days before the newest")
      continue
    if entry.waiting_since is not None and at - entry.waiting_since > datetime.timedelta(limit):
      reasons.append(f"{label} has waited for a source for {duration(at - entry.waiting_since)}")
  return reasons


def plain(value: object) -> str:
  """Text from the heartbeat made inert in Markdown, on one line: no mention, no issue
  reference, no HTML, no link, emphasis, code or table cell break."""
  text = " ".join(str("–" if value is None else value).split())
  # Backslashes first: they would otherwise undo the escapes below.
  text = text.replace("\\", "\\\\")
  for old, new in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("`", "'")):
    text = text.replace(old, new)
  for char in "*_[]()~|!":
    text = text.replace(char, "\\" + char)
  # A zero-width word joiner after each: no mention of a user, no reference to an issue.
  return text.replace("@", "@⁠").replace("#", "#⁠")


def utc(value: datetime.datetime | None) -> str:
  return "–" if value is None else value.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def summary(heartbeat: Heartbeat) -> str:
  """The heartbeat's public content in Markdown, for an issue (scripts/alert.sh)."""
  detail = f" {plain(heartbeat.detail)}" if heartbeat.detail is not None else ""
  lines = [
    f"**Collection {heartbeat.state}.**{detail}",
    "",
    f"- Started: {utc(heartbeat.started_at)}, last heartbeat: {utc(heartbeat.updated_at)},"
    f" ended: {utc(heartbeat.ended_at)}",
    f"- Newest run asked for: {heartbeat.target_run}",
  ]
  if heartbeat.resolutions:
    lines += ["", "| Resolution | State | Newest run | Runs | Error |", "|---|---|---|---|---|"]
    for entry in heartbeat.resolutions:
      cells = (resolution_label(entry.res), entry.state, entry.latest_run, entry.runs, entry.error)
      lines.append("| " + " | ".join(plain(cell) for cell in cells) + " |")
  return "\n".join(lines)


@status.command()
@pass_files
def overdue(files: Files) -> None:
  """Exit with 3 if the collection finished behind (see `behind`): forecast.sh then fails, and
  its alert (scripts/alert.sh) reports it, as the web page shows it stale. 1: the heartbeat cannot
  tell (no state, or a collection whose end it did not record)."""
  state = started(load(files.state_file), files)
  if state.state == "running":
    raise click.ClickException("the heartbeat did not record the collection's end")
  if state.state != "finished":
    return
  reasons = behind(state, now())
  if reasons:
    click.echo("The collection finished behind: " + "; ".join(reasons) + ".", err=True)
    raise click.exceptions.Exit(BEHIND_EXIT)


@status.command("summary")
@pass_files
def print_summary(files: Files) -> None:
  """Print the heartbeat's public content in Markdown (scripts/alert.sh)."""
  click.echo(summary(started(load(files.state_file), files)))
