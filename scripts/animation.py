# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "cartopy",
#   "cmocean",
#   "icechunk>=2",
#   "imageio-ffmpeg",
#   "matplotlib",
#   "numpy",
#   "pillow",
#   "s3fs",
#   "scipy",
#   "xarray",
#   "zarr",
# ]
# ///
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The ARCO-OCEAN animation (docs/animation-design.md): a globe turning once while a year of the
ocean's surface runs, one frame per day; sea surface temperature (thetao, level 0) in cmocean's
`thermal`, sea ice (siconc) in white over it, its opacity the concentration; land dark; the title
and the date small, near the centre of the bottom edge; no colour bar.

Usage: uv run --script scripts/animation.py [options] SOURCE OUTDIR

SOURCE: an ARCO-OCEAN historical dataset on a global grid, read anonymously: an Icechunk
repository (s3://ogs-arco-ocean/historical/res=0p25, or a local directory) or, with --zarr, a
plain Zarr store (the dataset published before, s3://ogs-arco-ocean/datasets/res=0p25). OUTDIR
receives:
- frames/NNNN.png, 1080 x 1080 (the folder is emptied first);
- arco-ocean.mp4 (H.264) and arco-ocean.webm (VP9), 30 frames per second, for the marketplace;
- arco-ocean.webp, an animated preview of --preview-size pixels, for the README and the web page;
- arco-ocean.png, the first frame's globe at 400 x 400 pixels (the web page's icon).
The year's data are read once, cached in OUTDIR/surface-YEAR-HASH.zarr (HASH: of the source, so
another source is read again), and the frames drawn in parallel processes.
"""

import argparse
import concurrent.futures
import hashlib
import os
import pathlib
import shutil
import subprocess

import numpy as np
import xarray as xr

BACKGROUND = "#0b1020"
LAND = (0x2B / 255, 0x2F / 255, 0x36 / 255)
ICE = 0.96
TEXT = "#cfd6df"
SST_RANGE = (-2.0, 31.0)
LATITUDE = 12.0
FPS = 30
# The globe's axes in the figure (left, bottom, width, height), the bottom strip for the text.
AXES = (0.02, 0.06, 0.96, 0.9)
# Natural Earth's coastlines, fetched once before the frames are drawn in parallel.
COASTLINES = "50m"


def read_surface(source: str, year: int, zarr: bool, region: str) -> xr.Dataset:
  """Level 0 of thetao and siconc for every day of `year`, longitudes in [-180, 180)."""
  storage_options = {"anon": True} if source.startswith("s3://") else None
  if zarr:
    ds = xr.open_zarr(source, storage_options=storage_options, consolidated=None)
  else:
    import icechunk

    if source.startswith("s3://"):
      bucket, _, prefix = source.removeprefix("s3://").partition("/")
      storage = icechunk.s3_storage(bucket=bucket, prefix=prefix, region=region, anonymous=True)
    else:
      storage = icechunk.local_filesystem_storage(source)
    session = icechunk.Repository.open(storage).readonly_session("main")
    ds = xr.open_zarr(session.store, consolidated=False)
  days = ds.sel(time=str(year))
  out = xr.Dataset({"sst": days.thetao.isel(depth=0), "ice": days.siconc}).load()
  out = out.assign_coords(lon=((out.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
  for name in out.variables:
    out[name].encoding = {}
  return out


def surface(source: str, year: int, zarr: bool, region: str, outdir: pathlib.Path) -> xr.Dataset:
  """`read_surface`, cached per source and year; written whole before it is used again."""
  key = hashlib.sha256(f"{source} {zarr} {region}".encode()).hexdigest()[:12]
  cache = outdir / f"surface-{year}-{key}.zarr"
  if cache.exists():
    return xr.open_zarr(cache).load()
  out = read_surface(source, year, zarr, region)
  partial = cache.with_suffix(".partial")
  shutil.rmtree(partial, ignore_errors=True)
  out.to_zarr(partial, mode="w")
  partial.rename(cache)
  return out


def edges(centres: np.ndarray) -> tuple[float, float]:
  """The outer edges of evenly spaced cells, from their centres."""
  step = float(centres[1] - centres[0])
  return float(centres[0]) - step / 2, float(centres[-1]) + step / 2


def frame(args: tuple[np.ndarray, np.ndarray, tuple, str, float, pathlib.Path]) -> pathlib.Path:
  """One frame: the day's surface on the globe seen from (`lon0`, LATITUDE)."""
  sst, ice, extent, date, lon0, path = args
  import cartopy.crs as ccrs
  import cmocean
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  # One RGB image: temperature in the colour map, ice blended in white, land (no value) dark.
  low, high = SST_RANGE
  rgb = cmocean.cm.thermal(np.clip((sst - low) / (high - low), 0, 1))[..., :3]
  alpha = (np.clip(np.nan_to_num(ice), 0, 1) * 0.95)[..., None]
  rgb = rgb * (1 - alpha) + ICE * alpha
  rgb[np.isnan(sst)] = LAND

  fig = plt.figure(figsize=(6, 6), dpi=180, facecolor=BACKGROUND)
  ax = fig.add_axes(AXES, projection=ccrs.Orthographic(lon0, LATITUDE))
  ax.set_facecolor(BACKGROUND)
  ax.imshow(
    rgb,
    origin="lower",
    extent=extent,
    transform=ccrs.PlateCarree(),
    regrid_shape=1400,
    interpolation="nearest",
  )
  ax.coastlines(resolution=COASTLINES, linewidth=0.3, color="#9aa3ad")
  ax.spines["geo"].set_edgecolor("#3a4252")
  # Title and date only, small, near the centre of the bottom edge, so a thumbnail cropped to
  # the centre keeps them (maintainer, 23 Nov).
  for x, text, align in ((0.30, "ARCO-OCEAN", "left"), (0.70, date, "right")):
    fig.text(x, 0.025, text, color=TEXT, fontsize=8, family="DejaVu Sans", ha=align)
  fig.savefig(path, facecolor=BACKGROUND)
  plt.close(fig)
  return path


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("source")
  parser.add_argument("outdir", type=pathlib.Path)
  parser.add_argument("--zarr", action="store_true", help="SOURCE is a plain Zarr store")
  parser.add_argument("--region", default="eu-south-1", help="the S3 bucket's region")
  parser.add_argument("--year", type=int, default=2023)
  parser.add_argument("--start-lon", type=float, default=-150.0, help="first frame's centre")
  parser.add_argument("--preview-size", type=int, default=480)
  parser.add_argument("--processes", type=int, default=os.cpu_count())
  args = parser.parse_args()

  args.outdir.mkdir(parents=True, exist_ok=True)
  frames = args.outdir / "frames"
  shutil.rmtree(frames, ignore_errors=True)
  frames.mkdir()
  data = surface(args.source, args.year, args.zarr, args.region, args.outdir)
  lon0, lon1 = edges(data.lon.values)
  lat0, lat1 = edges(data.lat.values)
  # Cell edges, the poles' half cells clipped: a grid that does not cover the globe fails here.
  extent = (lon0, lon1, max(lat0, -90.0), min(lat1, 90.0))
  if lon1 - lon0 < 359.9 or extent[3] - extent[2] < 179.9:
    raise SystemExit(f"Not a global grid: {extent}")

  import cartopy.io.shapereader

  cartopy.io.shapereader.natural_earth(COASTLINES, "physical", "coastline")
  days = data.sizes["time"]
  paths = [frames / f"{i:04d}.png" for i in range(days)]
  # One turn while the year runs, as the Earth turns (the surface moves eastwards, so the centre
  # of the view westwards); the loop's rotation joins without a jump.
  jobs = [
    (
      data.sst.values[i],
      data.ice.values[i],
      extent,
      np.datetime_as_string(data.time.values[i], unit="D"),
      args.start_lon - 360.0 * i / days,
      paths[i],
    )
    for i in range(days)
  ]
  with concurrent.futures.ProcessPoolExecutor(args.processes) as pool:
    for path in pool.map(frame, jobs):
      print("frame", path.name, flush=True)

  import imageio_ffmpeg
  from PIL import Image

  ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
  pattern = str(frames / "%04d.png")
  common = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern]
  subprocess.run(
    [*common, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart",
     str(args.outdir / "arco-ocean.mp4")],
    check=True,
  )  # fmt: skip
  subprocess.run(
    [*common, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "34",
     "-row-mt", "1", str(args.outdir / "arco-ocean.webm")],
    check=True,
  )  # fmt: skip
  size = (args.preview_size, args.preview_size)
  images = [Image.open(path).convert("RGB").resize(size, Image.LANCZOS) for path in paths]
  images[0].save(
    args.outdir / "arco-ocean.webp",
    save_all=True,
    append_images=images[1:],
    duration=round(1000 / FPS),
    loop=0,
    quality=70,
    method=6,
  )
  # The icon: the first frame's globe alone (the globe fills the axes' height, centred).
  first = Image.open(paths[0]).convert("RGB")
  side = round(AXES[3] * first.height)
  top = round((1 - AXES[1] - AXES[3]) * first.height)
  left = (first.width - side) // 2
  icon = first.crop((left, top, left + side, top + side)).resize((400, 400), Image.LANCZOS)
  icon.save(args.outdir / "arco-ocean.png", optimize=True)
  for name in ("arco-ocean.mp4", "arco-ocean.webm", "arco-ocean.webp", "arco-ocean.png"):
    print(name, (args.outdir / name).stat().st_size // 1024, "KiB")


if __name__ == "__main__":
  main()
