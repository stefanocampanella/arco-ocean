# Producing and extending the dataset

The recipes have no dates: the command gives them, so one recipe serves the first download and
every later extension, and the fingerprint of the recipe recorded in each commit stays the same.

```bash
# The whole period, at one resolution (DATA_ROOT/historical/res=0p25; about four days on the
# project machine), its progress on the web page, a failure reported as a GitHub issue.
scripts/download.sh --bind /data --start 1993-01-01 --end 2026-07-01 \
    --status-url s3://ogs-arco-ocean/status/historical/res=0p25.json --alert historical_res-0p25
# Later: the days after the last stored one, as a new version, once every source has them as
# final data (ERA5 lags by about three months).
scripts/download.sh --bind /data --extend --end 2026-10-01 historical_res-0p25
# The statistics of a resolution (DATA_ROOT/statistics/res=0p25), the same way.
scripts/climatology.sh --bind /data \
    --status-url s3://ogs-arco-ocean/status/statistics/res=0p25.json --alert historical_res-0p25
```

The outputs are `DATA_ROOT/<product>/res=<res>`, the bucket's layout with
`DATA_ROOT=s3://ogs-arco-ocean`. `DATA_ROOT` comes from the scripts' `--data-root`, the
environment, the scripts' settings file, `scripts/.env` (`$SCRATCH/arco-ocean` on clusters that
have one), else the project's `data/` (`scripts/lib/common.sh`); `--output` names one output
instead. The settings file, `~/.config/arco-ocean/settings` (`ARCO_OCEAN_SETTINGS` names another,
empty disables it), is read by the units too:

```bash
# ~/.config/arco-ocean/settings on the project machine
DATA_ROOT=s3://ogs-arco-ocean
```

A 0.25° historical repository takes several terabytes: write it to the bucket, not to a local
disk. The scripts' settings stay apart from arco-make's (`~/.arcomakerc`, below), which holds
secrets, and which arco-make warns about for any key it does not know.

The image sees only the home directory, `/tmp` and the current directory: a path elsewhere that
arco-make uses (its `TMPDIR`, a local output) must be bound with `--bind` (`/data` on the project
machine). Otherwise arco-make stops at once, its `TMPDIR` "not an existing, writable directory".

A block that fails with a transient error (a timeout, a dropped connection, a server error) is
redone, as the recipe's `[retries]` say: a historical block waits out an hour of outage of a
source, a forecast run a quarter of an hour. A run that fails anyway is resumed by
`scripts/download.sh` (`--attempts`); for the forecasts, 6 times, 30 minutes apart, for each
resolution. arco-make plans chunks of up to Dask's `array.chunk-size`: on the project machine,
`DASK_ARRAY__CHUNK_SIZE=256MiB` in arco-make's settings file (`~/.arcomakerc`), the fastest
there (Dask's default is 128 MiB).

With `--status-url`, a download publishes its progress, which the home page shows for the
historical downloads, one document per resolution (`status/historical/res=<res>.json` in the
bucket, as the repositories' layout):
`arco-ocean progress`, run with uv in the checkout, reads how far the download is from the
repository, as arco-make records it (each block a commit on the run's branch, its interval in the
commit's metadata), when the download starts, every `--heartbeat` seconds (300) and when it ends.
The document says "running", "finished" or "failed" (with the exit status), the period, the end
of the newest block stored, and when the newest block was committed and the document last
updated (`arco-ocean progress-schema` prints its schema). The progress is the download's own run
(its branch started from the repository as it was when the download started, a resumed run
included): an extension counts what the repository held, a `--replace` does not. The
repository's path and what identifies the run stay in the state file,
`LOG_DIR/progress_RECIPE.json`. A download killed outright stops updating it, and the
page calls it stale. A failure to publish it never stops the download (`LOG_DIR/progress.log`).

`scripts/climatology.sh --status-url` publishes the statistics' state the same way
(`arco-ocean progress --kind statistics`), at `status/statistics/res=<res>.json`: computing,
finished (with the time of their commit) or failed; written in one commit at the end, they have
no progress to show.

With `--alert`, both scripts report how they end on GitHub (`scripts/alert.sh`, in the
background, as the forecast collection's alerts, with the same token, see
[Forecasts](forecasts.md)): a failure (with the exit status, an interruption included) comments on
the open issue of that recipe, labelled `download-alert` or `statistics-alert` and titled
"Download RECIPE failed" or "Statistics RECIPE failed", or opens one; a run that succeeds closes
that recipe's open issues. The issue shows the progress's public summary, never logs. A run killed
outright, or the machine down, reports nothing: the page calls it stale. A report that fails is
logged in `LOG_DIR/alert.log`.

Each commit of a repository records how it was made, in its metadata: the version and commit of
arco-make, the versions of the packages that decide the values, and the recipe's fingerprint.

The scripts run arco-make from the image of the version the checks pin (`pyproject.toml`), now
`oras://ghcr.io/stefanocampanella/arco-make:v0.2.0`, which stays as published; `--image` names
another, `--virtual-env` a Python environment instead.
