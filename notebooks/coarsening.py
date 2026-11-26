# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
# Coarsening ocean datasets: the notes, their examples (checked: asserts), and the measurements
# behind their figures (run on demand). A marimo notebook: `uv run marimo edit
# notebooks/coarsening.py`; `uv run python notebooks/coarsening.py` runs the examples (CI);
# `-- --live` adds those on the real sources; `-- --measure RES --out FILE` and `-- --tables
# FILES` run the measurements and print their tables.

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import json
    import pathlib
    import sys
    from collections.abc import Callable
    from typing import Any

    import marimo as mo
    import numpy as np
    import xarray as xr
    from arcomake import processing_utils as pu
    from arcomake import settings
    from arcomake.temporary_utils import TempDirectoryRegistry

    STATIC = "cm://cmems_mod_glo_phy_my_0.083deg_static"
    DAILY = "cm://cmems_mod_glo_phy_my_0.083deg_P1D-m"
    STATIC_KW = {"engine": "copernicusmarine", "dataset_version": "202311", "service": "static-arco"}
    WAVES = "cm://cmems_mod_glo_wav_my_0.2deg_PT3H-i"
    WAVES_STATIC = "cm://cmems_mod_glo_wav_my_0.2deg_static"
    ERA5 = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
    GLOFAS_AUX = "https://confluence.ecmwf.int/download/attachments/242067380"
    LEVELS = [0, 10, 20, 30, 40, 45, 47, 48, 49]
    LEFT_OUT = [10, 20, 30, 40, 45, 47, 48]
    DAY = "2013-01-01"
    ICE_DAY = "2013-03-01"
    GAP_DAYS = ["1993-01-01", "2013-01-01", "2021-06-30"]


@app.cell
def _():
    # The examples on the real sources (Copernicus Marine credentials): `-- --live`.
    LIVE = "live" in mo.cli_args()
    return (LIVE,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Coarsening ocean datasets

    How [arco-make](https://github.com/stefanocampanella/arco-make)'s steps carry a z-level ocean
    model (GLORYS12), its sea ice, and river discharge (GloFAS) to coarser regular grids, and what
    the published fields mean. Written for ARCO-OCEAN (0.25°, 0.5° and 1° from GLORYS's 1/12°),
    whose recipes are in `configs/download`; the steps are generic (arco-make's `docs/steps.md`).

    Every statement with a number is backed by code, in this notebook (`notebooks/coarsening.py`,
    a [marimo](https://marimo.io) notebook), run with arco-make (the project's environment, `uv sync`):

    - the examples below run on synthetic data, and check their results (`assert`): every run of
      the notebook checks them (`uv run python notebooks/coarsening.py`, and in CI);
    - the examples on the real sources read small boxes, with Copernicus Marine credentials: they
      run with `-- --live`;
    - the global figures come from the notebook's measurements, run at each resolution with
      `-- --measure RES --out FILE.json` (section Measurements, at the end; needs the services'
      credentials, about 30 GB at 0.25°, and an ecCodes recent enough for GloFAS GRIB:
      `uv run --with eccodeslib`), shown as the tables below with `-- --tables A.json,B.json,...`;
      their numbers are those of the days they read.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Setting

    GLORYS12 is NEMO on a z-level grid: 50 levels of fixed thickness (`e3t`, 1 m at the surface,
    458 m at the bottom), each native cell sea or land at each level. A coarse cell covers many native
    cells (3 × 3 at 0.25°, 6 × 6 at 0.5°, 12 × 12 at 1°), whose sea floors lie at different depths.

    `regrid` with `method = "conservative"` averages the native cells under each coarse cell,
    weighted by their overlap and by latitude (cell areas on a sphere, xarray-regrid). Missing values:

    - `skipna = false` counts them as 0 (land as depth 0, no ice as 0 concentration): the average
      is over the whole coarse cell;
    - `skipna = true` averages the valid part only, and leaves NaN where the valid share is below
      `1 - nan_threshold`: `nan_threshold = 1` keeps a value wherever one native cell has one,
      `nan_threshold = 0` only where all have one.

    ```python
    # xarray-regrid 0.4.2, methods/conservative.py (abridged)
    if skipna:
      valid_frac = xr.dot(da.notnull(), *weight_arrays, dim=list(weights.keys()))
    da_regrid = xr.dot(da.fillna(0), *weight_arrays, dim=list(weights.keys()))
    if skipna:
      da_regrid /= valid_frac
      da_regrid = da_regrid.where(valid_frac >= get_valid_threshold(nan_threshold))
    ```

    Two behaviours of xarray-regrid matter below: target cells whose centre lies outside the range
    of the source's centres are NaN even where they overlap source cells (all methods); a source cell
    straddling target cells is split by its overlap in degrees, not in area (1e-7 of a total for
    0.05° cells on a 0.25° grid).

    ## 2. Layer faces

    The static product gives `e3t`, one thickness per level (no partial cells): the faces are
    `[0, cumsum(e3t)]`. `get_sea_mask` rebuilds them from the level centres instead, each centre
    mid-layer; the two differ by up to 2 m at depth, enough to move a few thousand coarse cells
    across a rule's cut (see Measurements, below).

    ## 3. GLORYS's own sea cells

    GLORYS's 3D `mask` marks a native cell sea where its depth `deptho` lies below the level's
    centre: the cell is sea when water fills more than half of it. The model's bottom cell is
    rounded to the nearest face. The relation holds everywhere but in a few tens of thousands of
    cells (34,615), in one direction only (the rule says sea, the mask says land), and `mask` is exactly
    "level below `deptho_lev`":
    """)
    return


@app.cell
def _():
    mo.stop(not LIVE, mo.md("_On the real sources: run with `-- --live`, with Copernicus Marine credentials._"))
    box = {"latitude": slice(-12, 12), "longitude": slice(95, 135)}  # Maritime Continent
    st = (
      xr.open_dataset(STATIC, variables=["deptho", "deptho_lev", "mask"], dataset_part="bathy", **STATIC_KW)
      .sel(box)
      .load()
    )
    mask = st["mask"].values.astype(bool)
    _rule = np.nan_to_num(st.deptho.values)[None] > st.depth.values[:, None, None]
    # Never sea for the mask and land for the rule.
    assert not (mask & ~_rule).any()
    _k = np.arange(mask.shape[0])[:, None, None]
    assert (mask == (_k < np.nan_to_num(st.deptho_lev.values)[None])).all()
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    The deepest level (49, centre 5,728 m) is sea in the mask but never has values: NEMO "has at most
    jpk-1 t-points inside the ocean, the additional t-point at jk = jpk is below the sea floor and
    is not used" (NEMO 3.6 manual, §4.3.2). Other cells marked sea without values (gaps) are few,
    and the same every day (see Measurements, below):
    """)
    return


@app.cell
def _():
    mo.stop(not LIVE, mo.md("_On the real sources: run with `-- --live`, with Copernicus Marine credentials._"))
    _day = xr.open_dataset(
      DAILY,
      engine="copernicusmarine",
      variables=["thetao"],
      start_datetime="2013-01-01",
      end_datetime="2013-01-01",
    )
    _t = _day.thetao.isel(time=0).sel(box).load()
    assert int(mask[49].sum()) > 0 and int(_t.isel(depth=49).notnull().sum()) == 0
    # No value outside the mask.
    assert int((_t.notnull().values & ~mask).sum()) == 0
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ARCO-OCEAN publishes 49 levels: level 49 is dropped.

    ## 4. Column water and mean depth

    With land as depth 0, the conservative mean of `deptho` times the coarse cell's area is the water
    volume of the column: the mean depth is the column's water, not a proxy for it. The water of each
    native column, split by layer, adds up to its depth; averaging and summing over layers are both
    linear, so the mean of the layers' water adds up to the mean depth. Only depths below the last
    face (trenches below 5,958 m) break the identity.

    ## 5. Water per layer: a worked example

    One coarse cell made of four native cells of equal area, four layers of 10 m; the native depths
    are 0, 0, 8 and 40 m (two land cells, a shelf, a channel):
    """)
    return


@app.cell
def _():
    faces = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    top, h = faces[:-1], np.diff(faces)
    centres = (faces[:-1] + faces[1:]) / 2
    depths = np.array([0.0, 0.0, 8.0, 40.0])
    water = (np.clip(depths[:, None] - top, 0, h) / h).mean(axis=0)  # share of each layer
    assert np.allclose(water, [0.45, 0.25, 0.25, 0.25])
    mean_depth = depths.mean()
    assert (float(mean_depth), float((water * h).sum())) == (12.0, 12.0)  # the column identity
    assert np.allclose(np.clip(mean_depth - top, 0, h) / h, [1.0, 0.2, 0.0, 0.0])  # a flat column of 12 m
    fraction = (depths[:, None] > centres).mean(axis=0)  # GLORYS's mask, regridded
    assert np.allclose(fraction, [0.5, 0.25, 0.25, 0.25])
    assert float((fraction * h).sum()) == 12.5
    {"water": water, "flat column": np.clip(mean_depth - top, 0, h) / h, "fraction": fraction}
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    | | Layer 0 | Layer 1 | Layer 2 | Layer 3 | Column |
    |---|---|---|---|---|---|
    | Water in the layer (share of the cell) | 0.45 | 0.25 | 0.25 | 0.25 | 12 m |
    | Flat column of the mean depth | 1.00 | 0.20 | 0 | 0 | 12 m |
    | GLORYS's mask regridded (`seafrac`) | 0.50 | 0.25 | 0.25 | 0.25 | 12.5 m |

    - **The fraction** (`seafrac`) is GLORYS's 3D mask regridded conservatively: the share of the
      coarse cell's area where the model has a sea cell at that level. Times the layer's volume, it
      is the water GLORYS has there; summed over layers, the column's water (12.5 m against 12: the
      shelf's 8 m count as a full 10 m layer, below).
    - **The flat column** spreads the mean depth evenly: it moves water from the layers that cross
      the sea floor inside the cell up to the layers above (layer 0 full, layers 2 and 3 empty though
      the channel fills them). What it adds above is what it removes below, so the column totals
      agree; the layers differ wherever a layer crosses the sea floor inside a coarse cell: coasts,
      slopes, ridges, seamounts, at any depth.

    The fraction holds the column's water and its split by layer; the mean depth holds only the
    total.

    ## 6. Rules: which coarse cells are sea

    A rule turns the water of a cell and layer into sea or land:
    """)
    return


@app.cell
def _():
    # current: the mean depth below the layer's centre
    assert (mean_depth > centres).tolist() == [True, False, False, False]
    # majority: at least half of the layer is sea
    assert (fraction >= 0.5).tolist() == [True, False, False, False]
    # any water
    assert (fraction > 0).tolist() == [True, True, True, True]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    - **Current** (the recipes until 2026: `get_sea_mask` on the regridded depth, `threshold = 0.5`)
      is GLORYS's own rule applied to a flat column. It guarantees "more than half water" only for a
      flat-bottomed cell; at 0.25° 8,869 surface cells it calls sea are less than half sea,
      and at depth cells more than half sea are called land (see Measurements, below).
    - **Majority** rounds each layer: it keeps each layer's water within half a percent down to
      4,800 m at 0.25°.
    - **Any water** (ARCO-OCEAN's choice) keeps every cell where the model has some sea, so that
      every regridded value has a cell, and publishes `seafrac` with it: users weight by the
      fraction, or mask at another threshold (`seafrac >= 0.5` is the majority rule).

    `fraction_mask` builds the mask: `threshold` (default 0) and `inclusive` choose the rule, and
    `tolerance` (default 1e-6) clears round-off left by the regridding weights where a coarse cell
    barely touches the source's cells:
    """)
    return


@app.cell
def _():
    _ds = xr.Dataset({"seafrac": ("depth", np.array([0.5, 0.25, 1e-8, 0.0]))})
    _out = pu.fraction_mask(_ds, fraction="seafrac", mask_name="sea")
    assert np.allclose(_out.seafrac.values, [0.5, 0.25, 0.0, 0.0])
    assert _out.sea.values.tolist() == [True, True, False, False]
    _majority = pu.fraction_mask(_ds, fraction="seafrac", mask_name="sea", threshold=0.5, inclusive=True)
    assert _majority.sea.values.tolist() == [True, False, False, False]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    No 0/1 mask conserves water: each rounds every cell and layer. The current rule rounds the
    flat column to the nearest face (right in total, wrong by layer); majority rounds each layer;
    any water rounds up. Only the fraction conserves water layer by layer.

    **Inclusion.** If the mean depth lies below a layer's centre, some native column does too, and
    is sea there: the current mask is inside the any-water mask, and its cells are empty only where
    GLORYS itself has a gap.

    **The footnote** (of the notebook these notes replace, `notebooks/regrid_glorys12.ipynb`). A
    coarse value regridded with `nan_threshold = 0` lies inside the current mask, whatever its
    threshold: every native cell under it has a value, hence is sea, hence lies deeper than the
    threshold depth, and so does their weighted mean. Premises: native values
    lie inside the native rule's mask; the weights of a coarse cell sum to 1; land counts as 0. On
    random bathymetries:
    """)
    return


@app.cell
def _():
    _rng = np.random.default_rng(0)
    _fine = _rng.choice([0.0, 3.0, 12.0, 27.0, 45.0], size=(1000, 4))  # 1000 coarse cells
    for _threshold in (0.0, 0.25, 0.5, 0.75, 1.0):
      _cut = _threshold * top + (1 - _threshold) * faces[1:]  # the rule's depth per layer
      _all_sea = (_fine[:, :, None] > _cut).all(axis=1)  # a value with nan_threshold 0
      _current = _fine.mean(axis=1)[:, None] > _cut
      assert (_all_sea <= _current).all(), _threshold
    assert ((_fine.mean(axis=1)[:, None] > centres) <= (_fine[:, :, None] > centres).any(axis=1)).all()
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    The same holds on GLORYS (one day at 0.25°, see Measurements, below): no native value
    outside the native rule's mask, no regridded value outside the current mask.

    ## 7. `nan_threshold`

    Natively, values exist exactly at GLORYS's sea cells, except its gaps. Regridded with
    `nan_threshold = 1`, a coarse cell has a value wherever one native cell under it has one: exactly
    the any-water cells, except where all their native sea cells are gaps. With 0, only where every
    native cell has one: a coarse cell touching the coast or the sea floor has none. ARCO-OCEAN uses
    1, with the any-water rule: values and sea cells coincide.

    ## 8. Volumes, partial cells, and Samudra

    A mask counts a sea cell as a full layer. GLORYS's bottom cells are sea when more than half
    full, so its mask rounds each column to the nearest face and the errors cancel (native mask
    volume against `deptho`: -0.1 %). OM4, the model behind the Samudra emulator, counts partly
    filled bottom cells as full, which overstates the volume (about 10 %, Samudra's notes). A
    fraction computed from `deptho` with partial cells would put water where GLORYS has no cell and
    no value; the fraction ARCO-OCEAN publishes is GLORYS's mask regridded, which describes where the
    data are.

    ## 9. Gaps and filling

    With level 49 dropped, a sea cell (any water) lacks a value only where all its native sea cells
    are GLORYS gaps: a few thousand cells, the same every day. They are filled from the nearest value
    above in the same column (`fill_from_above`), velocities included; cells with nothing above get
    0 (`masked_fill`):
    """)
    return


@app.cell
def _():
    _col = xr.Dataset(
      {"t": ("depth", [4.0, np.nan, 2.0, np.nan]), "sea": ("depth", [True, True, True, True])}
    )
    _filled = pu.fill_from_above(_col, variables=["t"], depth_dim="depth", mask_name="sea").t.values
    assert _filled.tolist() == [4.0, 4.0, 2.0, 2.0]
    _filled
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    The recipes used to fill with the native bottom value of each column, regridded: under a coarse
    cell this averages bottoms at different depths (a shelf edge and a plain), so a gap may get
    water from far above it. Leaving one level out and refilling it, filling from above has
    the lower error at every level tested (see Measurements, below).

    Elsewhere: horizontal extension from neighbouring sea cells (SOSIE's DROWN; CDO's `setmisstonn`,
    `setmisstodis`; xESMF's `nearest_s2d`, `inverse_dist`, `creep_fill`), Laplace extension, or
    leaving cells below the bottom missing (HYCOM's `layer2z`); remapping studies stress the boundary
    treatment (White et al. 2009). A vertical fill always has a source for the gaps of GLORYS.

    GLORYS was cut to latitudes -76.9167 to 89.9167 in earlier recipes: the rows south of it and the
    row at 90° are sea in the static mask without any value. Without the cut, no coarse sea cell is
    left empty by them (values come from the neighbouring rows, `nan_threshold = 1`), and the
    round-off fractions that the cut caused near the equator disappear; the recipes read all rows.

    ## 10. Sea ice

    GLORYS gives `siconc` (concentration) and `sithick` (thickness) NaN where there is no ice, and
    `usi`, `vsi` (velocity) 0 there; all four have `cell_methods = "area: mean where sea_ice"`:
    thickness and velocity are means over the ice-covered part, as in CMIP, where averages of
    thickness are weighted by concentration (Notz et al. 2016).

    ARCO-OCEAN publishes, over the sea part of each coarse cell:

    - `siconc`: ice area / sea area;
    - `sivol`: concentration × thickness, ice volume per unit sea area (m);
    - `usic`, `vsic`: concentration × velocity.

    Built with `products` on the native grid, `regrid` with `skipna = false` (missing as 0), and
    `divide_by` the surface `seafrac`. GLORYS's quantities come back exactly: thickness is
    `sivol / siconc` and velocity `usic / siconc` where `siconc > 0`, the means over the ice cover:
    """)
    return


@app.cell
def _():
    _ice = xr.Dataset(
      {  # three native cells: ice, open sea, land
        "siconc": ("x", [0.8, np.nan, np.nan]),
        "sithick": ("x", [2.0, np.nan, np.nan]),
        "seafrac": ("x", [1.0, 1.0, 0.0]),
      }
    )
    _native = pu.products(_ice, sivol=["siconc", "sithick"])
    _coarse = _native.fillna(0).mean("x")  # a conservative mean over one coarse cell
    _coarse = pu.divide_by(_coarse, variables=["siconc", "sivol"], by="seafrac")
    assert np.allclose(
      (float(_coarse.siconc), float(_coarse.sivol), float(_coarse.sivol / _coarse.siconc)), (0.4, 0.8, 2.0)
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Times `seafrac`, these fields are means over whole cells of native quantities (c, c h, c u), which
    regrid linearly: coarsening them again (to 1°, say) gives what regridding the native fields gives.
    They are 0 where there is no ice, continuous across the ice edge, and their area-weighted sums
    (times `seafrac`) are the ice area and volume.

    ## 11. River discharge into the ocean

    Not published in version 2 ([Data, Rivers](data.md)): this is the method of version 2.1.

    GloFAS gives the daily discharge (m³/s) of every land cell of its 0.05° grid. Discharge is not
    additive across cells (a river's cell already holds its tributaries): averaging the cells of a
    coarse cell mixes a main channel with hillslopes, a fifth of the main river at 0.25°, and less at
    coarser grids. What the ocean receives is the discharge at the rivers' mouths.

    GloFAS's local drain directions (LDD, the PCRaster convention: each cell points to its downstream
    neighbour, 5 marks a pit, where the flow ends) give the mouths: the pits. ARCO-OCEAN publishes
    `dis24_outlets`, the discharge at the pits as a flux per unit area of the coarse cell, in metres
    per day like a daily precipitation total:

    1. the LDD joins the discharge as a static part of the GloFAS dataset (`rename`,
       `coordinate_tolerance`: its coordinates differ from the discharge's by 4e-12);
    2. `keep_where` keeps the discharge at the pits, 0 elsewhere;
    3. `per_unit_area` divides by each native cell's area (times 86400: metres per day);
    4. `regrid`, conservative, `skipna = false`, with `conservation_tolerance`: a pit straddling
       coarse cells is split by overlap, and the total must be kept.
    """)
    return


@app.cell
def _():
    _lat, _lon = np.arange(-0.875, 1.0, 0.25), np.arange(0.125, 2.0, 0.25)
    _q = np.zeros((_lat.size, _lon.size))
    _q[3, 4], _q[6, 1] = 1000.0, 40.0  # two pits, m3/s
    _pits = xr.Dataset({"q": (("latitude", "longitude"), _q)}, coords={"latitude": _lat, "longitude": _lon})
    _density = pu.per_unit_area(_pits, variables=["q"])
    _grid = {
      "south": -0.75,
      "north": 0.75,
      "west": 0.25,
      "east": 1.75,
      "resolution_lat": 0.5,
      "resolution_lon": 0.5,
    }
    _coarse = pu.regrid(
      _density, grid=_grid, method="conservative", kwargs={"skipna": False}, conservation_tolerance=1e-6
    )
    _total = float((_coarse.q * pu.cell_areas(_coarse.latitude.values, _coarse.longitude.values)).sum())
    assert round(_total, 6) == 1040.0
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Checks: the upstream area at the pits equals the land area (every cell drains to one pit;
    1.00006 for GloFAS v4.0's network); the total at the pits equals the total of the coarse field
    (`conservation_tolerance`). GloFAS v5.0 publishes no LDD: the v4.0 one is used, on the same
    6,221,926 cells as v5.0's discharge. Pits whose basin ends inland (the Caspian, Lake Chad, the
    Okavango) stay in. The ocean model can link pits to its coast (Moby-Dick's
    graph does): the dataset does not move them to sea cells.

    The inland discharge (`dis24`), its mask and `uparea` are no longer published.

    ## 12. WAVERYS (not published)

    WAVERYS (CMEMS's wave reanalysis, MFWAM on ERA5 winds and ice) was dropped from ARCO-OCEAN.
    Findings, measured on 1 Mar and 15 Sep 2013 (the measurements' section `waverys`):

    - its sea (static depth, land NaN) differs from GLORYS's: none in the central Arctic (north of
      about 81°N), in a block of the Canadian Archipelago and in strips of the Antarctic coast (56,157
      GLORYS cells at 0.25°); sea in the Caspian, the Great Lakes, Ladoga and Onega (7,532 cells);
    - waves are missing where ERA5's ice cover exceeds about 0.3 (half of the open-sea cells at
      0.28-0.32, nearly all above 0.4), a field the dataset does not contain;
    - the recipes averaged the mean wave direction arithmetically, wrong across north (`sin_cos`
      fixes it), and filled waves under ice with 0, also the direction (meaning "from north") and
      the period.

    ## 13. What ARCO-OCEAN publishes

    | Variable | Dimensions | Meaning |
    |---|---|---|
    | `seafrac` | depth, lat, lon (static) | share of the cell where GLORYS has a sea cell at that level |
    | `deptho` | lat, lon (static) | mean sea-floor depth, land as 0 (the column's water) |
    | `thetao`, `so`, `uo`, `vo` | time, depth, lat, lon | averages over the sea part; gaps filled from above |
    | `zos` | time, lat, lon | average over the sea part |
    | `siconc`, `sivol`, `usic`, `vsic` | time, lat, lon | over the sea part (section 10) |
    | `dis24_outlets` | time, lat, lon | river input, metres per day over the cell (section 11; not in version 2) |
    | `areacello` | lat, lon (static) | cell area (m²) on GLORYS12's sphere |
    | `volcello` | depth, lat, lon (static) | sea water volume (m³): `seafrac` × layer thickness × `areacello` |
    | `lat_bnds`, `lon_bnds`, `depth_bnds` | coordinate, bnds | CF cell bounds |

    Values exist exactly where `seafrac > 0` (`ensure_no_nans` with `exact`). Volumes and heat
    contents are sums of value × `volcello`, not of the mask; a model's loss is best weighted the
    same way (water volume), so that cells barely touched by the sea weigh little. The ocean
    variables name these weights in `cell_measures`, so CF tools find them.

    The cells are those conservative regridding assumes: bounds midway between centres, the polar
    rows half as tall. Areas are on a sphere of radius 6,378,100 m, the one GLORYS12's static cell
    sizes (`e1t`, `e2t`) imply, so totals match the source's: at 1°, the total of `volcello` equals
    GLORYS12's own (the sum of `e1t` × `e2t` × `e3t` × `mask` over levels 0-48, 1.330 × 10¹⁸ m³) to
    2 × 10⁻⁷, at every level to 3 × 10⁻⁷. A sphere is not the Earth: against the WGS84 ellipsoid,
    its cells are 0.45 % larger at the equator and 0.89 % smaller near the poles, whatever the
    radius. Depth bounds are the faces `[0, cumsum(e3t)]` (section 2). River totals use the same
    areas: discharge (m³/s) = `dis24_outlets` × `areacello` / 86400 (version 2.1).

    ## Measurements

    Generated by the measurements below (GLORYS 202311, GloFAS v5.0, 1 Jan 2013 for the ocean,
    1 Mar 2013 for ice and rivers).

    The same at every resolution (native GLORYS, section `glorys` and `data`):

    | GLORYS12, native | |
    |---|---|
    | sea columns; deepest `deptho` | 6,151,166; 10,528 m (last face 5,958 m) |
    | `mask` = level below `deptho_lev` | everywhere |
    | `mask` = `deptho` below the centre | but 34,615 cells, all "rule sea, mask land" |
    | bottom cell's water (share of its layer), quantiles 0, 1 %, 50 %, 99 % | 0.49, 0.51, 1.01, 1.56 |
    | cells where a partial-cell fraction from `deptho` (> 0) differs from `mask` | 3,089,423 |
    | faces rebuilt from centres against `cumsum(e3t)`, largest difference | 2.18 m |
    | sea cells without value (levels 0-48), the same on 1993-01-01, 2013-01-01, 2021-06-30 | 224,223: 23,819 south of -76.9, 198,720 at 90°, 1,684 elsewhere |
    | level 49: sea cells; with a value | 164,580; 0 |

    Coarse grids (1 Jan 2013 for values):

    | | 0.25° | 0.5° | 1° |
    |---|---|---|---|
    | column identity, largest gap (trenches) | 3,964 m | 2,707 m | 1,874 m |
    | cells the current rule changes with `cumsum(e3t)` faces | 4,189 | 1,034 | 245 |
    | level 0 (0.5 m): current / majority / any | 693,310 / 684,441 / 693,310 | 176,194 / 171,421 / 176,913 | 44,982 / 42,973 / 45,328 |
    | level 0: current sea less than half sea | 8,869 | 4,773 | 2,009 |
    | level 30 (454 m): current / majority / any | 600,081 / 599,197 / 608,646 | 150,793 / 150,030 / 155,772 | 38,071 / 37,647 / 40,045 |
    | level 45 (3,992 m): current / majority / any | 322,447 / 324,494 / 359,731 | 80,231 / 81,579 / 98,869 | 20,002 / 20,500 / 26,852 |
    | level 45: more than half sea, current land | 4,222 | 1,816 | 598 |
    | level 48 (5,275 m): current / majority / any | 67,857 / 69,477 / 95,504 | 16,333 / 17,099 / 31,001 | 3,931 / 4,216 / 9,607 |
    | volume / mean depth: `seafrac` | 0.9989 | 0.9989 | 0.9989 |
    | volume / mean depth: current / majority / any mask | 0.9991 / 1.001 / 1.052 | 0.9993 / 1.003 / 1.107 | 0.9999 / 1.005 / 1.164 |
    | flat column / `seafrac`, level 0 | 1.012 | 1.025 | 1.043 |
    | flat column / `seafrac`, level 30 | 1.002 | 1.006 | 1.014 |
    | flat column / `seafrac`, level 45 | 0.996 | 0.992 | 0.986 |
    | flat column / `seafrac`, level 48 | 0.984 | 0.951 | 0.911 |
    | regridded values outside any water | 0 | 0 | 0 |
    | sea cells without value, levels 0-48 (filled from above) | 1,505 | 1,226 | 461 |
    | sea columns without any value (filled with 0) | 0 | 0 | 0 |
    | footnote: native values outside the native rule; values (`nan_threshold = 0`) outside the current mask | 0; 0 of 27,904,081 | 0; 0 of 6,693,626 | 0; 0 of 1,584,807 |

    Filling (one level left out and refilled; RMSE, temperature °C / salinity):

    | level left out | 0.25° above | 0.25° bottom | 0.5° above | 0.5° bottom | 1° above | 1° bottom |
    |---|---|---|---|---|---|---|
    | 10 (16 m) | 0.075 / 0.062 | 0.091 / 0.104 | 0.080 / 0.080 | 0.124 / 0.193 | 0.079 / 0.079 | 0.141 / 0.279 |
    | 30 (454 m) | 1.21 / 0.119 | 1.41 / 0.131 | 1.21 / 0.118 | 1.75 / 0.164 | 1.20 / 0.117 | 2.03 / 0.211 |
    | 40 (2,225 m) | 0.309 / 0.033 | 0.486 / 0.038 | 0.307 / 0.033 | 1.00 / 0.059 | 0.306 / 0.034 | 1.56 / 0.097 |
    | 48 (5,275 m) | 0.043 / 0.0040 | 0.084 / 0.0050 | 0.042 / 0.0043 | 0.231 / 0.0124 | 0.041 / 0.0042 | 0.633 / 0.0261 |

    Sea ice (1 Mar 2013) and rivers (GloFAS, 1 Mar 2013):

    | | 0.25° | 0.5° | 1° |
    |---|---|---|---|
    | `siconc`: divided by `seafrac` against regridded over the sea part, largest difference | 0 | 0 | 0 |
    | ice area; ice volume (coarse / native) | 1.000004; 1.000005 | 1.0000002; 1.0000002 | 1.0000002; 1.0000001 |
    | thickness, velocity back from float32 `sivol`, `usic`: largest relative error | 1.5e-7 | 1.4e-7 | 1.5e-7 |
    | pits; upstream area at pits / land area | 152,629; 1.00006 | 152,629; 1.00006 | 152,629; 1.00006 |
    | discharge at the pits; coarse total | 1,079,448.7; 1,079,448.8 m³/s | 1,079,448.7; 1,079,448.7 | 1,079,448.7; 1,079,448.7 |
    | cells with river input; pits on coarse edges | 29,892; 55,061 | 12,814; 0 | 5,597; 0 |
    | river input in cells with GLORYS sea | 58 % | 68 % | 93 % |
    | largest cell (the Amazon) | 244,040 m³/s | 244,030 m³/s | 245,130 m³/s |
    | former `dis24` (mean) / main river, median | 0.22 | 0.11 | 0.058 |

    GLORYS's sea ice natively: `siconc` missing on 5,027,535 of 6,151,166 sea cells (no ice), `usi`
    0 on 5,125,114.

    WAVERYS (section `waverys`): sea cells (any water) 644,685 against GLORYS's 693,310 at 0.25°
    (7,532 only in WAVERYS, 56,157 only in GLORYS); share of open-sea cells without waves by ERA5's
    ice cover, 1 Mar / 15 Sep 2013: 0.02 / 0.02 below 0.2, 0.15 / 0.17 at 0.2-0.28, 0.49 / 0.49 at
    0.28-0.32, 0.81 / 0.83 at 0.32-0.4, 0.96 / 0.98 at 0.4-0.5, 1.00 / 1.00 above.

    ## References

    - NEMO ocean engine, version 3.6 (Madec et al., 2016), §4.3.2-4.3.3 (z-coordinate, partial
      steps). <https://zenodo.org/records/1472492>
    - Copernicus Marine, GLOBAL_MULTIYEAR_PHY_001_030 (GLORYS12V1), static and daily products.
    - Copernicus Marine, GLOBAL_MULTIYEAR_WAV_001_032 (WAVERYS), product user manual, issue 1.6.
    - ECMWF, IFS documentation Cy47r3, Part VII: ECMWF wave model, §5.5 (grids and land-sea mask).
    - GloFAS v4.0 auxiliary data (LDD, upstream area):
      <https://confluence.ecmwf.int/display/CEMS/Auxiliary+Data>.
    - Dai, A. and Trenberth, K. E. (2002): Estimates of freshwater discharge from continents,
      J. Hydrometeorology 3, 660-687.
    - Notz, D. et al. (2016): The CMIP6 Sea-Ice Model Intercomparison Project (SIMIP), Geosci. Model
      Dev. 9, 3427-3446.
    - White, L., Adcroft, A. and Hallberg, R. (2009): High-order regridding-remapping schemes for
      continuous isopycnal and generalized coordinates in ocean models, J. Comput. Phys. 228,
      8665-8692.
    - Samudra: Dheeshjith, S. et al. (2025), an AI global ocean emulator trained on OM4.
    - xESMF masking and extrapolation: <https://pangeo-xesmf.readthedocs.io/en/latest/notebooks/Masking.html>.
    - SOSIE (DROWN): <https://brodeau.github.io/sosie>.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Running the measurements

    `uv run --with eccodeslib python notebooks/coarsening.py -- --measure 0.25 --out out-0p25.json`
    measures every section at a resolution (`--sections glorys,data,...` for some), keeping the
    sections already in the file; `-- --tables out-0p25.json,out-0p5.json,out-1p0.json` prints the
    tables above from such files, one column per resolution.
    """)
    return


@app.cell
def _():
    _args = mo.cli_args()
    mo.stop("measure" not in _args)
    _sections = str(_args.get("sections", "glorys,data,fill,ice,rivers,waverys")).split(",")
    measure(float(_args["measure"]), _sections, pathlib.Path(str(_args["out"])))
    return


@app.cell
def _():
    _args = mo.cli_args()
    mo.stop("tables" not in _args)
    tables([json.loads(pathlib.Path(p).read_text()) for p in str(_args["tables"]).split(",")])
    return


@app.function
def grid(res: float) -> dict[str, float]:
  return {
    "south": -90.0,
    "north": 90.0,
    "west": 0.0,
    "east": 360.0 - res,
    "resolution_lat": res,
    "resolution_lon": res,
  }


@app.function
def regrid(ds: xr.Dataset, res: float, **kwargs: Any) -> xr.Dataset:
  return pu.regrid(ds, grid=grid(res), method="conservative", kwargs=kwargs).load()


@app.function
def areas(ds: xr.Dataset | xr.DataArray, lat: str = "latitude", lon: str = "longitude"):
  return pu.cell_areas(ds[lat].values, ds[lon].values)


@app.function
def quantiles(x: np.ndarray, qs=(0.01, 0.1, 0.5, 0.9, 0.99)) -> dict[str, float]:
  x = np.asarray(x, dtype="float64")
  x = x[np.isfinite(x)]
  if not x.size:
    return {}
  return {str(q): float(v) for q, v in zip(qs, np.quantile(x, qs), strict=True)}


@app.function
def weighted(err: np.ndarray, w: np.ndarray) -> dict[str, float]:
  return {
    "bias": float((w * err).sum() / w.sum()),
    "rmse": float(np.sqrt((w * err**2).sum() / w.sum())),
  }


@app.class_definition
class Static:
  """GLORYS's static fields, read once: depth, its level, the 3D mask, the layer thicknesses."""

  def __init__(self) -> None:
    bathy = xr.open_dataset(
      STATIC, variables=["deptho", "deptho_lev", "mask"], dataset_part="bathy", **STATIC_KW
    )
    self.bathy = bathy.load()
    coords = xr.open_dataset(STATIC, variables=["e3t"], dataset_part="coords", **STATIC_KW)
    self.e3t = coords["e3t"].load().values.astype("float64")
    self.centres = self.bathy.depth.values.astype("float64")
    self.faces = np.concatenate([[0.0], np.cumsum(self.e3t)])
    self.mask = self.bathy["mask"].values.astype(bool)
    self.deptho = np.nan_to_num(self.bathy.deptho.values.astype("float64"))  # land: 0


@app.function
def rebuilt_faces(centres: np.ndarray) -> np.ndarray:
  """Faces as `get_sea_mask` rebuilds them: each centre mid-layer, the first top at 0."""
  faces = [0.0]
  for c in centres:
    faces.append(faces[-1] + 2 * (c - faces[-1]))
  return np.array(faces)


@app.function
def section_glorys(res: float, st: Static) -> dict[str, Any]:
  out: dict[str, Any] = {}
  rebuilt = rebuilt_faces(st.centres)
  out["faces"] = {
    "cumsum_e3t_last": st.faces[-4:].round(2).tolist(),
    "rebuilt_last": rebuilt[-4:].round(2).tolist(),
    "max_abs_difference_m": float(np.abs(rebuilt - st.faces).max()),
  }
  D, mask = st.deptho, st.mask
  k = np.arange(mask.shape[0])[:, None, None]
  wet = D > 0
  rule = D[None] > st.centres[:, None, None]
  lev = np.nan_to_num(st.bathy.deptho_lev.values)
  top, h = st.faces[:-1], np.diff(st.faces)
  wl = lev[wet].astype(int)
  fill = (D[wet] - st.faces[wl - 1]) / (st.faces[wl] - st.faces[wl - 1])
  w = np.clip(D[None] - top[:, None, None], 0, h[:, None, None]) / h[:, None, None]
  out["native"] = {
    "wet_columns": int(wet.sum()),
    "deptho_max_m": float(D.max()),
    "mask_equals_level_below_deptho_lev": bool((mask == ((k < lev[None]) & wet[None])).all()),
    "mask_but_not_centre_rule": int((mask & ~rule).sum()),
    "centre_rule_but_not_mask": int((rule & ~mask).sum()),
    "bottom_cell_fill_quantiles": quantiles(fill, (0.0, 0.01, 0.5, 0.99, 1.0)),
    "partial_cell_fraction_positive_differs_from_mask": int(((w > 0) != mask).sum()),
  }
  native = xr.Dataset(
    {
      "deptho": (("latitude", "longitude"), D),
      "w": (("depth", "latitude", "longitude"), w.astype("float32")),
      "binary": (("depth", "latitude", "longitude"), mask.astype("float32")),
    },
    coords={
      "depth": st.bathy.depth,
      "latitude": st.bathy.latitude,
      "longitude": st.bathy.longitude,
    },
  )
  del w
  raw = regrid(native, res, skipna=False)
  round_off = int(((raw.binary > 0) & (raw.binary < 1e-6)).sum())
  coarse = pu.fraction_mask(raw, fraction="binary").fillna(0.0)
  del raw
  Dbar = coarse.deptho.values
  f, fb = coarse.w.values.astype("float64"), coarse.binary.values.astype("float64")
  a = areas(coarse)
  bathy = coarse[["deptho"]].assign_coords(depth=st.bathy.depth)
  current = pu.get_sea_mask(bathy, bathymetry="deptho", depth_dim="depth", mask_name="m")[
    "m"
  ].values
  with_e3t = np.stack([Dbar > m for m in (st.faces[:-1] + st.faces[1:]) / 2])
  rules = {"current": current, "majority": fb >= 0.5, "any": fb > 0}
  out["coarse"] = {
    "identity_max_abs_m": float(np.abs((f * h[:, None, None]).sum(0) - Dbar).max()),
    "current_rule_e3t_vs_rebuilt_faces_cells": int((with_e3t != current).sum()),
    "cells_below_round_off_tolerance": round_off,
  }
  per_level = {}
  for lv in LEVELS:
    c, m, an = rules["current"][lv], rules["majority"][lv], rules["any"][lv]
    per_level[lv] = {
      "depth_m": float(st.centres[lv]),
      "current": int(c.sum()),
      "majority": int(m.sum()),
      "any": int(an.sum()),
      "current_only_vs_majority": int((c & ~m).sum()),
      "majority_only_vs_current": int((m & ~c).sum()),
      "current_sea_fraction_below_half": int((c & (fb[lv] < 0.5)).sum()),
      "current_sea_fraction_below_quarter": int((c & (fb[lv] < 0.25)).sum()),
      "smallest_fraction_in_current": float(fb[lv][c].min()) if c.any() else None,
    }
  out["rules_per_level"] = per_level
  V = float((a * Dbar).sum())
  flat = np.clip(Dbar[None] - top[:, None, None], 0, h[:, None, None])
  out["volumes_relative_to_mean_depth"] = {
    "fraction": float((a * (fb * h[:, None, None]).sum(0)).sum() / V),
    **{f"{n} mask": float((a * (r * h[:, None, None]).sum(0)).sum() / V) for n, r in rules.items()},
    "native mask over native depth": float(
      (areas(st.bathy) * (mask * h[:, None, None]).sum(0)).sum() / (areas(st.bathy) * D).sum()
    ),
  }
  out["layer_water_relative_to_fraction"] = {
    lv: {
      "flat_column": float((a * flat[lv]).sum() / (a * h[lv] * fb[lv]).sum()),
      **{
        n: float((a * h[lv] * r[lv]).sum() / (a * h[lv] * fb[lv]).sum()) for n, r in rules.items()
      },
    }
    for lv in LEVELS
  }
  return out


@app.function
def section_data(res: float, st: Static, day: xr.Dataset) -> dict[str, Any]:
  out: dict[str, Any] = {}
  mask = st.mask
  lat = st.bathy.latitude.values
  gaps = {}
  for d in GAP_DAYS:
    t = xr.open_dataset(
      DAILY, engine="copernicusmarine", variables=["thetao"], start_datetime=d, end_datetime=d
    )
    gaps[d] = mask & t["thetao"].isel(time=0).isnull().load().values
  first = gaps[GAP_DAYS[0]]
  out["gaps"] = {
    "same_on_all_days": all(bool((g == first).all()) for g in gaps.values()),
    "levels_0_48": int(first[:49].sum()),
    "level_49": int(first[49].sum()),
    "level_49_sea_cells": int(mask[49].sum()),
    "rows_south_of_minus_76_9": int(first[:49, lat < -76.9].sum()),
    "row_90": int(first[:49, lat > 89.95].sum()),
    "scattered": int(first[:49, (lat >= -76.9) & (lat <= 89.95)].sum()),
    "values_outside_mask": int((day.thetao.notnull().values & ~mask).sum()),
  }
  coarse = regrid(day[["thetao"]], res, skipna=True, nan_threshold=1.0)
  frac = regrid(xr.Dataset({"b": st.bathy["mask"].astype("float32")}), res, skipna=False)
  sea = pu.fraction_mask(frac, fraction="b", mask_name="sea")["sea"].values
  valid = coarse.thetao.notnull().values
  empty = sea & ~valid
  out["regridded"] = {
    "values_outside_any_water": int((valid & ~sea).sum()),
    "sea_without_value_level_49": int(empty[49].sum()),
    "sea_without_value_levels_0_48": int(empty[:49].sum()),
    "columns_without_any_value": int((sea[0] & ~valid[:49].any(0)).sum()),
  }
  # The footnote: values with nan_threshold 0 lie inside the current mask.
  native_rule = pu.get_sea_mask(st.bathy, bathymetry="deptho", depth_dim="depth", mask_name="m")[
    "m"
  ].values
  bathy = regrid(st.bathy[["deptho"]].fillna(0.0), res, skipna=False).assign_coords(
    depth=st.bathy.depth
  )
  current = pu.get_sea_mask(bathy, bathymetry="deptho", depth_dim="depth", mask_name="m")[
    "m"
  ].values
  strict = np.isfinite(regrid(day[["thetao"]], res, skipna=True, nan_threshold=0.0).thetao.values)
  out["footnote"] = {
    "premise_exceptions": int((day.thetao.notnull().values & ~native_rule).sum()),
    "conclusion_exceptions": int((strict & ~current).sum()),
    "values_nan_threshold_0": int(strict.sum()),
  }
  return out


@app.function
def section_fill(res: float, day: xr.Dataset, st: Static) -> dict[str, Any]:
  out: dict[str, Any] = {}
  variables = ["thetao", "so"]
  coarse = regrid(day[variables], res, skipna=True, nan_threshold=1.0)
  w = np.broadcast_to(areas(coarse), coarse.thetao.shape[1:])
  for K in LEFT_OUT:
    bottom = regrid(
      pu.get_bottom(day[variables].isel(depth=slice(0, K)), depth_dim="depth"),
      res,
      skipna=True,
      nan_threshold=1.0,
    )
    sub = coarse.isel(depth=slice(0, K + 1))
    above = pu.fill_from_above(
      sub.where(sub.depth < sub.depth[K]),  # level K left out
      variables=variables,
      depth_dim="depth",
    )
    res_k = {}
    for v in variables:
      truth, up, bot = coarse[v].values[K], above[v].values[K], bottom[v].values
      ok = np.isfinite(truth) & np.isfinite(up) & np.isfinite(bot)
      res_k[v] = {
        "cells": int(ok.sum()),
        "above": weighted((up - truth)[ok], w[ok]),
        "bottom": weighted((bot - truth)[ok], w[ok]),
      }
    out[K] = res_k
  return out


@app.function
def section_ice(res: float, st: Static) -> dict[str, Any]:
  ice = (
    xr.open_dataset(
      DAILY,
      engine="copernicusmarine",
      variables=["siconc", "sithick", "usi", "vsi"],
      start_datetime=ICE_DAY,
      end_datetime=ICE_DAY,
    )
    .isel(time=0)
    .load()
  )
  sea = st.mask[0]
  native = pu.products(
    ice, sivol=["siconc", "sithick"], usic=["siconc", "usi"], vsic=["siconc", "vsi"]
  )
  frac = xr.Dataset(
    {"seafrac": (("latitude", "longitude"), sea.astype("float64"))},
    coords={k: ice[k] for k in ("latitude", "longitude")},
  )
  coarse = regrid(xr.merge([native[["siconc", "sivol", "usic", "vsic"]], frac]), res, skipna=False)
  coarse = pu.fraction_mask(coarse, fraction="seafrac")
  coarse = pu.divide_by(coarse, variables=["siconc", "sivol", "usic", "vsic"], by="seafrac")
  c0 = ice.siconc.fillna(0).where(sea)
  ref = regrid(
    xr.Dataset(
      {
        "c": c0,
        "ch": (c0 * ice.sithick.fillna(0)).where(sea),
        "cu": (c0 * ice.usi.fillna(0)).where(sea),
      }
    ),
    res,
    skipna=True,
    nan_threshold=1.0,
  )
  a_n, a_c = areas(ice), areas(coarse)
  f = np.nan_to_num(coarse.seafrac.values)  # NaN beyond the source's latitudes
  cz = np.nan_to_num(c0.values)
  out: dict[str, Any] = {
    "native_sea_cells": int(sea.sum()),
    "siconc_missing_on_sea": int((ice.siconc.isnull().values & sea).sum()),
    "usi_zero_on_sea": int((ice.usi.values == 0).sum()),
    "identity_max_abs": float(np.nanmax(np.abs(coarse.siconc.values - ref.c.values))),
    "area_ratio": float((a_c * f * np.nan_to_num(coarse.siconc.values)).sum() / (a_n * cz).sum()),
    "volume_ratio": float(
      (a_c * f * np.nan_to_num(coarse.sivol.values)).sum()
      / (a_n * cz * np.nan_to_num(ice.sithick.values)).sum()
    ),
  }
  c32 = np.nan_to_num(coarse.siconc.values).astype("float32")
  icy = c32 > 0
  for v, ref_name in [("sivol", "ch"), ("usic", "cu")]:
    reference = ref[ref_name].values / ref.c.values
    back = np.asarray(
      np.nan_to_num(coarse[v].values).astype("float32") / np.where(icy, c32, 1), dtype="float64"
    )
    rel = np.abs(back - reference)[icy] / np.maximum(np.abs(reference[icy]), 1e-12)
    out[f"round_trip_{v}_max_relative"] = float(np.nanmax(rel))
  thickness = np.where(icy, np.nan_to_num(coarse.sivol.values) / np.where(icy, c32, 1), np.nan)
  speed = np.where(icy, np.abs(np.nan_to_num(coarse.usic.values)) / np.where(icy, c32, 1), np.nan)
  bins = {}
  for lo, hi in [(0, 0.05), (0.05, 0.15), (0.15, 0.5), (0.5, 0.9), (0.9, 1.01)]:
    s = icy & (c32 > lo) & (c32 <= hi)
    bins[f"{lo}-{min(hi, 1.0)}"] = {
      "cells": int(s.sum()),
      "thickness_median": float(np.median(thickness[s])),
      "sivol_median": float(np.median(np.nan_to_num(coarse.sivol.values)[s])),
      "speed_median": float(np.median(speed[s])),
      "usic_abs_median": float(np.median(np.abs(np.nan_to_num(coarse.usic.values))[s])),
    }
  out["bins"] = bins
  return out


@app.function
def section_rivers(res: float, st: Static) -> dict[str, Any]:
  with TempDirectoryRegistry():
    dis = xr.open_dataset(
      "ewds://cems-glofas-historical",
      engine="earlywarningdatastore",
      system_version="version_5_0",
      hydrological_model="lisflood",
      product_type="consolidated",
      timespan="time_mean",
      variable="average_river_discharge_in_the_last_24_hours",
      start_datetime=datetime.datetime(2013, 3, 1),
      end_datetime=datetime.datetime(2013, 3, 2),
    ).squeeze("time", drop=True)
    # Read the values while the downloaded files exist (`load` leaves the backend's arrays lazy).
    dis = xr.Dataset(
      {"avg_dis": (("latitude", "longitude"), np.asarray(dis["avg_dis"].values))},
      coords={"latitude": dis.latitude.values, "longitude": dis.longitude.values},
    )
    aux = (
      xr.merge(
        [
          xr.open_dataset(f"{GLOFAS_AUX}/ldd_glofas_v4_0.nc", engine="netcdfoverhttp")[["ldd"]],
          xr.open_dataset(f"{GLOFAS_AUX}/uparea_glofas_v4_0.nc", engine="netcdfoverhttp")[
            ["uparea"]
          ].rename(latitude="lat", longitude="lon"),
        ]
      )
      .rename(lat="latitude", lon="longitude")
      .load()
    )
  for name in ("latitude", "longitude"):  # the files' coordinates differ by about 4e-12
    assert np.allclose(aux[name].values, dis[name].values, rtol=0, atol=1e-9)
  aux = aux.assign_coords(latitude=dis.latitude, longitude=dis.longitude)
  ds = xr.merge([dis.rename(avg_dis="dis24"), aux])
  q = ds.dis24.values.astype("float64")
  pits = ds.ldd.values == 5
  a = areas(ds)
  out: dict[str, Any] = {
    "cells_with_discharge": int(np.isfinite(q).sum()),
    "pits": int(pits.sum()),
    "upstream_area_at_pits_over_land_area": float(
      np.nansum(ds.uparea.values[pits]) / (a * np.isfinite(q)).sum()
    ),
    "discharge_at_pits_m3s": float(np.nansum(q[pits])),
  }
  kept = pu.keep_where(ds, variables=["dis24"], condition="ldd", equals=5)
  density = pu.per_unit_area(kept[["dis24"]], variables=["dis24"], factor=86400.0)
  coarse = pu.regrid(
    density,
    grid=grid(res),
    method="conservative",
    kwargs={"skipna": False},
    conservation_tolerance=1e-6,
  ).load()
  per_cell = coarse.dis24.values * areas(coarse) / 86400.0
  frac = (
    regrid(xr.Dataset({"b": st.bathy["mask"].isel(depth=0).astype("float64")}), res, skipna=False)
    .b.fillna(0)
    .values
  )
  lat_p = ds.latitude.values[np.nonzero(pits)[0]]
  lon_p = (ds.longitude.values[np.nonzero(pits)[1]] + 360) % 360
  edge = np.isclose(((lat_p + 90) / res + 0.5) % 1, 0) | np.isclose((lon_p / res + 0.5) % 1, 0)
  out.update(
    {
      "coarse_total_m3s": float(np.nansum(per_cell)),
      "coarse_cells_with_input": int((np.nan_to_num(per_cell) > 0).sum()),
      "pits_on_coarse_edges": int(edge.sum()),
      "input_in_cells_with_sea": float(
        np.nansum(np.where(frac > 0, per_cell, 0)) / np.nansum(per_cell)
      ),
      "largest_cell_m3s": float(np.nanmax(per_cell)),
      "density_m_per_day_quantiles": quantiles(
        coarse.dis24.values[coarse.dis24.values > 0], (0.5, 0.9, 0.99, 1.0)
      ),
    }
  )
  mean = regrid(ds[["dis24"]], res, skipna=True, nan_threshold=0.0).dis24.values
  iy = np.floor((ds.latitude.values + 90) / res + 0.5).astype(int)
  ix = np.floor(((ds.longitude.values + 360) % 360) / res + 0.5).astype(int) % mean.shape[1]
  mx = np.full(mean.shape, -np.inf)
  Y, X = np.meshgrid(iy, ix, indexing="ij")
  ok = np.isfinite(q)
  np.maximum.at(mx, (Y[ok], X[ok]), q[ok])
  both = np.isfinite(mean) & (mx > 1)
  out["published_mean_over_main_river_median"] = float(np.median(mean[both] / mx[both]))
  return out


@app.function
def section_waverys(res: float, st: Static) -> dict[str, Any]:
  ws = xr.open_dataset(
    WAVES_STATIC,
    engine="copernicusmarine",
    variables=["deptho"],
    dataset_version="202311",
    dataset_part="bathy",
    service="static-arco",
  ).load()
  wsea = np.isfinite(ws.deptho.values) & (ws.deptho.values > 0)
  fw = (
    regrid(
      ws.assign(sea=(("latitude", "longitude"), wsea.astype("float32")))[["sea"]], res, skipna=False
    )
    .sea.fillna(0)
    .values
  )
  fg = (
    regrid(xr.Dataset({"b": st.bathy["mask"].isel(depth=0).astype("float32")}), res, skipna=False)
    .b.fillna(0)
    .values
  )
  out: dict[str, Any] = {
    "waverys_any": int((fw > 0).sum()),
    "glorys_any": int((fg > 0).sum()),
    "waverys_only": int(((fw > 0) & (fg == 0)).sum()),
    "glorys_only": int(((fg > 0) & (fw == 0)).sum()),
  }
  era = xr.open_zarr(ERA5, consolidated=True, storage_options={"token": "anon"})["sea_ice_cover"]
  threshold = {}
  for stamp in ["2013-03-01T00:00", "2013-09-15T00:00"]:
    w = (
      xr.open_dataset(
        WAVES,
        engine="copernicusmarine",
        variables=["VHM0"],
        start_datetime=stamp,
        end_datetime=stamp,
      )
      .isel(time=0)
      .load()
    )
    sic = era.sel(time=stamp).load().sortby("latitude")
    valid = xr.Dataset(
      {
        "s": (("latitude", "longitude"), wsea.astype("float32")),
        "v": (("latitude", "longitude"), (w.VHM0.notnull().values & wsea).astype("float32")),
      },
      coords={"latitude": w.latitude, "longitude": w.longitude},
    )
    g = {
      "south": -90.0,
      "north": 90.0,
      "west": 0.0,
      "east": 359.75,
      "resolution_lat": 0.25,
      "resolution_lon": 0.25,
    }
    r = (
      pu.regrid(valid, grid=g, method="conservative", kwargs={"skipna": False})
      .load()
      .sortby("latitude")
    )
    open_sea = r.s.values > 0.99
    missing = 1 - r.v.values / np.where(r.s.values > 0, r.s.values, 1)
    rows = {}
    for lo, hi in [
      (0, 1e-6),
      (1e-6, 0.2),
      (0.2, 0.28),
      (0.28, 0.32),
      (0.32, 0.4),
      (0.4, 0.5),
      (0.5, 1.01),
    ]:
      s = open_sea & (sic.values >= lo) & (sic.values < hi)
      rows[f"{lo}-{hi}"] = float(missing[s].mean()) if s.any() else None
    threshold[stamp] = rows
  out["missing_share_by_era5_ice_cover"] = threshold
  return out


@app.function
def measure(res: float, sections: list[str], path: pathlib.Path) -> None:
  settings.load()
  # Sections already measured in `path` are kept (rerun some with `--sections`).
  results: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
  if results.get("resolution", res) != res:
    raise SystemExit(f"{path} holds measurements at another resolution")
  results["resolution"] = res
  st = Static()
  day = None
  if {"data", "fill"} & set(sections):
    day = (
      xr.open_dataset(
        DAILY,
        engine="copernicusmarine",
        variables=["thetao", "so"],
        start_datetime=DAY,
        end_datetime=DAY,
      )
      .isel(time=0)
      .load()
    )
  runners: dict[str, Callable[[], dict[str, Any]]] = {
    "glorys": lambda: section_glorys(res, st),
    "data": lambda: section_data(res, st, day),
    "fill": lambda: section_fill(res, day, st),
    "ice": lambda: section_ice(res, st),
    "rivers": lambda: section_rivers(res, st),
    "waverys": lambda: section_waverys(res, st),
  }
  for name in sections:
    print(f"section {name}...", file=sys.stderr, flush=True)
    results[name] = runners[name]()
    path.write_text(json.dumps(results, indent=1, default=float))
  print(f"wrote {path}", file=sys.stderr)


@app.function
def tables(results: list[dict[str, Any]]) -> None:
  """The notes' tables, one column per resolution."""

  def row(label: str, get: Callable[[dict[str, Any]], Any]) -> str:
    cells = []
    for r in results:
      try:
        value = get(r)
      except (KeyError, TypeError):
        value = None
      cells.append(
        "" if value is None else (f"{value:,}" if isinstance(value, int) else f"{value:.4g}")
      )
    return f"| {label} | " + " | ".join(cells) + " |"

  header = "| | " + " | ".join(f"{r['resolution']} deg" for r in results) + " |"
  rule = "|---|" + "---|" * len(results)
  print(header)
  print(rule)
  for lv in map(str, LEVELS):
    for key in [
      "current",
      "majority",
      "any",
      "current_only_vs_majority",
      "majority_only_vs_current",
    ]:
      print(
        row(f"level {lv}: {key}", lambda r, lv=lv, key=key: r["glorys"]["rules_per_level"][lv][key])
      )
  for key in ["fraction", "current mask", "majority mask", "any mask"]:
    print(
      row(
        f"volume / mean depth: {key}",
        lambda r, key=key: r["glorys"]["volumes_relative_to_mean_depth"][key],
      )
    )
  for lv in map(str, LEVELS):
    print(
      row(
        f"level {lv}: flat column / fraction",
        lambda r, lv=lv: r["glorys"]["layer_water_relative_to_fraction"][lv]["flat_column"],
      )
    )
  for key in [
    "values_outside_any_water",
    "sea_without_value_level_49",
    "sea_without_value_levels_0_48",
    "columns_without_any_value",
  ]:
    print(row(key, lambda r, key=key: r["data"]["regridded"][key]))
  for K in map(str, LEFT_OUT):
    for v in ["thetao", "so"]:
      for how in ["above", "bottom"]:
        print(
          row(
            f"left out {K}, {v}, {how}: RMSE",
            lambda r, K=K, v=v, how=how: r["fill"][K][v][how]["rmse"],
          )
        )
  for key in [
    "identity_max_abs",
    "area_ratio",
    "volume_ratio",
    "round_trip_sivol_max_relative",
    "round_trip_usic_max_relative",
  ]:
    print(row(f"ice: {key}", lambda r, key=key: r["ice"][key]))
  for key in [
    "coarse_total_m3s",
    "coarse_cells_with_input",
    "pits_on_coarse_edges",
    "input_in_cells_with_sea",
    "largest_cell_m3s",
    "published_mean_over_main_river_median",
  ]:
    print(row(f"rivers: {key}", lambda r, key=key: r["rivers"][key]))


if __name__ == "__main__":
    app.run()
