---
title: ARCO-OCEAN
subtitle: The ocean and sea ice with their atmospheric forcing, analysis-ready and cloud-optimized, for machine learning
---

ARCO-OCEAN gives the ocean state and its forcing on regular latitude-longitude grids at 0.25°,
0.5° and 1°, one value a day, from 1 January 1993 to 30 June 2026: the ocean and sea ice from the
GLORYS12 reanalysis (49 levels, to 5275 m) and the atmosphere from ERA5. Each coarse resolution is
made from the sources, so that every cell keeps the water and ice of the source cells under it.
Daily forecasts of the same variables, from the operational systems of the same producers,
continue it. It is stored as [Icechunk](https://icechunk.io/) repositories on AWS S3, readable
without credentials ([Data access](access.md)).

:::{figure} assets/images/arco-ocean.png
:alt: The globe on 1 January 2023: sea surface temperature and sea ice from ARCO-OCEAN
:width: 480px
:align: center

Sea surface temperature (`thetao`, top level) and sea ice (`siconc`, white) on 1 January 2023 at
0.25°; [the globe turning through the year](assets/images/arco-ocean.webp), day by day (8 MB,
on request: no motion nor download unless asked for). Generated using E.U. Copernicus Marine
Service Information ([10.48670/moi-00021](https://doi.org/10.48670/moi-00021)).
:::

The availability of standard datasets and benchmarks has been a key factor in the development
of new machine learning methods and models, including those applied to weather forecasting and
climate science ([Rasp et al., 2023](https://arxiv.org/abs/2308.15560),
[Watson-Parris et al., 2022](https://doi.org/10.1029/2021MS002954)). ARCO-OCEAN aims to provide a
representative, and to some extent comprehensive, dataset for training machine learning models to
forecast the ocean state. It is the first to include both the ocean state and its forcing, and
has been designed having in mind coupled atmosphere-ocean models for Subseasonal-to-Seasonal (S2S)
forecasts ([Campanella et al., 2025](https://www.climatechange.ai/papers/iclr2025/81)); future
extensions could include variables related to climate, like biogeochemistry.

## Products

One Icechunk repository per product and resolution in the `s3://ogs-arco-ocean` bucket (region
`eu-south-1`), at `<product>/res=<res>`, with `<res>` one of `0p25`, `0p5` and `1p0`.

| Product | Path | Content |
|---|---|---|
| Historical | `historical/res=<res>` | Daily values, 1993-01-01 to 2026-06-30: GLORYS12 (temperature, salinity, currents, sea surface height, sea ice), ERA5 (2 m temperature and dew point, sea-level pressure, 10 m wind, radiation, precipitation), and the cells' geometry (sea fraction, areas, volumes, bounds). [Data](data.md) |
| Statistics | `statistics/res=<res>` | The climatology and the standard deviation of the anomalies over 1993–2023, by day of the year (groups `climatology` and `anomaly_std`). |
| Forecast | `forecast/res=<res>` | The daily 00 UTC runs, 10 lead days, the last five years of runs: GLO12 and IFS HRES, on the historical dataset's grids and variables, with a flag per component. [Forecasts](forecasts.md) |

## Historical downloads

The historical dataset is downloaded once at each resolution, block after block (32 days each),
into its repository; each is published when every block is stored. Their progress, read from the
repositories, is updated every five minutes while a download runs. The headline names the
resolution that needs attention first: failed, then stale, then downloading.

:::{anywidget} assets/js/status.js
:css: assets/js/status.css
{"show": "historical"}
:::

States: **downloading** (updated recently), **finished**, **failed** (the download stopped; it
is resumed by hand), **stale** (no update for more than 15 minutes, without an end: the machine
down or the process killed).

## Statistics

The climatology and the anomaly standard deviation are computed once at each resolution, from
the historical dataset, and written in one commit at the end: they have a state (computing,
finished, failed), not a progress.

:::{anywidget} assets/js/status.js
:css: assets/js/status.css
{"show": "statistics"}
:::

States: **computing** (updated recently), **finished**, **failed** (the computation stopped; it
is rerun by hand), **stale** (no update for more than 15 minutes, without an end).

## Forecast collection

A collection every day adds the day's forecast run to the forecast repositories, at every
resolution. Its state is read from the heartbeat it publishes while it runs.

:::{anywidget} assets/js/status.js
:css: assets/js/status.css
{"show": "forecast"}
:::

States: **downloading** (heartbeat recent), **finished**, **aborted** (the collection failed;
the next one resumes it), **stale** (the heartbeat stopped without an end, or no collection has
finished for more than a day, or a resolution is behind). "Own forecast" is the share of the
newest run's lead times that each component's run gives; the rest comes from later releases
(GLO12, for runs collected after their day) or is missing.

## Documentation

- [Data](data.md): every variable, its source and how it is made; the format.
- [Data access](access.md): opening the repositories; the tutorials.
- [The sources](sources.md): their versions, the limitations their producers document, and how
  they fit together.
- [Coarsening ocean datasets](notebooks/coarsening.ipynb): the sea fraction, the fills, the sea
  ice and the river outlets (not in version 2).
- [Producing and extending the dataset](producing.md) and [Forecasts](forecasts.md): the scripts,
  the recipes, the daily collection and its alerts.
- [Licence](licence.md): the datasets' and the code's, the credits the sources ask for, and how
  to cite ARCO-OCEAN.
- [Development](development.md): the checks, this site, the use of AI tools.
- [arco-make](https://github.com/stefanocampanella/arco-make), the program that builds
  ARCO-OCEAN from its recipes (`configs/`).

Neither the European Commission nor ECMWF nor Mercator Ocean International is responsible for any
use that may be made of the Copernicus information or data ARCO-OCEAN contains.
