---
license: CC-BY-4.0
---

# Forecasts

The forecast repositories (`forecast/res=<res>`, recipes `configs/download/forecast_res-<res>.toml`)
hold daily forecast runs on the grid and with the variables of the historical dataset: the
00 UTC run of each day, its 10 lead days, the last five years of runs. The sources are the
forecasts of the historical ones: GLO12, the Copernicus Marine analysis and forecast, for
GLORYS12 (with GLO12's own static fields: its sea differs from GLORYS12's in about 0.4 % of the
native cells, and `volcello` counts its partial bottom cells, which GLORYS12's static product does
not give: 0.75 % less water in all, up to 7 % less in the deepest levels, more in level 48, which
takes in level 49; the `deptho` comments tell how each product's sea floor differs from its
water column); IFS HRES from ECMWF's open data for ERA5 (the static `z` and `lsm` stay ERA5's).
`scripts/forecast.sh` collects
them at every resolution: the first time with `--start`, from the end of the historical dataset,
then every day, adding the runs after the last stored one (a missed day is caught up).

```bash
# The heartbeat's environment (the package, src/arco_ocean), after each pull: forecast.sh runs
# `arco-ocean status` with uv, which would otherwise install it at the collection's first beat.
uv sync --frozen --no-default-groups
# The first time: every run from the end of the historical dataset to today's, with the
# heartbeat for the web page (DATA_ROOT/forecast/res=<res>).
scripts/forecast.sh --bind /data --status-url s3://ogs-arco-ocean/status/forecast.json \
    --start 2026-07-01
# Then every day at 12:00 UTC, from systemd (below), once the backfill is stored: the units
# extend the repositories, and fail while there are none; their failures and recoveries are
# reported as a GitHub issue (below).
scripts/install_units.sh --alerts -- --bind /data
```

arco-make's settings and credentials come from its settings file, `~/.arcomakerc`, which the
heartbeat reads too: the AWS profile included (`AWS_PROFILE` or `AWS_DEFAULT_PROFILE`). The
units do not read the shell's profile, so a variable exported there (by hand, or in `~/.bashrc`)
reaches commands run by hand but not the daily collection: put arco-make's in `~/.arcomakerc`,
the scripts' `DATA_ROOT` in their settings file. The scripts also source `scripts/.env`
(`--env-file` for another), which sets only `DATA_ROOT`.

The daily collection runs as systemd user units, versioned in `systemd/`:
`arco-ocean-forecast.timer` starts `arco-ocean-forecast.service`, which runs
`scripts/forecast.sh --status-url s3://ogs-arco-ocean/status/forecast.json` with the options given
to `scripts/install_units.sh` after `--`. 12:00 UTC is hours after the sources published
today's run on 23 Nov 2026 (GLO12 by 06:00 UTC, IFS on AWS at 07:30), so that a late release
still makes it; a run still missing is tried again
(below), else the next day. Compared with cron:
- a day the machine was off is collected when it starts again, and a collection still running is
  not started twice;
- a collection that hangs is stopped after 20 hours (its heartbeat ends aborted, the next one
  resumes), and one that takes more than 80 % of the machine's memory is killed;
- the output goes to the journal (`journalctl --user -u arco-ocean-forecast`), the next and last
  runs are shown by `systemctl --user list-timers`; the unit fails when a download does, or
  when the collection finishes behind (below; a run not published yet, within `missing_after`,
  ends `forecast.sh` with 75, a success for the unit).

The installer links the units from the checkout (after a `git pull` that changes them:
`systemctl --user daemon-reload`) and writes the machine's part, the checkout and the options, in
a drop-in (`~/.config/systemd/user/arco-ocean-forecast.service.d/local.conf`); run it again to
change the options, or from another checkout to move the units there. `--uninstall` stops the
timer and a collection running and removes what the installer wrote (drop-ins of your own, from
`systemctl --user edit`, stay). The user's units run only while the user
is logged in, unless lingering is on (once: `sudo loginctl enable-linger $USER`). A collection
can still be run by hand (`systemctl --user start arco-ocean-forecast`, or `scripts/forecast.sh`):
collections never overlap.

A run whose sources have not all published it yet (younger than two days) is not stored: the
runs before it are, and it is tried again (every 30 minutes, 6 times), else collected the next
day; older, a source without it gives NaN, flagged. Collections never overlap. GLO12 overwrites its past
releases: a run collected after its day (the backfill, a missed day) holds the values of later
releases. Each component has a flag variable (`ifs_forecast`,
`glo12_forecast`; `init_time` x `lead_time`), true where its values are its run's own forecast,
false where they come from later releases or are missing (a source without the run: NaN).

With `--status-url`, the collection publishes a heartbeat, `status/forecast.json` in the bucket,
which the [web page](index.md) reads: the collection's state (`running`, `finished`, `aborted`),
each resolution's (`pending`, `downloading`, `finished`, `not_published`, `failed`), and each
repository's newest run, number of runs and flags. `arco-ocean status` (the package in
`src/arco_ocean`, run with uv in the checkout's environment, `arco-ocean heartbeat-schema` prints
the document's schema) writes it, with the AWS profile of arco-make's settings; it is
updated at each step and every 5 minutes while the collection runs (`--heartbeat`). A collection
that fails, or is stopped by a signal it can trap, ends its heartbeat as aborted; one killed
outright (or whose machine goes down) stops beating, and the page calls it stale after three
missed beats. A finished collection becomes stale when the next has not finished within 30 hours
(`--stale-after`), and is stale at once when a resolution falls behind by more than the recipes'
`missing_after` (two days, `--missing-after`, published with the heartbeat): its newest stored
run older than that, or the resolution waiting for its sources for longer (a source that stopped
publishing keeps it waiting every day, while the older runs are stored without it, flagged);
`forecast.sh` then fails (`arco-ocean status overdue`), so that its alert reports it. The
heartbeat never stops a collection: a failure to publish it is logged in
`logs/forecast/status.log`.

The alerts (`scripts/install_units.sh --alerts`) run on the machine that collects. systemd
starts `arco-ocean-alert@failed` when the collection's unit fails (a download failed, the
collection finished behind, it was stopped or timed out), and `arco-ocean-alert@finished` when
it succeeds (`OnFailure=` and `OnSuccess=`, in the collection's drop-in). Both run
`scripts/alert.sh`:
- **A failure** adds a comment to the open issue labelled `forecast-alert`, or opens one. It
  says what failed (`forecast.sh` exits with 3 when the collection finished behind, 1 for
  another failure), holds what systemd tells (the unit's result, exit code and status, and the
  `journalctl` command for its logs) and the heartbeat's public content (`arco-ocean status
  summary`), never logs, paths or host names: the repository is public.
- **A success** closes the open issues, with a comment.

A report that cannot reach GitHub is tried again, 6 times, 5 minutes apart. GitHub notifies the
repository's watchers. The issues are opened with the maintainer's token,
and GitHub does not email its own actions to a user unless asked: turn on "Include your own
updates" in GitHub's notification settings (Email preferences) to receive them. The token is in
`~/.config/arco-ocean/github-token`, readable by its owner only (`chmod 600`): a fine-grained
personal access token for this repository alone, with the repository permission "Issues: Read
and write" and nothing else (`--alert-repo OWNER/REPO` for another repository). GitHub emails
before the token expires; a failed report shows in `systemctl --user list-units --failed`.

What the alerts do not report, as they come from the collection's own unit: a collection that
hangs, until its unit times out (20 hours); and a collection that never starts (the machine
down, its timer disabled, lingering off after a reboot). The web page shows these stale, after
three missed beats or 30 hours without a collection finished. Until 26 Nov 2026 a GitHub Actions
watchdog read the heartbeat from outside, with a keepalive against GitHub disabling its
schedule; the installer removes the keepalive's units where it finds them.
