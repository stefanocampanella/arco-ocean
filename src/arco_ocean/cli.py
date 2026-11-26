# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The `arco-ocean` command."""

import click

from arco_ocean import progress, status


@click.group()
def cli() -> None:
  """ARCO-OCEAN's tools: the heartbeats of the forecast collection and of downloads."""


@cli.command("heartbeat-schema")
def heartbeat_schema() -> None:
  """Print the JSON Schema of the heartbeat's published document."""
  click.echo(status.json_schema())


@cli.command("progress-schema")
def progress_schema() -> None:
  """Print the JSON Schema of a download's published progress."""
  click.echo(progress.json_schema())


cli.add_command(status.status)
cli.add_command(progress.progress)
