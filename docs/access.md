# Data access

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

1. [Computing the Oceanic El Nino Index (ONI) with Xarray and ARCO-OCEAN](https://github.com/stefanocampanella/arco-ocean/blob/main/tutorials/oni.py) (written for the first version: its paths and variables are those of the 0.25°, 10-level dataset)

The tutorials are [marimo](https://marimo.io) notebooks: `uvx marimo edit --sandbox tutorials/oni.py` opens one in an environment of its own, with the dependencies it lists.
