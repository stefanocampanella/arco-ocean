# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The scripts' default image is the one of the arco-make these checks pin."""

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).parents[2]
IMAGE = "oras://ghcr.io/stefanocampanella/arco-make"


def pinned_version() -> str:
  lock = tomllib.loads((ROOT / "uv.lock").read_text())
  (package,) = (p for p in lock["package"] if p["name"] == "arcomake")
  return package["version"]


def test_the_default_image_is_the_pinned_version() -> None:
  """A version's image, not `latest`, which every merge on arco-make's master replaces. The
  scripts take it from scripts/lib/common.sh, and their help shows it from there."""
  expected = f"{IMAGE}:v{pinned_version()}"
  text = (ROOT / "scripts" / "lib" / "common.sh").read_text()
  (default,) = re.findall(r'^DEFAULT_IMAGE="([^"]*)"$', text, flags=re.MULTILINE)
  assert default == expected
  # No script keeps an image of its own.
  for script in (ROOT / "scripts").glob("*.sh"):
    assert IMAGE not in script.read_text(), script.name
