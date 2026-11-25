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
ocean's surface runs, two frames per day (the second halfway to the next day, interpolated); sea
surface temperature (thetao, level 0) in cmocean's `thermal`, sea ice (siconc) in white over it,
its opacity the concentration; land dark; the title and the date small, near the centre of the
bottom edge; no colour bar.

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
another source is read again), and the frames drawn in parallel processes, each reading the days it
needs from the cache. The globe is projected here, not by cartopy: each pixel's longitude and
latitude, the temperature and ice there interpolated bilinearly between the sea cells (across the
antimeridian too), 2 x 2 samples per pixel; cartopy draws the coastlines over it.
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
FRAMES_PER_DAY = 2
# Samples per pixel along each axis: the globe's limb and the cells' edges without steps.
SUPERSAMPLE = 2
# The figure: 6 x 6 inches at 180 dots per inch, 1080 pixels a side.
INCHES, DPI = 6, 180
# The globe's square axes, in whole pixels so that the globe's image is drawn one pixel per pixel
# (a fraction resamples it, in steps): 972 pixels, above a strip of 64 for the text.
FRAME, GLOBE, BOTTOM = INCHES * DPI, 972, 64
AXES = ((FRAME - GLOBE) / 2 / FRAME, BOTTOM / FRAME, GLOBE / FRAME, GLOBE / FRAME)
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


def surface(source: str, year: int, zarr: bool, region: str, outdir: pathlib.Path) -> pathlib.Path:
  """`read_surface`, cached per source and year, one day per chunk (a frame reads two days);
  written whole before it is used again."""
  key = hashlib.sha256(f"{source} {zarr} {region} daily".encode()).hexdigest()[:12]
  cache = outdir / f"surface-{year}-{key}.zarr"
  if not cache.exists():
    out = read_surface(source, year, zarr, region)
    partial = cache.with_suffix(".partial")
    shutil.rmtree(partial, ignore_errors=True)
    daily = {"chunks": (1, out.sizes["lat"], out.sizes["lon"])}
    out.to_zarr(partial, mode="w", encoding={name: daily for name in ("sst", "ice")})
    partial.rename(cache)
  return cache


def axis(centres: np.ndarray) -> tuple[float, float]:
  """The first centre and the step of evenly spaced cells."""
  steps = np.diff(centres)
  if not np.allclose(steps, steps[0]):
    raise SystemExit("Not a regular grid")
  return float(centres[0]), float(steps[0])


# Each drawing process's view of the cache, and the longitudes and latitudes of the globe's samples
# seen from longitude 0 (`_setup`): turning the globe about its axis adds the view's longitude to
# them, so they are computed once.
_DATA: xr.Dataset | None = None
_VIEW: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None


def _setup(cache: pathlib.Path) -> None:
  global _DATA, _VIEW
  # Without Dask: a frame's reads run in its process, not in a pool of threads per process.
  _DATA = xr.open_zarr(cache, chunks=None)
  _VIEW = view(GLOBE * SUPERSAMPLE)


def view(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """Longitudes and latitudes of n x n points over the globe seen from (0, LATITUDE), rows from
  south to north, and which points are on the globe (the others are given 0, 0)."""
  import cartopy.crs as ccrs

  projection = ccrs.Orthographic(0.0, LATITUDE)
  (x0, x1), (y0, y1) = projection.x_limits, projection.y_limits
  x = x0 + (np.arange(n) + 0.5) * (x1 - x0) / n
  y = y0 + (np.arange(n) + 0.5) * (y1 - y0) / n
  xx, yy = np.meshgrid(x, y)
  points = ccrs.PlateCarree().transform_points(projection, xx, yy)
  lon, lat = points[..., 0], points[..., 1]
  on_globe = np.isfinite(lon) & np.isfinite(lat)
  return np.where(on_globe, lon, 0.0), np.where(on_globe, lat, 0.0), on_globe


def colours(sst: np.ndarray, ice: np.ndarray) -> np.ndarray:
  """RGB: temperature in the colour map, ice blended in white, land (no value) dark."""
  import cmocean

  low, high = SST_RANGE
  rgb = cmocean.cm.thermal(np.clip((sst - low) / (high - low), 0, 1))[..., :3]
  alpha = (np.clip(np.nan_to_num(ice), 0, 1) * 0.95)[..., None]
  rgb = rgb * (1 - alpha) + ICE * alpha
  rgb[np.isnan(sst)] = LAND
  return rgb


def sample(
  sst: np.ndarray, ice: np.ndarray, lon: np.ndarray, lat: np.ndarray, grid: tuple
) -> tuple[np.ndarray, np.ndarray]:
  """Temperature and ice (lat, lon) at the points (`lon`, `lat`), bilinearly between the centres
  of the sea's cells: the longitudes periodic (no seam at the antimeridian), the latitudes clamped
  to the polar rows. A point whose neighbours are mostly land is land (NaN); otherwise only its
  sea neighbours count, so the land's value does not seep into the sea's colours."""
  lon_first, lon_step, lat_first, lat_step = grid
  rows, columns = sst.shape
  i = np.mod((lon - lon_first) / lon_step, columns)
  j = np.clip((lat - lat_first) / lat_step, 0, rows - 1)
  i0 = np.floor(i).astype(np.intp) % columns
  j0 = np.minimum(np.floor(j).astype(np.intp), rows - 2)
  di = i - np.floor(i)
  dj = j - j0
  i1 = (i0 + 1) % columns
  sea = ~np.isnan(sst)
  sst, ice = np.nan_to_num(sst), np.nan_to_num(ice)
  weight = np.zeros_like(lon)
  sst_sum = np.zeros_like(lon)
  ice_sum = np.zeros_like(lon)
  for rows_, columns_, w in (
    (j0, i0, (1 - dj) * (1 - di)),
    (j0, i1, (1 - dj) * di),
    (j0 + 1, i0, dj * (1 - di)),
    (j0 + 1, i1, dj * di),
  ):
    w = w * sea[rows_, columns_]
    weight += w
    sst_sum += w * sst[rows_, columns_]
    ice_sum += w * ice[rows_, columns_]
  land = weight < 0.5
  weight = np.where(land, 1.0, weight)
  return np.where(land, np.nan, sst_sum / weight), ice_sum / weight


def globe(sst: np.ndarray, ice: np.ndarray, grid: tuple, lon0: float, size: int) -> np.ndarray:
  """The globe seen from (`lon0`, LATITUDE) as an RGBA image of `size` x `size` pixels over the
  projection's limits, rows from south to north, transparent off the globe, each pixel the mean
  of SUPERSAMPLE**2 samples."""
  assert _VIEW is not None
  lon, lat, on_globe = _VIEW
  values = colours(*sample(sst, ice, lon + lon0, lat, grid))
  alpha = on_globe.astype(float)
  # Means of the samples of each pixel, the colours weighted by their opacity.
  premultiplied = np.concatenate([values * alpha[..., None], alpha[..., None]], axis=-1)
  pixels = premultiplied.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE, 4).mean(axis=(1, 3))
  opacity = pixels[..., 3:]
  pixels[..., :3] = np.divide(pixels[..., :3], opacity, out=np.zeros_like(pixels[..., :3]),
                              where=opacity > 0)  # fmt: skip
  return np.clip(pixels, 0, 1)


def frame(args: tuple[int, int, float, tuple, str, float, pathlib.Path]) -> pathlib.Path:
  """One frame: the surface `weight` of the way from day `day` to day `next_day`, on the globe
  seen from (`lon0`, LATITUDE)."""
  day, next_day, weight, grid, date, lon0, path = args
  import cartopy.crs as ccrs
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  assert _DATA is not None
  first = _DATA.isel(time=day)
  sst, ice = first.sst.values, first.ice.values
  if weight > 0:
    second = _DATA.isel(time=next_day)
    sst = sst * (1 - weight) + second.sst.values * weight
    ice = np.nan_to_num(ice) * (1 - weight) + np.nan_to_num(second.ice.values) * weight

  fig = plt.figure(figsize=(INCHES, INCHES), dpi=DPI, facecolor=BACKGROUND)
  projection = ccrs.Orthographic(lon0, LATITUDE)
  ax = fig.add_axes(AXES, projection=projection)
  ax.set_facecolor(BACKGROUND)
  ax.set_global()
  (x0, x1), (y0, y1) = projection.x_limits, projection.y_limits
  # The globe fills the square axes: one image pixel per pixel of the frame.
  ax.imshow(
    globe(sst, ice, grid, lon0, GLOBE),
    origin="lower",
    extent=(x0, x1, y0, y1),
    transform=projection,
    interpolation="none",
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
  parser.add_argument(
    "--frames-per-day",
    type=int,
    default=FRAMES_PER_DAY,
    help="frames per day: the day's, then the day blended with the next",
  )
  parser.add_argument("--preview-size", type=int, default=480)
  parser.add_argument("--processes", type=int, default=os.cpu_count())
  args = parser.parse_args()
  if args.frames_per_day < 1:
    parser.error("--frames-per-day must be at least 1")

  args.outdir.mkdir(parents=True, exist_ok=True)
  frames = args.outdir / "frames"
  shutil.rmtree(frames, ignore_errors=True)
  frames.mkdir()
  cache = surface(args.source, args.year, args.zarr, args.region, args.outdir)
  data = xr.open_zarr(cache)
  (lon_first, lon_step), (lat_first, lat_step) = axis(data.lon.values), axis(data.lat.values)
  grid = (lon_first, lon_step, lat_first, lat_step)
  # The cells' edges, the poles' half cells clipped: a grid that does not cover the globe fails.
  west, east = lon_first - lon_step / 2, lon_first + (data.sizes["lon"] - 0.5) * lon_step
  south = max(lat_first - lat_step / 2, -90.0)
  north = min(lat_first + (data.sizes["lat"] - 0.5) * lat_step, 90.0)
  if east - west < 359.9 or north - south < 179.9:
    raise SystemExit(f"Not a global grid: {west, east, south, north}")

  import cartopy.io.shapereader

  cartopy.io.shapereader.natural_earth(COASTLINES, "physical", "coastline")
  days = data.sizes["time"]
  dates = np.datetime_as_string(data.time.values, unit="D")
  count = days * args.frames_per_day
  paths = [frames / f"{i:04d}.png" for i in range(count)]
  # One turn while the year runs, as the Earth turns (the surface moves eastwards, so the centre
  # of the view westwards). The frames between two days blend them; the last day's blend with the
  # first, so the loop joins without a jump, in its rotation as in its values.
  jobs = []
  for i in range(count):
    day, step = divmod(i, args.frames_per_day)
    weight = step / args.frames_per_day
    lon = args.start_lon - 360.0 * i / count
    jobs.append((day, (day + 1) % days, weight, grid, str(dates[day]), lon, paths[i]))
  with concurrent.futures.ProcessPoolExecutor(
    args.processes, initializer=_setup, initargs=(cache,)
  ) as pool:
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
    quality=60,
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
