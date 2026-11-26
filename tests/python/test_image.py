# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The scripts' default image is the one of the arco-make these checks pin."""

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).parents[2]
SCRIPTS = ("download.sh", "climatology.sh")
IMAGE = "oras://ghcr.io/stefanocampanella/arco-make"


def pinned_version() -> str:
  lock = tomllib.loads((ROOT / "uv.lock").read_text())
  (package,) = (p for p in lock["package"] if p["name"] == "arcomake")
  return package["version"]


def test_the_default_image_is_the_pinned_version() -> None:
  """A version's image, not `latest`, which every merge on arco-make's master replaces."""
  expected = f"{IMAGE}:v{pinned_version()}"
  for script in SCRIPTS:
    text = (ROOT / "scripts" / script).read_text()
    (default,) = re.findall(r'^IMAGE="([^"]*)"$', text, flags=re.MULTILINE)
    assert default == expected, script
    assert f"(default: {expected})" in text, script
