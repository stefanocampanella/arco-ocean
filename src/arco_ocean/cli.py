# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The `arco-ocean` command."""

import click

from arco_ocean import status


@click.group()
def cli() -> None:
  """ARCO-OCEAN's tools: the forecast collection's heartbeat."""


@cli.command("heartbeat-schema")
def heartbeat_schema() -> None:
  """Print the JSON Schema of the heartbeat's published document."""
  click.echo(status.json_schema())


cli.add_command(status.status)
