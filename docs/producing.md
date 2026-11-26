---
license: CC-BY-4.0
---

# Producing and extending the dataset

The recipes have no dates: the command gives them, so one recipe serves the first download and
every later extension, and the fingerprint of the recipe recorded in each commit stays the same.

```bash
# The whole period, at one resolution (DATA_ROOT/historical/res=0p25; about four days on the
# project machine).
scripts/download.sh --bind /data --start 1993-01-01 --end 2026-07-01 historical_res-0p25
# Later: the days after the last stored one, as a new version, once every source has them as
# final data (ERA5 lags by about three months).
scripts/download.sh --bind /data --extend --end 2026-10-01 historical_res-0p25
# The statistics of a resolution (DATA_ROOT/statistics/res=0p25).
scripts/climatology.sh --bind /data historical_res-0p25
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

Each commit of a repository records how it was made, in its metadata: the version and commit of
arco-make, the versions of the packages that decide the values, and the recipe's fingerprint.

The scripts run arco-make from the image of the version the checks pin (`pyproject.toml`), now
`oras://ghcr.io/stefanocampanella/arco-make:v0.2.0`, which stays as published; `--image` names
another, `--virtual-env` a Python environment instead.
