# The sources: versions, limitations and how they fit together

ARCO-OCEAN merges products made independently: an ocean reanalysis and an atmospheric
reanalysis, and for the forecasts their operational counterparts. This page
records which versions the recipes read, and what users should know about each source and about
how they fit together. It does not report errors of the sources: it reports limitations their
producers document. Checked on 23 Nov 2026 against the producers' documentation (links below).

## Versions (checked 23 Nov 2026)

Every source is read at its latest version.

| Source | Read as | Latest offered |
|---|---|---|
| GLORYS12 (`GLOBAL_MULTIYEAR_PHY_001_030`) | `cmems_mod_glo_phy_my_0.083deg_P1D-m` and `..._static`, version 202311 | 202311, the only version; no newer global physics reanalysis at 1/12° in the catalogue |
| GLO12 (`GLOBAL_ANALYSISFORECAST_PHY_001_024`) | `cmems_mod_glo_phy_anfc_0.083deg_P1D-m` and the `-cur`, `-so`, `-thetao` datasets, version 202406; static fields version 202211 | the same, the only versions |
| ERA5 | Google's ARCO-ERA5 store `full_37-1h-0p25deg-chunk-1.zarr-v3` | the newest of Google's ERA5 stores |
| IFS HRES | ECMWF open data, 0.25°, on AWS (`s3://ecmwf-forecasts`) | the current operational cycle |

## GLORYS12, the ocean and sea ice

From the GLORYS12 quality document ([QUID 001-030](https://documentation.marine.copernicus.eu/QUID/CMEMS-GLO-QUID-001-030.pdf), issue 1.6, November 2023) and its paper ([Jean-Michel et al., 2021](https://doi.org/10.3389/feart.2021.698876)):

- **Atmospheric forcing changes in 2019.** GLORYS12 is forced by ERA-Interim until the end of
  2018, with its precipitation and radiation corrected toward satellite estimates (not poleward
  of 65°N and 60°S), and by ERA5 from January 2019, without corrections. The QUID shows a
  difference in Southern Ocean sea-ice extent in austral summer between the two forcings.
- **River runoff is a climatology** ([Dai et al., 2009](https://doi.org/10.1175/2008JCLI2592.1)),
  plus freshwater from icebergs around Greenland and Antarctica. The global mass budget is
  imposed: evaporation minus precipitation minus runoff is zero, plus a seasonal cycle and a
  trend.
- **Interim production since July 2021.** The reanalysis is extended with near-real-time
  observations (in situ, altimetry, Reynolds SST, sea ice) instead of reprocessed ones.
- **Spin-up.** The run starts in December 1991 from a climatology, a year before the period
  ARCO-OCEAN covers; the authors find one year short for the deep ocean.
- **Documented biases.**
  - Mean kinetic energy at 1000 m is higher than Argo drifts suggest, in the boundary currents
    and the ACC.
  - The eastward equatorial current of the western tropical Pacific is not reproduced, and some
    zonal currents are too strong (ACC, South Equatorial Current).
  - The steric part of sea-level rise is too large.
  - Arctic sea ice piles up in the Beaufort Gyre, about 1 m too thick against CryoSat-2 in
    January 2014. Sea-ice thickness is not assimilated, only concentration.
  - Eddy kinetic energy jumps in 2004, with a change of the 3D-Var window.
- **Fixed exchanges.** Temperature and salinity are restored to a climatology at Gibraltar and
  Bab-el-Mandeb.
- **Bottom level.** Level 50 (5728 m) is never computed by NEMO: ARCO-OCEAN leaves it out.

## ERA5, the atmosphere

From ERA5's documentation and its known issues ([ERA5: data documentation](https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation)):

- **Its own sea surface.** ERA5's SST and sea ice are boundary conditions from HadISST2 until
  September 2007, then from OSTIA and OSI SAF, updated once a day: not GLORYS12's.
- **Known issues in the period covered:**
  - a spurious semi-permanent cyclone over the Amundsen Sea, May to October 1996;
  - global SST held constant from 24 to 29 June 2024 (an OSTIA delivery error);
  - sea-ice concentration held constant from 11 to 18 September 2024;
  - no sea ice on the Caspian Sea from late 2007 to 2013;
  - a winter warm bias of 5 K or more in the skin temperature over thick, snow-covered Arctic
    sea ice under clear skies;
  - "rain bombs": extreme precipitation in small areas a few times a year, mostly over high
    orography in Africa;
  - near-surface winds and temperatures that do not match between assimilation cycles at about
    09-10 and 21-22 UTC, mostly over low-latitude oceans (daily means smooth this out).
- **Accumulations.** Accumulations end at their stamp. ARCO-OCEAN moves them back an hour, so day
  D sums its own hours (arco-make logbook, 17 Nov).
- **Final data only.** The historical dataset ends on 2026-07-01, within ERA5's final data; ERA5T,
  preliminary data that can be revised, is not used.

## GloFAS, the river discharge

Not in version 2 (README, Rivers). The notes on GloFAS v5.0 and its forecasts are at the tag
`rivers-last`.

## How the sources fit together

These are not errors of any source, but they matter to a model trained on ARCO-OCEAN as one
system:

1. **The ocean did not feel the dataset's atmosphere before 2019.** ARCO-OCEAN's atmospheric
   fields are ERA5 throughout, but GLORYS12 was driven by corrected ERA-Interim until the end
   of 2018. Before 2019, the surface fluxes implied by ARCO-OCEAN's atmosphere are not those
   the ocean received. From 2019 they come from the same reanalysis, though GLORYS12 computes
   its fluxes with its own bulk formulae.
2. **Two sea surfaces.** ERA5's near-surface fields over the ocean (`2t`, `2d`, the winds) were
   made over ERA5's own SST and sea ice, not GLORYS12's. They differ most near the ice edge and
   in the boundary currents.
3. **The forecasts are other systems.** GLO12 (the operational analysis and forecast) and IFS
   HRES are not the reanalyses' systems. They differ in model version,
   resolution and assimilated data, and GLO12 has its own bathymetry and mask (README,
   Forecasts). A model trained on the historical dataset meets a shift when it reads the
   forecasts.
