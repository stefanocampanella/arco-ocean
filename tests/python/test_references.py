# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""Every DOI the site links has its citation in docs/references.bib: mystmd then takes it from
there, without asking doi.org, which does not always answer (a build of 26 Nov 2026 failed on it).
A new DOI's citation: `curl -sL -H "Accept: application/x-bibtex" https://doi.org/DOI`."""

import pathlib
import re

DOCS = pathlib.Path(__file__).parents[2] / "docs"
LINKED = re.compile(r"\]\(https://doi\.org/(10\.[^)\s]+)\)")
CITED = re.compile(r"\bdoi\s*=\s*\{([^}]+)\}", re.IGNORECASE)


def test_every_linked_doi_has_its_citation() -> None:
  linked = {doi.lower() for page in DOCS.glob("*.md") for doi in LINKED.findall(page.read_text())}
  cited = {doi.lower() for doi in CITED.findall((DOCS / "references.bib").read_text())}
  assert linked, "no DOI found: the pattern no longer matches the pages"
  assert linked <= cited, f"not in docs/references.bib: {sorted(linked - cited)}"
