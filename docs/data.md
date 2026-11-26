---
license: CC-BY-4.0
---

# Data

ARCO-OCEAN is an analysis-ready cloud-optimized ([Abernathey et al., 2021](https://doi.org/10.1109/MCSE.2021.3059437)) dataset providing physical properties of the ocean and sea ice for a period of about 33 years, from the 1st of January 1993 to the 30th of June 2026, the last day every source gives as final data (November 2026). The dataset includes also atmospheric variables that would be needed as boundary conditions and used to drive a numerical simulation. The dataset is the result of collecting, processing, merging and optimizing for the cloud different data sources, all retrospective analyses (reanalyses) or hindcasts of different Earth system components.

The fields are given on regular latitude-longitude grids at three horizontal resolutions: 0.25°, 0.5° and 1°. The finest is the resolution of most state-of-the-art machine learning weather forecasting models trained on the retrospective analysis ERA5 ([Hersbach et al., 2020](https://doi.org/10.1002/qj.3803)), and ERA5's own grid; the coarser ones are made from the same sources, not from the 0.25° data, so that every coarse cell keeps the water and ice of the source cells under it. Many of the variables in ARCO-OCEAN were originally defined on an Arakawa C grid and afterward interpolated on cell centers before being further postprocessed and ingested in the dataset. Please refer to the documentation of individual source datasets for more details. Also, see the section on regridding below.

The temporal resolution of ARCO-OCEAN is 1 day. The simulation timestep of numerical models is usually much less than that, and source datasets distribute either system state snapshots or time averages (or accumulations, e.g., for precipitation) at lower temporal resolutions. On top of that, the ARCO-OCEAN postprocessing further reduces the temporal resolution of some of these datasets. Individual sections of documentation provide more details.

Indeed, the dataset has been designed to train a machine learning forecasting model and takes inspiration from similar datasets, like ARCO-ERA5 ([Carver et al., 2023](https://ams.confex.com/ams/103ANNUAL/meetingapp.cgi/Paper/415842)). In light of this, design choices made are motivated in the following, and more precise information on how to reproduce the ARCO-OCEAN dataset is provided: the recipes are in `configs/download/`, the scripts that run them in `scripts/`, and the program is [arco-make](https://github.com/stefanocampanella/arco-make).

## Ocean and sea ice

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

Ocean and sea ice values exist exactly where `seafrac > 0`. Volumes and heat contents are sums of value × `volcello`; areas use `areacello`. The variables name these weights in `cell_measures`. How these fields are built, and why, is in the [notes on coarsening ocean datasets](coarsen-ocean-datasets.md).

[^1]: Global Ocean Physics Reanalysis. E.U. Copernicus Marine Service Information (CMEMS). Marine Data Store (MDS). DOI: 10.48670/moi-00021 (Accessed on 10-Oct-2025)

## Waves

WAVERYS wave variables were part of the first version and are no longer included: their sea and ice masks differ from GLORYS12's (no sea north of about 81°N, waves missing where ERA5's ice cover exceeds about 0.3). The findings are kept in the notes on coarsening.

## Atmospheric

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


## Rivers

Version 2 has no river discharge. Version 1 published GloFAS's river discharge (v4.0, `dis24`). GloFAS is distributed only by the Early Warning Data Store (EWDS), whose queue held requests for many hours at a time in November 2026. Version 2.1 will bring the rivers back, as the discharge of GloFAS v5.0 at the rivers' mouths (`dis24_outlets`). Its recipes and documentation are at the tag `rivers-last` of this repository, and the method is in the [notes on coarsening ocean datasets](coarsen-ocean-datasets.md).

## Notes on regridding, null values, and masking

All fields are regridded conservatively with `xarray-regrid` ([Schilperoort et al., 2025](https://doi.org/10.5281/zenodo.15176942)), which averages the source cells under each target cell weighted by their overlap.

- Ocean fields: averages over the sea part of each cell. A cell is sea (has values) where `seafrac > 0`, i.e. where GLORYS12 has some sea cell: GLORYS12's 3D mask regridded is `seafrac`, so the domain is static and every regridded value has a cell. The few sea cells where GLORYS12 has no value (its gaps, the same every day) take the nearest value above in the same column, or 0 if none. Outside the sea, values are missing (NaN).
- Sea ice: averages over the sea part, no ice as 0 (section above).
- ERA5: values everywhere. The `land_sea_mask`, renamed `lsm`, is ERA5's fraction of land in each cell, which is not GLORYS12's sea: use `seafrac` for the ocean.

The [notes on coarsening ocean datasets](coarsen-ocean-datasets.md) explain these choices, with measurements at 0.25°, 0.5° and 1°: which coarse cells to call sea, how the water of each layer is kept, how gaps are filled, sea ice, and river discharge (not in version 2).

Every block of the download is checked before it is written: a complete daily time axis, the grid convention, ocean and sea ice values exactly where `seafrac > 0` and every other variable everywhere, and a `long_name` and `units` on every variable, no two variables sharing a `long_name`. `configs/validate/historical.toml` checks a whole dataset the same way, given its dates: `arco-make validate --start 1993-01-01 --end 2026-07-01 configs/validate/historical.toml DATASET`.

The sources' versions, the limitations their producers document, and how they fit together (the ocean forced by another atmosphere before 2019) are in [docs/sources.md](sources.md).

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
