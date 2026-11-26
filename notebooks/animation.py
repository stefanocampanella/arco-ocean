# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "cartopy",
#   "cmocean",
#   "icechunk>=2",
#   "imageio-ffmpeg",
#   "marimo",
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
# The ARCO-OCEAN animation: its design, and the code that makes it. A marimo notebook:
# `uv run notebooks/animation.py -- --source SOURCE --outdir OUTDIR` makes it (Running it).

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import concurrent.futures
    import hashlib
    import os
    import pathlib
    import shutil
    import subprocess

    import marimo as mo
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
    # Each drawing process's view of the cache ("data"), and the longitudes and latitudes of the
    # globe's samples seen from longitude 0 ("view"): turning the globe about its axis adds the
    # view's longitude to them, so they are computed once (worker_setup). One dict, updated, not
    # rebound (marimo defines each name in one place).
    WORKER: dict = {}


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # An animation of ARCO-OCEAN (design)

    Roadmap item 5: an animation for the Earthmover marketplace listing and the documentation. This
    was a proposal; the maintainer chose its content and text on 23 Nov (Decisions, below).

    *The animation is the README's cover
    (`docs/assets/images/arco-ocean.webp`), made on 25 Nov by this notebook (How it is made, below).
    Generated using E.U. Copernicus Marine Service Information
    ([10.48670/moi-00021](https://doi.org/10.48670/moi-00021)).*

    ## What it shows

    **A rotating globe with a year of the ocean's surface.** Day by day; sea surface temperature
    as colour; sea ice drawn over it in white, its opacity the concentration; land
    dark. While the year runs, the globe turns once, so each ocean comes into view in its own
    season:
    - the Pacific's equatorial cold tongue;
    - the Gulf Stream and the Kuroshio;
    - the Arctic ice melting back in summer, and the Antarctic ice growing in austral winter.

    **The year.** 2023, El Niño's onset, when the eastern Pacific warms over the months.
    It is within the historical dataset and well known; any year works.

    ## Why this design

    - **One variable, one colour map.** Temperature is a magnitude, so it gets one sequential,
      perceptually uniform colour map: cmocean's `thermal`, dark purple to yellow. It reads under
      colour-vision deficiencies, unlike a rainbow, and stays legible on the dark background.
    - **Sea ice in white over it.** No second colour scale: white is outside the colour map, and its
      opacity is the concentration, so the ice edge is soft where the ice is thin.
    - **A globe, not a map.** A rotating globe avoids the distortion of flat maps at the poles,
      where the ice is, and shows ocean and ice together as one system, which is what the dataset
      merges.
    - **A loop for the marketplace.** Two frames a day, 730 frames at 30 per second (24 s), and
      one turn of the globe. It loops without a jump in rotation, though one in season. A frame a
      day (12 s, the first version) turned the globe by a degree a frame, 8 pixels at its centre:
      too fast to follow (maintainer, 25 Nov: "a bit jumpy").

    ## Alternatives considered

    1. **Surface currents.** Speed from `uo`/`vo` (cmocean `speed`, on black), with particles
       advected along the currents. The most striking option, but rendering particles needs more
       than cartopy (a GPU renderer, or a few days of work), and the current speed at 0.25° is
       noisy.
    2. **Anomalies.** Temperature minus the climatology (the statistics' `climatology` group), on a
       diverging map (blue, grey at zero, red). It shows El Niño best, but it needs the statistics
       and a legend that explains the anomaly.
    3. **Depth.** A slice through the levels (temperature along the equator, 0-500 m) next to the
       globe: it shows that the dataset is 3D, but two panels are less suited to a thumbnail.

    ## How it is made

    `uv run notebooks/animation.py -- --source SOURCE --outdir OUTDIR [--zarr]` (dependencies
    inline; the options in the cell that runs it, at the end). Made on 25 Nov 2026 (by
    `scripts/animation.py`, which became this notebook):
    - **Data.** Level 0 of `thetao` and `siconc` for the 365 days of 2023 at 0.25°, read anonymously
      once (about 3 GB) and cached in OUTDIR per source. Made from the dataset published before
      (`s3://ogs-arco-ocean/datasets/res=0p25`, `--zarr`), since the new historical repository is not
      written yet: its sea ice was averaged with open water as 0 along coasts, which the new recipes
      fix. Run the notebook again on `historical/res=0p25` once it is published.
    - **Frames.** Two per day, the second halfway to the next day (the two days' values blended;
      the last day's with the first, closing the loop): temperature in `thermal`, ice blended in
      white, land dark, on an orthographic globe centred at 12° N (the equator's ocean in view, the
      Arctic at the rim), with Natural Earth's 50 m coastlines; 1080 x 1080 pixels. The centre moves
      west by 360/730° a frame, so the surface moves east as the Earth's does.
    - **Projection.** The notebook projects the globe itself: each pixel's longitude and latitude
      (cartopy's inverse orthographic projection, once: turning the globe adds to the longitudes),
      the temperature and ice there interpolated bilinearly between the sea cells' centres (a point
      among mostly land cells is land), longitudes periodic, 2 x 2 samples per pixel, the globe's
      axes on whole pixels so the image is drawn one pixel per pixel. The first version let cartopy
      warp the image by nearest cell: the cells' edges stepped from frame to frame (jumpy), and the
      antimeridian, where the grid's longitudes wrap, showed as a line. The frames take 5 minutes
      on the project machine, the whole run 11 (the WebP's encoding is the slowest part).
    - **Outputs.**
      - `docs/assets/images/arco-ocean.webp` (480 x 480, 8.3 MB, quality 60: WebP shares little between
        frames, so its size follows their number): the README's cover; the web page shows the
        still globe and links it, so that it moves and loads only on request.
      - `docs/assets/images/arco-ocean.png`: the first frame's globe, the web page's icon.
      - An MP4 (H.264) and a WebM (VP9), 1080 x 1080, 7.9 and 5.6 MB, for the marketplace: not
        committed.
      - Each credits the Copernicus Marine Service where it is shown; the images are CC BY 4.0, as
        the data.

    ## Decisions (maintainer, 23 Nov)

    1. **Variable and year:** sea surface temperature with sea ice, in 2023, as proposed.
    2. **Text:** the title and a running date, small, near the centre of the bottom edge, so that a
       thumbnail cropped to the centre keeps them; no colour bar.

    ## Open points

    1. **Branding:** Earthmover's marketplace may have size and length requirements, to check when
       listing (roadmap item 10).
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Running it

    `uv run notebooks/animation.py -- --source SOURCE --outdir OUTDIR [--zarr] [--region R] [--year Y] [--start-lon L] [--frames-per-day N] [--preview-size P] [--processes N]`

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
    """)
    return


@app.cell
def _():
    # Run with the arguments after `--` (Running it, above); nothing without --source.
    _args = mo.cli_args()
    mo.stop(
        "source" not in _args,
        mo.md("_Run with `uv run notebooks/animation.py -- --source SOURCE --outdir OUTDIR`._"),
    )
    render(
        str(_args["source"]),
        pathlib.Path(str(_args["outdir"])),
        zarr="zarr" in _args,
        region=str(_args.get("region", "eu-south-1")),
        year=int(_args.get("year", 2023)),
        start_lon=float(_args.get("start-lon", -150.0)),
        frames_per_day=int(_args.get("frames-per-day", FRAMES_PER_DAY)),
        preview_size=int(_args.get("preview-size", 480)),
        processes=int(_args["processes"]) if "processes" in _args else os.cpu_count(),
    )
    return


@app.function
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


@app.function
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


@app.function
def axis(centres: np.ndarray) -> tuple[float, float]:
  """The first centre and the step of evenly spaced cells."""
  steps = np.diff(centres)
  if not np.allclose(steps, steps[0]):
    raise SystemExit("Not a regular grid")
  return float(centres[0]), float(steps[0])


@app.function
def worker_setup(cache: pathlib.Path) -> None:
  # Without Dask: a frame's reads run in its process, not in a pool of threads per process.
  WORKER["data"] = xr.open_zarr(cache, chunks=None)
  WORKER["view"] = view(GLOBE * SUPERSAMPLE)


@app.function
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


@app.function
def colours(sst: np.ndarray, ice: np.ndarray) -> np.ndarray:
  """RGB: temperature in the colour map, ice blended in white, land (no value) dark."""
  import cmocean

  low, high = SST_RANGE
  rgb = cmocean.cm.thermal(np.clip((sst - low) / (high - low), 0, 1))[..., :3]
  alpha = (np.clip(np.nan_to_num(ice), 0, 1) * 0.95)[..., None]
  rgb = rgb * (1 - alpha) + ICE * alpha
  rgb[np.isnan(sst)] = LAND
  return rgb


@app.function
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


@app.function
def globe(sst: np.ndarray, ice: np.ndarray, grid: tuple, lon0: float, size: int) -> np.ndarray:
  """The globe seen from (`lon0`, LATITUDE) as an RGBA image of `size` x `size` pixels over the
  projection's limits, rows from south to north, transparent off the globe, each pixel the mean
  of SUPERSAMPLE**2 samples."""
  lon, lat, on_globe = WORKER["view"]
  values = colours(*sample(sst, ice, lon + lon0, lat, grid))
  alpha = on_globe.astype(float)
  # Means of the samples of each pixel, the colours weighted by their opacity.
  premultiplied = np.concatenate([values * alpha[..., None], alpha[..., None]], axis=-1)
  pixels = premultiplied.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE, 4).mean(axis=(1, 3))
  opacity = pixels[..., 3:]
  pixels[..., :3] = np.divide(pixels[..., :3], opacity, out=np.zeros_like(pixels[..., :3]),
                              where=opacity > 0)  # fmt: skip
  return np.clip(pixels, 0, 1)


@app.function
def frame(args: tuple[int, int, float, tuple, str, float, pathlib.Path]) -> pathlib.Path:
  """One frame: the surface `weight` of the way from day `day` to day `next_day`, on the globe
  seen from (`lon0`, LATITUDE)."""
  day, next_day, weight, grid, date, lon0, path = args
  import cartopy.crs as ccrs
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  data = WORKER["data"]
  first = data.isel(time=day)
  sst, ice = first.sst.values, first.ice.values
  if weight > 0:
    second = data.isel(time=next_day)
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


@app.function
def render(
  source: str,
  outdir: pathlib.Path,
  zarr: bool = False,
  region: str = "eu-south-1",
  year: int = 2023,
  start_lon: float = -150.0,
  frames_per_day: int = FRAMES_PER_DAY,
  preview_size: int = 480,
  processes: int | None = None,
) -> None:
  """The frames, the videos, the preview and the icon of `year` from `source` into `outdir`
  (Running it, above). frames_per_day: the day's frame, then the day blended with the next;
  start_lon: the first frame's centre."""
  if frames_per_day < 1:
    raise ValueError("frames_per_day must be at least 1")
  outdir.mkdir(parents=True, exist_ok=True)
  frames = outdir / "frames"
  shutil.rmtree(frames, ignore_errors=True)
  frames.mkdir()
  cache = surface(source, year, zarr, region, outdir)
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
  count = days * frames_per_day
  paths = [frames / f"{i:04d}.png" for i in range(count)]
  # One turn while the year runs, as the Earth turns (the surface moves eastwards, so the centre
  # of the view westwards). The frames between two days blend them; the last day's blend with the
  # first, so the loop joins without a jump, in its rotation as in its values.
  jobs = []
  for i in range(count):
    day, step = divmod(i, frames_per_day)
    weight = step / frames_per_day
    lon = start_lon - 360.0 * i / count
    jobs.append((day, (day + 1) % days, weight, grid, str(dates[day]), lon, paths[i]))
  with concurrent.futures.ProcessPoolExecutor(
    processes, initializer=worker_setup, initargs=(cache,)
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
     str(outdir / "arco-ocean.mp4")],
    check=True,
  )  # fmt: skip
  subprocess.run(
    [*common, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "34",
     "-row-mt", "1", str(outdir / "arco-ocean.webm")],
    check=True,
  )  # fmt: skip
  size = (preview_size, preview_size)
  images = [Image.open(path).convert("RGB").resize(size, Image.LANCZOS) for path in paths]
  images[0].save(
    outdir / "arco-ocean.webp",
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
  icon.save(outdir / "arco-ocean.png", optimize=True)
  for name in ("arco-ocean.mp4", "arco-ocean.webm", "arco-ocean.webp", "arco-ocean.png"):
    print(name, (outdir / name).stat().st_size // 1024, "KiB")


if __name__ == "__main__":
    app.run()
