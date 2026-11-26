# The ARCO-OCEAN Dataset

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.17751608.svg)](https://doi.org/10.5281/zenodo.17751608)

<p align="center">
  <img src="assets/arco-ocean.webp" width="480" alt="A globe turning through 2023: sea surface temperature and sea ice from ARCO-OCEAN">
</p>

*Sea surface temperature (`thetao`, top level) and sea ice (`siconc`, white) of 2023 at 0.25°, day
by day, made by `scripts/animation.py` ([design](docs/animation-design.md)). Generated
using E.U. Copernicus Marine Service Information
([10.48670/moi-00021](https://doi.org/10.48670/moi-00021)).*

## Summary

The availability of standard datasets and benchmarks has been a key factor in the development of new machine learning methods and models, including those applied to weather forecasting and climate science ([Rasp et al., 2023](https://arxiv.org/abs/2308.15560), [Watson-Parris et al., 2022](https://doi.org/10.1029/2021MS002954)). The ARCO-OCEAN dataset is a new dataset that aims to provide a representative, and to some extent comprehensive, dataset for training machine learning models to forecast the ocean state.

This dataset is the first to include both the ocean state and its forcing, and has been designed having in mind coupled atmosphere-ocean models for Subseasonal-to-Seasonal (S2S) forecasts ([Campanella et al., 2025](https://www.climatechange.ai/papers/iclr2025/81)). However, future extensions could include variables related to climate, like biogeochemistry.

## Data

ARCO-OCEAN is an analysis-ready cloud-optimized ([Abernathey et al., 2021](https://doi.org/10.1109/MCSE.2021.3059437)) dataset providing physical properties of the ocean and sea ice for a period of about 33 years, from the 1st of January 1993 to the 30th of June 2026, the last day every source gives as final data (November 2026). The dataset includes also atmospheric variables that would be needed as boundary conditions and used to drive a numerical simulation. The dataset is the result of collecting, processing, merging and optimizing for the cloud different data sources, all retrospective analyses (reanalyses) or hindcasts of different Earth system components.

The fields are given on regular latitude-longitude grids at three horizontal resolutions: 0.25°, 0.5° and 1°. The finest is the resolution of most state-of-the-art machine learning weather forecasting models trained on the retrospective analysis ERA5 ([Hersbach et al., 2020](https://doi.org/10.1002/qj.3803)), and ERA5's own grid; the coarser ones are made from the same sources, not from the 0.25° data, so that every coarse cell keeps the water and ice of the source cells under it. Many of the variables in ARCO-OCEAN were originally defined on an Arakawa C grid and afterward interpolated on cell centers before being further postprocessed and ingested in the dataset. Please refer to the documentation of individual source datasets for more details. Also, see the section on regridding below.

The temporal resolution of ARCO-OCEAN is 1 day. The simulation timestep of numerical models is usually much less than that, and source datasets distribute either system state snapshots or time averages (or accumulations, e.g., for precipitation) at lower temporal resolutions. On top of that, the ARCO-OCEAN postprocessing further reduces the temporal resolution of some of these datasets. Individual sections of documentation provide more details.

Indeed, the dataset has been designed to train a machine learning forecasting model and takes inspiration from similar datasets, like ARCO-ERA5 ([Carver et al., 2023](https://ams.confex.com/ams/103ANNUAL/meetingapp.cgi/Paper/415842)). In light of this, design choices made are motivated in the following, and more precise information on how to reproduce the ARCO-OCEAN dataset is provided: the recipes are in `configs/download/`, the scripts that run them in `scripts/`, and the program is [arco-make](https://github.com/stefanocampanella/arco-make).

### Ocean and sea ice

The ocean circulation and sea ice variables are taken from the GLORYS12 reanalysis[^1], hence the dataset contains modified E.U. Copernicus Marine Service Information; [DOI: 10.48670/moi-00021](https://doi.org/10.48670/moi-00021).

GLORYS12 has an eddy-resolving resolution of 0.083°, which enables a high-fidelity representation of the dynamics of the ocean. Henceforth, by regridding a higher resolution product, the ARCO-OCEAN dataset retains accuracy although its lower resolution, as argued in [El Aouni et al., 2024](https://arxiv.org/abs/2412.05454). GLORYS12 covers latitudes from -80° to 90°: south of it, coarse cells have no sea (`seafrac` is 0) and no ocean values.

GLORYS12 is the only source dataset with a vertical dimension in ARCO-OCEAN. Its first 49 levels are kept, from 0.494 m to 5274.784 m; the 50th (5727.917 m) is left out, as NEMO, the model behind GLORYS12, never computes it.

| Variable name | Description                                    | Data type | Units   | Assimilated |
|---------------|------------------------------------------------|-----------|---------|-------------|
| `thetao`      | Potential temperature                          | float32   | °C      | Yes         |
| `so`          | Salinity                                       | float32   | - (PSU) | Yes         |
| `uo`          | Eastward ocean current velocity                | float32   | m/s     | No          |
| `vo`          | Northward ocean current velocity               | float32   | m/s     | No          |
| `zos`         | Sea surface height above geoid                 | float32   | m       | Yes         |
| `siconc`      | Sea ice concentration (over the sea part)      | float32   | -       | Yes         |
| `sivol`       | Sea ice volume per area (`siconc` × `sithick`) | float32   | m       | No          |
| `usic`        | `siconc` × eastward sea ice velocity           | float32   | m/s     | No          |
| `vsic`        | `siconc` × northward sea ice velocity          | float32   | m/s     | No          |

Values are averages over the sea part of each cell. GLORYS12's sea ice thickness and velocity (means over the ice-covered part) are `sivol / siconc`, `usic / siconc` and `vsic / siconc` where `siconc > 0`.

| Variable name                        | Description                                                             | Data type | Units |
|--------------------------------------|-------------------------------------------------------------------------|-----------|-------|
| `seafrac`                            | Share of the cell where GLORYS12 has a sea cell, per level (static)     | float32   | -     |
| `deptho`                             | Mean sea-floor depth, land as 0 (static; see its comment)               | float32   | m     |
| `areacello`                          | Cell area, on GLORYS12's sphere, radius 6,378,100 m (static)            | float32   | m²    |
| `volcello`                           | Sea water volume of the cell: `seafrac` × layer thickness × `areacello` | float32   | m³    |
| `lat_bnds`, `lon_bnds`, `depth_bnds` | CF cell bounds (depth: GLORYS12's layer faces)                          | float32   | ° / m |

Ocean and sea ice values exist exactly where `seafrac > 0`. Volumes and heat contents are sums of value × `volcello`; areas use `areacello`. The variables name these weights in `cell_measures`. How these fields are built, and why, is in the [notes on coarsening ocean datasets](docs/coarsen-ocean-datasets.md).

[^1]: Global Ocean Physics Reanalysis. E.U. Copernicus Marine Service Information (CMEMS). Marine Data Store (MDS). DOI: 10.48670/moi-00021 (Accessed on 10-Oct-2025)

### Waves

WAVERYS wave variables were part of the first version and are no longer included: their sea and ice masks differ from GLORYS12's (no sea north of about 81°N, waves missing where ERA5's ice cover exceeds about 0.3). The findings are kept in the notes on coarsening.

### Atmospheric

Dynamical atmospheric variables are derived from the ERA5 dataset available as a public dataset on Google Cloud Storage[^3], which redistributes the data available on Climate Data Store[^4]. As such, it requires attributing the original source.

> Hersbach et al, (2017) was downloaded from the Copernicus Climate Change Service (C3S) Climate Data Store. We thank C3S for allowing us to redistribute the data.
> Hersbach, H., Bell, B., Berrisford, P., Hirahara, S., Horányi, A., Muñoz‐Sabater, J., Nicolas, J., Peubey, C., Radu, R., Schepers, D., Simmons, A., Soci, C., Abdalla, S., Abellan, X., Balsamo, G., Bechtold, P., Biavati, G., Bidlot, J., Bonavita, M., De Chiara, G., Dahlgren, P., Dee, D., Diamantakis, M., Dragani, R., Flemming, J., Forbes, R., Fuentes, M., Geer, A., Haimberger, L., Healy, S., Hogan, R.J., Hólm, E., Janisková, M., Keeley, S., Laloyaux, P., Lopez, P., Lupu, C., Radnoti, G., de Rosnay, P., Rozum, I., Vamborg, F., Villaume, S., Thépaut, J-N. (2017): Complete ERA5: Fifth generation of ECMWF atmospheric reanalyses of the global climate. Copernicus Climate Change Service (C3S) Data Store (CDS). (Accessed on DD-MM-YYYY)
> The results contain modified Copernicus Climate Change Service information 2022. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.

The question regarding which atmospheric variables one should include in the training of a data-driven ocean circulation model is still an open research one. As an example, at the moment of writing, some competitive models use just the air temperature at 2 metres and the wind velocity at 10 metres above the surface ([El Aouni et al., 2024](https://arxiv.org/abs/2412.05454)), or even just the winds ([Wang et al., 2024](https://arxiv.org/abs/2402.02995)). Another obvious starting point is using the variables used by numerical models, as [NEMO](https://www.nemo-ocean.eu/doc/node27.html) or [MITgcm](https://mitgcm.readthedocs.io/en/latest/phys_pkgs/exf.html#ssub-phys-pkg-exf-inputs-units), an approach closer to that followed by [Cui et al., 2025](https://doi.org/10.1038/s41467-025-57389-2).

The wind stress, the evaporation, and the latent and sensible heat fluxes can be computed using bulk formulae (for a discussion of their parametrization in NEMO see [Bonino et al., 2022](https://doi.org/10.5194/gmd-15-6873-2022)), starting from the air density and pressure. In turn, the former can be computed from temperature and specific humidity. In particular, we included the dew point temperature at 2 metres above the surface, but not the lowest level of the 3D specific humidity, following the [ECMWF guidelines for computing the surface (2m) specific humidity](https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation#heading-Guidelines). Also, precipitation and the variables relevant for radiative transfer were included.

The temporal resolution of the ARCO-ERA5 dataset is 1 hour; therefore, it had to be resampled at a daily resolution. The instantaneous fields are averages of the 24 hours of each day (00:00 to 23:00 UTC). The accumulated fields (precipitation, radiation) are sums over the same hours: ERA5 stamps an hourly accumulation at the end of its hour, so they are moved back one hour first, and day D sums its own hours, not the last hour of the day before. At 0.25° the fields are on ERA5's own grid; at 0.5° and 1° they are regridded conservatively.

| Variable name | Description                                                      | Data type | Units | Assimilated |
|---------------|------------------------------------------------------------------|-----------|-------|-------------|
| `2t`          | Temperature of air at 2m                                         | float32   | K     | Yes         |
| `2d`          | Dew point temperature of air at 2m                               | float32   | K     | Yes         |
| `mslp`        | Mean sea level pressure                                          | float32   | Pa    | Yes         |
| `10u`         | Eastward wind velocity at 10m                                    | float32   | m/s   | Yes         |
| `10v`         | Northward wind velocity at 10m                                   | float32   | m/s   | Yes         |
| `ssrd`        | Shortwave radiation at surface (positive downward), daily total  | float32   | J/m^2 | No          |
| `strd`        | Longwave radiation at surface (positive downward), daily total   | float32   | J/m^2 | No          |
| `tp`          | Total precipitation (rain and snow), daily total                 | float32   | m     | Yes         |

Time invariants are read from the same ARCO-ERA5 store at one stamp, 2000-01-01 00:00, and stored once, without the time dimension. ERA5 stores them as hourly series of the same values (identical on 1993-01-01, 2000-01-01, 2010-07-01 and 2021-06-30), except `z` from 2022-10-01 on, which differs at the two polar rows. The climatology and the anomaly standard deviation leave them out, with the other static variables.

| Variable name | Description                                                      | Data type | Units   |
|---------------|------------------------------------------------------------------|-----------|---------|
| `z`           | Gravitational potential energy per unit mass at surface (static) | float32   | m^2/s^2 |
| `lsm`         | Fraction of land in a grid cell (static)                         | float32   | -       |

[^3]: Carver, Robert W, and Merose, Alex. (2023): ARCO-ERA5: An Analysis-Ready Cloud-Optimized Reanalysis Dataset.
22nd Conf. on AI for Env. Science, Denver, CO, Amer. Meteo. Soc, 4A.1, [https://ams.confex.com/ams/103ANNUAL/meetingapp.cgi/Paper/415842](https://ams.confex.com/ams/103ANNUAL/meetingapp.cgi/Paper/415842)

[^4]: Copernicus Climate Change Service, Climate Data Store, (2023): ERA5 hourly data on single levels from 1940 to present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). DOI: 10.24381/cds.adbb2d47 (Accessed on 10-Oct-2025)


### Rivers

Version 2 has no river discharge. Version 1 published GloFAS's river discharge (v4.0, `dis24`). GloFAS is distributed only by the Early Warning Data Store (EWDS), whose queue held requests for many hours at a time in November 2026. Version 2.1 will bring the rivers back, as the discharge of GloFAS v5.0 at the rivers' mouths (`dis24_outlets`). Its recipes and documentation are at the tag `rivers-last` of this repository, and the method is in the [notes on coarsening ocean datasets](docs/coarsen-ocean-datasets.md).

### Notes on regridding, null values, and masking

All fields are regridded conservatively with `xarray-regrid` ([Schilperoort et al., 2025](https://doi.org/10.5281/zenodo.15176942)), which averages the source cells under each target cell weighted by their overlap.

- Ocean fields: averages over the sea part of each cell. A cell is sea (has values) where `seafrac > 0`, i.e. where GLORYS12 has some sea cell: GLORYS12's 3D mask regridded is `seafrac`, so the domain is static and every regridded value has a cell. The few sea cells where GLORYS12 has no value (its gaps, the same every day) take the nearest value above in the same column, or 0 if none. Outside the sea, values are missing (NaN).
- Sea ice: averages over the sea part, no ice as 0 (section above).
- ERA5: values everywhere. The `land_sea_mask`, renamed `lsm`, is ERA5's fraction of land in each cell, which is not GLORYS12's sea: use `seafrac` for the ocean.

The [notes on coarsening ocean datasets](docs/coarsen-ocean-datasets.md) explain these choices, with measurements at 0.25°, 0.5° and 1°: which coarse cells to call sea, how the water of each layer is kept, how gaps are filled, sea ice, and river discharge (not in version 2).

Every block of the download is checked before it is written: a complete daily time axis, the grid convention, ocean and sea ice values exactly where `seafrac > 0` and every other variable everywhere, and a `long_name` and `units` on every variable, no two variables sharing a `long_name`. `configs/validate/historical.toml` checks a whole dataset the same way, given its dates: `arco-make validate --start 1993-01-01 --end 2026-07-01 configs/validate/historical.toml DATASET`.

The sources' versions, the limitations their producers document, and how they fit together (the ocean forced by another atmosphere before 2019) are in [docs/sources.md](docs/sources.md).

## Producing and extending the dataset

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

### Forecasts

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
which the [web page](#web-page) reads: the collection's state (`running`, `finished`, `aborted`),
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

### Checks

`uvx pre-commit run --all-files` runs the checks made before each commit: TOML and YAML syntax,
ruff, ty, ShellCheck, the web page's tests (`node --test`, Node.js from `uvx`), the scripts'
tests, REUSE and a secret scan. CI runs them on every pull request, and:

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

## Data format

Each resolution is an [Icechunk](https://icechunk.io) repository: a [Zarr version 3](https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html) dataset with versions, whose `main` branch is the current one. The dataset has the dimensions `time`, `depth`, `lat` and `lon` (and `bnds`, for the cell bounds), each with its coordinate. The latitudes increase within [-90, 90], and the longitudes are in the range [0, 360), following the [convention used by the ECMWF](https://confluence.ecmwf.int/display/CKB/ERA5%3A+What+is+the+spatial+reference#ERA5:Whatisthespatialreference-Coordinatesystem); the grid's polar rows are centred on the poles and half as tall. The depth coordinate is GLORYS12's level depths. The time coordinate uses the proleptic Gregorian calendar and unit "days since 1993-01-01" (UTC), one stamp per day at 00:00.

Variables are single precision floating point numbers, stored with time as the leading (slowest varying) dimension, followed by depth (when present), then latitude, and finally longitude. A chunk is one day and one level of a variable over the whole grid; chunks are grouped in shards of 8 days and all levels, a day's levels next to each other, so a whole profile of a day is read in a few requests. Chunks are compressed with Blosc (LZ4, level 1, byte shuffle). Static variables (`seafrac`, `deptho`, the cell measures, `z`, `lsm`) have no time dimension.

The forecast repositories have the dimensions `init_time` (the run, 00 UTC of its day),
`lead_time` (0 to 9 days), `depth`, `lat` and `lon`, and the coordinate `valid_time` (`init_time`
\+ `lead_time`, the day a value is for, as `time` in the historical dataset). A chunk is one run,
lead day and level over the whole grid; a shard holds a whole run. IFS daily means take 8
samples a day to day 5, then 4 (ERA5's: 24).

The statistics (the climatology and the anomaly standard deviation, from `scripts/climatology.sh`) are computed over the reference period 1993-2023, a 30-year normal as climatological normals are. Models evaluated on years inside it see them in their normalization.

The climatology and the anomaly standard deviation have 365 bins along `time`, the days of a 365-day year (0 = Jan 1). Feb 29 values are pooled with Feb 28 (bin 58), and the later days of leap years use the bin of the same date: to index them, take the day of year minus 1, and minus 1 more after Feb 29 in leap years. Each bin is smoothed with a Gaussian window of 29 days (scale 7 days), counting only the values present.

## Data access

ARCO-OCEAN is available via [AWS S3](https://aws.amazon.com/s3/) in the `s3://ogs-arco-ocean` bucket, one Icechunk repository per product and resolution: `historical/res=<res>` for the dataset and `statistics/res=<res>` for its statistics, with `<res>` one of `0p25`, `0p5` and `1p0`. The statistics repository has two groups, `climatology` and `anomaly_std`, written together in one version.

With a Python environment holding `xarray` and `icechunk` ([installation](https://icechunk.io/en/latest/)), a dataset is opened lazily, without credentials:

```python
import icechunk
import xarray as xr

storage = icechunk.s3_storage(
  bucket="ogs-arco-ocean",
  prefix="historical/res=0p25",
  region="eu-south-1",
  anonymous=True,
  # Icechunk waits 60 s by default for a stalled answer from S3; asking again sooner is faster.
  network_stream_timeout_seconds=20,
)
repo = icechunk.Repository.open(storage)
dataset = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
```

The statistics open the same way from `statistics/res=<res>`, one group at a time (`xr.open_zarr(store, group="climatology", consolidated=False)`, or `group="anomaly_std"`), or both together with `xr.open_datatree(store, engine="zarr", consolidated=False)`.

A download writes its blocks one commit at a time on a branch of its own, and `main` moves to the last of them only once the run is complete: `main` is always a whole version. The previous version is kept for a while (the recipes' `keep_versions = 2`); `main`'s history also lists the commits of single blocks, which are not whole versions.

The first version of ARCO-OCEAN (0.25°, 10 levels, waves, Zarr version 2) stays in the bucket until the new one replaces it; its description is in this repository's history.

## Tutorials

1. [Computing the Oceanic El Nino Index (ONI) with Xarray and ARCO-OCEAN](tutorials/oni.py) (written for the first version: its paths and variables are those of the 0.25°, 10-level dataset)

The tutorials are [marimo](https://marimo.io) notebooks: `uvx marimo edit --sandbox tutorials/oni.py` opens one in an environment of its own, with the dependencies it lists.

## Web page

`site/` is the web page of ARCO-OCEAN (<https://stefanocampanella.github.io/arco-ocean/>):
static files without a build step, deployed to GitHub Pages from `main` by
`.github/workflows/pages.yml` (Pages enabled once, with "GitHub Actions" as source). Besides the dataset's description, it shows the state of the forecast collection,
read every minute from its heartbeat (above): downloading, finished, stale or aborted, and each
resolution's newest run. `site/status.js` decides the state; `site/dashboard.js` shows it. To
preview it, serve the directory (`python -m http.server -d site`, module scripts do not load from
`file://`); `?status=URL` reads another heartbeat, e.g. the test copy in the bucket's
`experiments/status/forecast.json`.

## License

The datasets (historical, statistics and forecasts) are released under the Creative Commons Attribution 4.0 International licence, CC BY 4.0 ([summary](https://creativecommons.org/licenses/by/4.0/), [legal code](https://creativecommons.org/licenses/by/4.0/legalcode)). They are derived from the sources below, whose licences ask that they be credited: each dataset's global `attribution` attribute does so, in the forms the licences prescribe, and must accompany any redistribution of the data or of products derived from them.

| Source | In | Licence | Credit required |
|---|---|---|---|
| GLORYS12, Copernicus Marine Service ([10.48670/moi-00021](https://doi.org/10.48670/moi-00021)) | historical, statistics: ocean, sea ice | [Copernicus Marine Service licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence) | "Generated using E.U. Copernicus Marine Service Information", with the DOIs, visible where the data are accessed |
| GLO12, Copernicus Marine Service ([10.48670/moi-00016](https://doi.org/10.48670/moi-00016)) | forecasts: ocean, sea ice | as GLORYS12 | as GLORYS12 |
| ERA5, Copernicus Climate Change Service ([10.24381/cds.adbb2d47](https://doi.org/10.24381/cds.adbb2d47)) | historical, statistics: atmosphere; forecasts: static fields | CC BY 4.0 | "Contains modified Copernicus Climate Change Service information [year]" |
| ECMWF IFS open data ([data.ecmwf.int](https://data.ecmwf.int/forecasts/), read from its copy on AWS) | forecasts: atmosphere | CC BY 4.0 and the [ECMWF terms of use](https://apps.ecmwf.int/datasets/licences/general/) | "based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)" |

The Copernicus Marine Service licence (clause 2.6) asks that its record-keeping requirement be passed on: users of the ocean and sea-ice variables are asked to keep records of their use of the data, enough to document and trace it, and to make them available to the Copernicus Marine Service on reasonable notice.

The code of this repository (scripts, recipes, documentation) is released under the MIT licence ([LICENSE](LICENSE)); the ONI tutorial, adapted from [Climatematch](https://comptools.climatematch.io/)'s, under its licences, CC BY 4.0 for the text and the BSD 3-Clause License for the code. The animation and the icon in `assets/` show the dataset's values: they are released under CC BY 4.0, as the data, with the credit given under the animation above.

## Use of AI tools

The recipes, scripts and documentation of this repository have been written largely with AI coding assistants (Claude Code, by Anthropic), directed and reviewed by the maintainers, as has [arco-make](https://github.com/stefanocampanella/arco-make), the tool that produces the datasets. The recipes' outputs were checked on real data before the production run (arco-make's logbook records the checks). The commits made with an assistant name it in a `Co-Authored-By` trailer. The maintainers are responsible for the datasets and the code as published: please report problems as issues.

## Suggested attribution

[//]: # (FIXME: Temporary. Come up with a better attribution)
```
Campanella, S., Salon, S., Querin, S., and Bortolussi, L.: ARCO-OCEAN: A dataset of physical properties of the ocean and sea ice, with hydrological and atmospheric forcing, optimized for machine learning. https://doi.org/10.5281/zenodo.17751608
```
