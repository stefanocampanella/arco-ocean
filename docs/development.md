# Development

The repository holds the recipes (`configs/`), the scripts that run them (`scripts/`, bash),
the package of ARCO-OCEAN's own code (`src/arco_ocean`: the forecast collection's heartbeat), the
notebooks (`notebooks/`) and this site (`docs/`). The datasets are made by
[arco-make](https://github.com/stefanocampanella/arco-make), from its released image.

## Checks

`uvx pre-commit run --all-files` runs the checks made before each commit: TOML and YAML syntax,
ruff, ty, ShellCheck, the web page's tests, the scripts' tests, REUSE and a secret scan. CI runs
them on every pull request, and:

- `uv run --frozen pytest` (`tests/python`; a coverage of the package of at least 80 %): every
  recipe loaded with the models of the pinned arco-make (an unknown key, step or argument
  fails), the examples of the coarsening notes, and the forecast heartbeat.
- `tests/bats/helpers/bats-core/bin/bats tests/bats`: the scripts and the systemd units, with
  [bats-core](https://bats-core.readthedocs.io), its libraries (bats-support, bats-assert,
  bats-file) as git submodules in `tests/bats/helpers` (after a clone: `git submodule update
  --init`). One file per script; each test runs in a project directory of its own, with
  stand-ins first on `PATH` for the commands the scripts call (`arco-make`, `systemctl`, `gh`,
  ...), which record their calls (`tests/bats/common.bash`); the units are checked by
  `systemd-analyze verify`. The heartbeat's tests run the package's `arco-ocean`: they need the
  project's environment (`uv sync`) and are skipped without it.
- `node --test 'tests/js/*.test.js'` (Node.js from `uvx --from nodejs-wheel`): the web page's
  judgement of the heartbeat, on fixtures that `tests/python/test_js_fixtures.py` checks against
  the package's models, so that the page is tested with the documents the heartbeat publishes.

## The site

This site is built by [mystmd](https://mystmd.org), the engine of Jupyter Book 2, from the pages
in `docs/` (`docs/myst.yml` lists them) and the marimo notebooks of `notebooks/`, exported to
pages first (their text and code, not run), and deployed to GitHub Pages from `main` by
`.github/workflows/pages.yml` (Pages enabled once, with "GitHub Actions" as source). Each fact is
written once, here; the README points to these pages. To preview it:

```bash
scripts/site.sh start   # http://localhost:3000
```

The citations of the DOIs the pages link are in `docs/references.bib`, so that the site builds
without asking doi.org, which does not always answer: a new DOI needs its entry,
`curl -sL -H "Accept: application/x-bibtex" https://doi.org/DOI` (`tests/python/test_references.py`
checks).

The states of the historical downloads, of the statistics and of the forecast collection on the
home page are MyST `{anywidget}`s of one module, `docs/assets/js/status.js` with its styles in
`status.css` (the directive copies one file alone), the card chosen by the directive's JSON
(`{"show": "historical"}`, `{"show": "statistics"}` or `{"show": "forecast"}`). It holds the
judgements of the documents (pure functions, tested in Node, `tests/js`, on fixtures the
package's models validate) and the widget, which reads its documents every minute. `?status=URL`
in the page's address reads another heartbeat, e.g. the test copy in the bucket's
`experiments/status/forecast.json`, and `?progress=PREFIX` and `?statistics=PREFIX` other
progresses and states (`PREFIX` followed by `res=<res>.json`).

## Use of AI tools

The recipes, scripts and documentation of this repository have been written largely with AI coding assistants (Claude Code, by Anthropic), directed and reviewed by the maintainers, as has [arco-make](https://github.com/stefanocampanella/arco-make), the tool that produces the datasets. The recipes' outputs were checked on real data before the production run (arco-make's logbook records the checks). The commits made with an assistant name it in a `Co-Authored-By` trailer. The maintainers are responsible for the datasets and the code as published: please report problems as issues.
