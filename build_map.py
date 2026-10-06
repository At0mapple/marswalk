"""
build_map.py  --  Marswalk map builder
=====================================
Turns an elevation grid into ONE web page (mars_map.html): an interactive map
with toggleable layers, a safe walking route, sliders and a go/no-go briefing.

Install once:
    pip install numpy matplotlib scikit-image scipy pillow
    pip install rasterio          # only needed in week 3, for real .tif data

Run:
    python build_map.py
Then open  mars_map.html  in your browser.

The script has 7 steps. Read the comments in each one (week 2 homework).
Everything you are meant to change lives in STEP 1.
"""

import os
import io
import json
import base64
import numpy as np
import matplotlib
matplotlib.use("Agg")                      # draw to files, no pop-up windows
import matplotlib.pyplot as plt
from scipy import ndimage
from matplotlib.colors import LinearSegmentedColormap
from skimage.graph import route_through_array
from PIL import Image


# =====================================================================
# STEP 1 - SETTINGS  (the only place you need to edit)
# =====================================================================
SITE_NAME = "Gale Crater"

# --- Where the elevation comes from ----------------------------------
# None = generate fake terrain (week 1-2).
# "gale_elevation.tif" = use a real file (week 3+, needs rasterio).
ELEVATION_FILE = "gale_elevation.tif"
# Real files only: meters per pixel. Leave None to read it from the file.
# You MUST set it if the file is in degrees (QGIS shows this in layer info).
REAL_METERS_PER_PIXEL = 1.0
# Real files only: use just a PART of a big file (needed for the 3.6 GB Gale file).
# CROP_CENTER = middle of the part, as shares of the whole file (0 to 1): (left-right, top-bottom).
# CROP_SIZE_KM = (width, height) of the part in km. None = use the whole file.
CROP_CENTER = (0.257, 0.382)
CROP_SIZE_KM = (16, 8)
MAX_REAL_PIXELS = 1600     # longest side of the map in pixels (more = sharper but slower)
SAVE_OVERVIEW = True       # saves file_overview.png: the whole file, with your crop as a red box

# --- Fake terrain only -----------------------------------------------
GRID_WIDTH = 600           # pixels left to right (a wide box fits a wide screen)
GRID_HEIGHT = 300          # pixels top to bottom
FAKE_METERS_PER_PIXEL = 40    # 600 x 300 pixels at 40 m = a 24 x 12 km box
RANDOM_SEED = 7            # change it to get a different landscape

# --- Route -----------------------------------------------------------
# Positions are (row, column) in pixels. Row 0 is the TOP, column 0 is the LEFT.
# (Written as shares of the grid size so they work for any fake grid.
#  With a real file, type plain pixel numbers instead.)
START = (480, 500)    # the habitat
END = (400, 800)      # the science target, in the middle of the map

# --- Safety rules (Science role owns these numbers) -------------------
WALK_SPEED_KMH = 2.5       # average speed of a person in a suit
MAX_SLOPE_DEG = 15         # steeper than this = no walking
SUIT_HOURS = 8.0           # how long the suit lasts (the page has a slider for this)
STOPS_HOURS = 1.0          # time spent at stops (samples, photos)
MARGIN_HOURS = 0.5         # spare time that must always be left over
RETURN_RING_KM = 6.0       # never go farther than this from the habitat
# EVA suit: hours each supply lasts when the suit time slider is at SUIT_HOURS.
# (Practice numbers: the Science role replaces them with real suit data.)
SUIT_SUPPLIES = {"Oxygen": 8.5, "CO2 scrubber": 8.0, "Battery": 9.0, "Cooling water": 8.5}

# --- Names on the map -------------------------------------------------
HABITAT_NAME = "Habitat"
TARGET_NAME = "Target: clay outcrop"
STOP_NAMES = ["Stop 1"]    # spread evenly along the route. Use [] for no stops.
CONDITIONS = ("Clear sky, low dust. Air about -60 to -20 \u00b0C. "
              "(Practice values: the Science role replaces these.)")

# --- Look of the map -------------------------------------------------
exaggeration = 3.0         # makes hills look taller in the shading (try 1 to 6)
SLOPE_SHOW_FROM = 5        # the "Steep slopes" layer starts coloring at this angle
CONTOUR_EVERY_M = None     # None = choose automatically, or type a number like 20

# Presets for the "Views" buttons: a name and the layers it switches on.
# Layer names: Terrain, Contours, Steep slopes, Temperature, Minerals, Route, Return ring
views = {
    "Safety": ["Terrain", "Steep slopes", "Route", "Return ring"],
    "Science": ["Terrain", "Minerals", "Route"],
    "Cold exposure": ["Terrain", "Temperature", "Route"],
    "Terrain only": ["Terrain"],
}
start_view = "Safety"      # which preset is on when the page opens

# --- Real images from the Data role (week 3) --------------------------
# Image of the real terrain, replaces the shaded fake terrain. Must cover
# exactly the same box as the elevation file.
TERRAIN_IMAGE = None                    # e.g. "gale_terrain.png"
# Extra layers, same box. Name on the map -> image file. Using the name
# "Minerals" replaces the practice minerals layer.
EXTRA_LAYERS = {}                       # e.g. {"Minerals": "gale_minerals.png"}

OUTPUT_HTML = "mars_map.html"


# =====================================================================
# STEP 2 - GET THE ELEVATION  (a grid where each pixel is a height, in m)
# =====================================================================
def make_fake_terrain(h, w, px, seed):
    """Invent a landscape h pixels tall and w wide (px = meters per pixel):
    gentle rolling ground + a big mound + one crater with a steep rim."""
    rng = np.random.default_rng(seed)
    elev = np.zeros((h, w))
    k = 100 / px           # sizes below are in "100 m pixels", k converts them to this grid
    # Rolling ground: smooth random noise at four sizes, big to small.
    for sigma, height in [(25 * k, 90), (10 * k, 25), (4 * k, 6), (1.5 * k, 1.5)]:
        noise = ndimage.gaussian_filter(rng.normal(size=(h, w)), sigma)
        elev += height * noise / noise.std()
    rows, cols = np.mgrid[0:h, 0:w]
    # A mound on the right side (like Mount Sharp in Gale).
    elev += 650 * np.exp(-(((rows - 0.35 * h) ** 2 + (cols - 0.80 * w) ** 2) / (2 * (22 * k) ** 2)))
    # A crater between the habitat and the target. The route has to go around it.
    r = np.hypot(rows - 0.42 * h, cols - 0.36 * w)
    elev += -110 * np.exp(-(r / (10 * k)) ** 2) + 130 * np.exp(-((r - 13 * k) / (3.2 * k)) ** 2)
    return elev


def save_overview(src, window):
    """Picture of the WHOLE file with the cropped part as a red box (helps you pick CROP_CENTER)."""
    import matplotlib.patches as mpatches
    from rasterio.enums import Resampling
    shrink = max(1.0, max(src.width, src.height) / 900)
    ow, oh = max(1, int(src.width / shrink)), max(1, int(src.height / shrink))
    print("Making file_overview.png (a big file can take a minute)...")
    ov = src.read(1, out_shape=(oh, ow), resampling=Resampling.average, masked=True).astype("float64").filled(np.nan)
    ov = np.ma.masked_where(~np.isfinite(ov) | (np.abs(ov) > 1e10), ov)
    fig, ax = plt.subplots(figsize=(9, 9 * oh / ow + 0.9), dpi=110)
    ax.imshow(ov, cmap="terrain", extent=[0, 1, 1, 0], aspect="auto")
    ax.add_patch(mpatches.Rectangle((window.col_off / src.width, window.row_off / src.height),
                                    window.width / src.width, window.height / src.height,
                                    fill=False, edgecolor="red", linewidth=2.5))
    ax.set_xticks(np.arange(0, 1.01, 0.1)); ax.set_yticks(np.arange(0, 1.01, 0.1))
    ax.grid(color="white", alpha=0.35)
    ax.set_title("Whole file. Red box = the part the map uses.\n"
                 "CROP_CENTER = (across, down), each from 0 to 1", fontsize=10)
    fig.tight_layout(); fig.savefig("file_overview.png"); plt.close(fig)


def load_real_elevation(path):
    """Read (a part of) a GeoTIFF. Returns (elevation grid, meters per pixel)."""
    import rasterio                        # imported here so week 1 works without it
    from rasterio.enums import Resampling
    from rasterio.windows import Window
    with rasterio.open(path) as src:
        geographic = src.crs is not None and src.crs.is_geographic
        if REAL_METERS_PER_PIXEL is not None:
            px = REAL_METERS_PER_PIXEL
        elif geographic:
            raise SystemExit("The file is in degrees. Set REAL_METERS_PER_PIXEL in STEP 1.")
        else:
            px = abs(src.transform.a)
        print(f"File: {src.width} x {src.height} pixels, {px:g} m per pixel "
              f"= {src.width * px / 1000:.0f} x {src.height * px / 1000:.0f} km")
        # 1) Which part of the file do we use?
        if CROP_SIZE_KM:
            win_w = int(min(src.width, CROP_SIZE_KM[0] * 1000 / px))
            win_h = int(min(src.height, CROP_SIZE_KM[1] * 1000 / px))
        else:
            win_w, win_h = src.width, src.height
        col0 = int(np.clip(CROP_CENTER[0] * src.width - win_w / 2, 0, src.width - win_w))
        row0 = int(np.clip(CROP_CENTER[1] * src.height - win_h / 2, 0, src.height - win_h))
        window = Window(col0, row0, win_w, win_h)
        # 2) Shrink WHILE reading, so a huge file never fills your computer's memory.
        shrink = max(1.0, max(win_w, win_h) / MAX_REAL_PIXELS)
        out_w, out_h = max(1, int(win_w / shrink)), max(1, int(win_h / shrink))
        data = src.read(1, window=window, out_shape=(out_h, out_w), resampling=Resampling.average, masked=True)
        elev = data.astype("float64").filled(np.nan)       # missing data -> nan
        factor = win_w / out_w                              # how much bigger each pixel got
        if SAVE_OVERVIEW:
            save_overview(src, window)
    elev[np.abs(elev) > 1e10] = np.nan                     # junk "no data" numbers
    px *= factor
    # Fill holes (missing data) with the nearest valid value.
    if np.isnan(elev).any():
        idx = ndimage.distance_transform_edt(np.isnan(elev), return_distances=False, return_indices=True)
        elev = elev[tuple(idx)]
    return elev, px


if ELEVATION_FILE:
    elevation, meters_per_pixel = load_real_elevation(ELEVATION_FILE)
    print(f"Loaded {ELEVATION_FILE}: {elevation.shape[1]} x {elevation.shape[0]} pixels, "
          f"{meters_per_pixel:.0f} m per pixel")
else:
    elevation = make_fake_terrain(GRID_HEIGHT, GRID_WIDTH, FAKE_METERS_PER_PIXEL, RANDOM_SEED)
    meters_per_pixel = FAKE_METERS_PER_PIXEL
    print("Using FAKE terrain. Set ELEVATION_FILE in STEP 1 for real data.")

H, W = elevation.shape
if not all(0 <= r < H and 0 <= c < W for r, c in (START, END)):
    print(f"NOTE: START/END are outside this map ({H} rows x {W} columns), so default spots are used.")
    print("      Open the page, hover over the map to read pixel positions, then set START and END in STEP 1.")
    START = (int(0.50 * H), int(0.25 * W))
    END = (int(0.32 * H), int(0.475 * W))


# =====================================================================
# STEP 3 - SLOPE  (how steep is each pixel, in degrees)
# =====================================================================
# np.gradient gives the height change per meter going down (rows) and right (columns).
# Combine the two directions, then turn "rise over run" into an angle.
d_row, d_col = np.gradient(elevation, meters_per_pixel)
slope_deg = np.degrees(np.arctan(np.hypot(d_row, d_col)))


# =====================================================================
# STEP 4 - HILLSHADE  (shading so the flat grid looks 3D)
# =====================================================================
# Pretend the sun is in the north-west, 45 degrees up. Pixels that face the
# sun are bright, pixels that face away are dark. "exaggeration" stretches
# the heights so small hills show up better. It only changes the picture,
# not the slope numbers used for safety.
def hillshade(elev, px, exag, azimuth_deg=315, altitude_deg=45):
    dr, dc = np.gradient(elev * exag, px)
    slope = np.arctan(np.hypot(dr, dc))
    aspect = np.arctan2(dr, -dc)           # direction the ground faces
    az = np.radians(360 - azimuth_deg + 90)
    zen = np.radians(90 - altitude_deg)
    shade = np.cos(zen) * np.cos(slope) + np.sin(zen) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)

shade = hillshade(elevation, meters_per_pixel, exaggeration)


# =====================================================================
# STEP 5 - HAZARD SCORE  (0 = easy ground, 1 = do not go here)
# =====================================================================
# Mostly slope, plus a bit for "bumpy" ground (height changes in a 5 x 5 box).
mean = ndimage.uniform_filter(elevation, 5)
bumpiness = np.sqrt(np.clip(ndimage.uniform_filter(elevation ** 2, 5) - mean ** 2, 0, None))
bumpiness = np.clip(bumpiness / (np.percentile(bumpiness, 95) + 1e-9), 0, 1)
hazard = np.clip(0.8 * slope_deg / MAX_SLOPE_DEG + 0.2 * bumpiness, 0, 1)

# The route finder works on a "cost" map: cheap = easy, expensive = avoid.
# Slopes over the limit get a huge cost, so the route only crosses them if there is no other way.
cost = 1 + 10 * hazard ** 2
cost[slope_deg > MAX_SLOPE_DEG] += 1000


# =====================================================================
# STEP 6 - ROUTE  (cheapest path from START to END, then the numbers)
# =====================================================================
path, _ = route_through_array(cost, START, END, fully_connected=True, geometric=True)
path = np.array(path)                      # list of (row, col) pixels

# Walk along the route and add up each little step in 3D (sideways + up/down).
step_rows = np.diff(path[:, 0]) * meters_per_pixel
step_cols = np.diff(path[:, 1]) * meters_per_pixel
step_up = np.diff(elevation[path[:, 0], path[:, 1]])
step_len = np.sqrt(step_rows ** 2 + step_cols ** 2 + step_up ** 2)      # meters
along_m = np.concatenate([[0], np.cumsum(step_len)])                    # distance walked so far

distance_km = along_m[-1] / 1000
max_slope_on_route = slope_deg[path[:, 0], path[:, 1]].max()
one_way_hours = distance_km / WALK_SPEED_KMH
round_trip_hours = 2 * one_way_hours
farthest_km = np.hypot(path[:, 0] - START[0], path[:, 1] - START[1]).max() * meters_per_pixel / 1000
plan_hours = round_trip_hours + STOPS_HOURS + MARGIN_HOURS     # time the plan needs
spare_hours = SUIT_HOURS - plan_hours                          # time left over

# --- The go/no-go rule: every check must pass --------------------------
checks = {
    f"Round trip + stops + margin = {plan_hours:.1f} h, suit lasts {SUIT_HOURS:.1f} h":
        spare_hours >= 0,
    f"Steepest ground on route {max_slope_on_route:.1f} deg, limit is {MAX_SLOPE_DEG} deg":
        max_slope_on_route <= MAX_SLOPE_DEG,
    f"Farthest point {farthest_km:.1f} km, return ring is {RETURN_RING_KM:.1f} km":
        farthest_km <= RETURN_RING_KM,
}
go = all(checks.values())

print(f"\n=== Briefing numbers: {SITE_NAME} ===")
print(f"  Route distance:      {distance_km:.2f} km")
print(f"  Steepest slope:      {max_slope_on_route:.1f} deg")
print(f"  Round trip + stops:  {round_trip_hours + STOPS_HOURS:.1f} h")
print(f"  Time spare:          {spare_hours:+.1f} h")
print(f"  Farthest from base:  {farthest_km:.2f} km")
for text, ok in checks.items():
    print(f"  [{'pass' if ok else 'FAIL'}] {text}")
print(f"  DECISION: {'GO' if go else 'NO-GO'}\n")

# Elevation chart for the Designer: height along the route.
fig, ax = plt.subplots(figsize=(7, 2.6), dpi=150)
ax.fill_between(along_m / 1000, elevation[path[:, 0], path[:, 1]], elevation.min(), color="#c1440e", alpha=0.35)
ax.plot(along_m / 1000, elevation[path[:, 0], path[:, 1]], color="#c1440e")
ax.set_xlabel("Distance along route (km)")
ax.set_ylabel("Height (m)")
ax.set_title(f"Elevation profile - {SITE_NAME}", fontsize=10)
ax.margins(x=0)
fig.tight_layout()
fig.savefig("elevation_profile.png")
plt.close(fig)


# =====================================================================
# STEP 7 - BUILD THE PAGE  (layer pictures + numbers -> one HTML file)
# =====================================================================
# 7a. A sharper copy of the heights. Smooth curves between the pixels, so the
#     shading and slopes are drawn in fine detail instead of big soft blocks.
up = max(1, min(round(2400 / W), int((5e6 / (H * W)) ** 0.5)))
elev_up = ndimage.zoom(elevation, up, order=3) if up > 1 else elevation
px_up = meters_per_pixel / up
dr_up, dc_up = np.gradient(elev_up, px_up)
slope_up = np.degrees(np.arctan(np.hypot(dr_up, dc_up)))
shade_up = hillshade(elev_up, px_up, exaggeration)
size_k = 100 / meters_per_pixel     # sizes fake features in meters, not pixels


def to_uri(rgba, fmt="PNG"):
    """A picture (RGBA numbers 0-1) -> text that can live inside the HTML file."""
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype("uint8"))
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=90)
    else:
        img.save(buf, "PNG", optimize=True)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def file_to_uri(path):
    """An image file from the Data role -> text that can live inside the HTML file."""
    kind = "jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "png"
    with open(path, "rb") as f:
        return f"data:image/{kind};base64," + base64.b64encode(f.read()).decode()


def colors_of(cmap, lo, hi, n=5):
    """A few colors from a colormap, for the legend bars."""
    return [matplotlib.colors.to_hex(cmap(x)) for x in np.linspace(lo, hi, n)]


images = {}      # layer name -> picture
legends = {}     # layer name -> legend text + colors
opacity = {}     # layer name -> how see-through (1 = solid)

# --- Layer: Terrain (shaded relief in Mars colors) ----------------------
if TERRAIN_IMAGE:
    images["Terrain"] = file_to_uri(TERRAIN_IMAGE)
else:
    mars = LinearSegmentedColormap.from_list(
        "mars", ["#2a1710", "#6e3a22", "#b8652f", "#dd9a58", "#f3cf9a"])
    height01 = (elev_up - elev_up.min()) / (np.ptp(elev_up) + 1e-9)
    terrain = mars(height01)                                   # low = dark, high = light
    shade_look = shade_up
    if not ELEVATION_FILE:
        # Fake terrain has no fine detail, so add a little gravel-like texture to the
        # PICTURE only (the slope numbers are not touched). Real data brings its own.
        grit = ndimage.gaussian_filter(np.random.default_rng(RANDOM_SEED + 2).normal(size=elev_up.shape), 1.1)
        shade_look = hillshade(elev_up + 0.9 * grit / grit.std(), px_up, exaggeration)
    terrain[..., :3] *= np.clip(0.30 + 0.95 * shade_look, 0, 1.2)[..., None]   # add shadows
    images["Terrain"] = to_uri(terrain, "JPEG")

# --- Layer: Contours (lines of equal height) ----------------------------
if CONTOUR_EVERY_M:
    step = CONTOUR_EVERY_M
else:                                     # about 25 lines: 1, 2, 5, 10, 20, 50 ... meters
    raw = max(np.ptp(elevation) / 25, 1e-6)
    mag = 10 ** np.floor(np.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
level = np.floor(elev_up / step).astype(int)
thin = np.zeros(level.shape, bool)
bold = np.zeros(level.shape, bool)        # every 5th line is drawn thicker
for sl_a, sl_b in [((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
                   ((slice(None, -1), slice(None)), (slice(1, None), slice(None)))]:
    changed = level[sl_a] != level[sl_b]
    thin[sl_a] |= changed
    bold[sl_a] |= changed & (np.maximum(level[sl_a], level[sl_b]) % 5 == 0)
bold = ndimage.binary_dilation(bold)
contours = np.zeros(level.shape + (4,))
contours[..., :3] = 1.0
contours[..., 3] = np.where(bold, 0.65, np.where(thin, 0.28, 0.0))
images["Contours"] = to_uri(contours)
legends["Contours"] = {"label": f"Contour lines every {step:g} m (thicker every {5 * step:g} m)",
                       "colors": ["#ffffff"]}

# --- Layer: Steep slopes (clear where easy, yellow -> red where steep) ---
t = np.clip((slope_up - SLOPE_SHOW_FROM) / (MAX_SLOPE_DEG - SLOPE_SHOW_FROM), 0, 1)
steep = plt.cm.YlOrRd(0.15 + 0.85 * t)
steep[..., 3] = 0.85 * np.clip((slope_up - SLOPE_SHOW_FROM + 2) / 4, 0, 1)
images["Steep slopes"] = to_uri(steep)
legends["Steep slopes"] = {
    "label": f"Slope {SLOPE_SHOW_FROM}\u00b0 to {MAX_SLOPE_DEG}\u00b0+ (red = over the walking limit)",
    "colors": colors_of(plt.cm.YlOrRd, 0.15, 1.0)}

# --- Layer: Temperature  (FAKE numbers: Science replaces these) ---------
# THIS IS THE PATTERN TO COPY for a new layer (e.g. "Radiation"):
#   1) make a grid of numbers   2) turn it into colors   3) put it in images
# Then add the layer name to a preset in `views` (STEP 1) and to LAYER_ORDER below.
shade_soft = ndimage.gaussian_filter(shade, 1.5)
temperature_c = -60 + 40 * shade_soft - 0.015 * (elevation - elevation.mean())
temp01 = (temperature_c - temperature_c.min()) / (np.ptp(temperature_c) + 1e-9)
temp_rgba = plt.cm.coolwarm(temp01)
temp_rgba[..., 3] = 0.6
images["Temperature"] = to_uri(temp_rgba)
legends["Temperature"] = {
    "label": f"Air temperature {temperature_c.min():.0f} to {temperature_c.max():.0f} \u00b0C (practice values)",
    "colors": colors_of(plt.cm.coolwarm, 0.0, 1.0)}

# --- Layer: Minerals  (FAKE clay patches around the target) -------------
rng = np.random.default_rng(RANDOM_SEED + 1)
blobs = ndimage.gaussian_filter(rng.normal(size=(H, W)), 10 * size_k)
blobs = (blobs - blobs.mean()) / blobs.std()
rows_g, cols_g = np.mgrid[0:H, 0:W]
near_target = np.exp(-(((rows_g - END[0]) ** 2 + (cols_g - END[1]) ** 2) / (2 * (18 * size_k) ** 2)))
clay = np.clip((blobs + 2.5 * near_target - 0.9) / 2.2, 0, 1) ** 1.3     # soft edges, stronger near the target
minerals = np.zeros((H, W, 4))
minerals[..., 0], minerals[..., 1], minerals[..., 2] = 0.66, 0.42, 1.0
minerals[..., 3] = 0.85 * clay
images["Minerals"] = to_uri(minerals)
legends["Minerals"] = {"label": "Clay-rich ground (practice data)", "colors": ["#a96bff"]}

# --- Layers from the Data role (images of the same box) -----------------
for layer_name, image_file in EXTRA_LAYERS.items():
    images[layer_name] = file_to_uri(image_file)
    legends[layer_name] = {"label": layer_name, "colors": ["#a96bff"]}
    opacity[layer_name] = 0.7

# Order of the checkboxes (and the order they are stacked, bottom to top).
LAYER_ORDER = ["Terrain", "Contours", "Steep slopes", "Temperature", "Minerals"]
LAYER_ORDER += [n for n in EXTRA_LAYERS if n not in LAYER_ORDER]
LAYER_ORDER += ["Route", "Return ring"]

# 7b. Numbers for the hover readout, packed small (the page unpacks them).
elev_min, elev_range = float(elevation.min()), float(np.ptp(elevation)) or 1.0
elev_packed = np.round((elevation - elev_min) / elev_range * 65535).astype("<u2")
slope_packed = np.clip(np.round(slope_deg * 4), 0, 255).astype("u1")
pack = lambda arr: base64.b64encode(arr.tobytes()).decode()

# 7c. Markers: habitat, stops (spread evenly along the route), target.
def point_at(fraction):
    i = int(np.searchsorted(along_m, along_m[-1] * fraction))
    return min(i, len(path) - 1)

markers = [{"name": HABITAT_NAME, "r": int(START[0]), "c": int(START[1]), "km": 0.0}]
for n, stop in enumerate(STOP_NAMES):
    i = point_at((n + 1) / (len(STOP_NAMES) + 1))
    markers.append({"name": stop, "r": int(path[i, 0]), "c": int(path[i, 1]), "km": round(along_m[i] / 1000, 2)})
markers.append({"name": TARGET_NAME, "r": int(END[0]), "c": int(END[1]), "km": round(distance_km, 2)})

route_heights = elevation[path[:, 0], path[:, 1]]
route_slopes = slope_deg[path[:, 0], path[:, 1]]

data = {
    "subtitle": ("Generated terrain for demonstration. Real version uses orbital imagery and elevation data."
                 if not ELEVATION_FILE else f"{SITE_NAME}. Elevation from {os.path.basename(ELEVATION_FILE)}."),
    "H": H, "W": W, "mpp": meters_per_pixel,
    "layers": LAYER_ORDER, "images": images, "legends": legends, "opacity": opacity,
    "views": {k: [n for n in v if n in LAYER_ORDER] for k, v in views.items()},
    "startView": start_view,
    "elev": pack(elev_packed), "elevMin": elev_min, "elevRange": elev_range, "slope": pack(slope_packed),
    "route": path.flatten().tolist(),
    "routeKm": np.round(along_m / 1000, 3).tolist(),
    "routeM": np.round(route_heights, 1).tolist(),
    "routeSlope": np.round(route_slopes, 1).tolist(),
    "markers": markers,
    "habitat": [int(START[0]), int(START[1])],
    "distanceKm": float(distance_km), "maxSlope": float(max_slope_on_route),
    "farthestKm": float(farthest_km), "relief": float(route_heights.max() - route_heights.min()),
    "limits": {"speed": WALK_SPEED_KMH, "suit": SUIT_HOURS, "stops": STOPS_HOURS,
               "margin": MARGIN_HOURS, "slope": MAX_SLOPE_DEG, "ring": RETURN_RING_KM},
    "conditions": CONDITIONS,
    "supplies": SUIT_SUPPLIES, "suitBase": SUIT_HOURS,
    "target": {"elev": float(elevation[END]), "slope": float(slope_deg[END]),
               "temp": float(temperature_c[END]), "clay": float(clay[END]),
               "bearing": float(np.degrees(np.arctan2(END[1] - START[1], -(END[0] - START[0]))) % 360),
               "dir": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((np.degrees(np.arctan2(END[1] - START[1], -(END[0] - START[0]))) % 360 + 22.5) // 45) % 8]},
}


# =====================================================================
# THE PAGE  (HTML + CSS + JavaScript). Designer: the colors are the
# variables at the top of the <style> block, change them there.
# =====================================================================
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marswalk planner</title>
<style>
:root{
  --bg:#121212; --card:#1c1c1f; --text:#ececec; --muted:#a7a7ae; --line:#3a3a40;
  --accent:#7fb2ff; --accent-bg:#1d2a40;
  --go-bg:#12301c; --go-text:#7be28a; --nogo-bg:#3a1212; --nogo-text:#ff8a80;
  --route:#4fc3f7; --profile:#7d75d6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.45 Roboto,"Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:1180px;margin:0 auto;padding:22px 20px 60px}
h1{margin:0 0 4px;font-size:30px;font-weight:600}
h2{margin:30px 0 8px;font-size:19px;font-weight:500}
.muted{color:var(--muted)}
#subtitle{margin:0 0 16px}
.verdict{display:inline-block;padding:10px 18px;border-radius:12px;font-weight:600;font-size:20px;margin-bottom:16px}
.verdict.go{background:var(--go-bg);color:var(--go-text)}
.verdict.nogo{background:var(--nogo-bg);color:var(--nogo-text)}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:10px}
.chips{display:flex;flex-wrap:wrap;gap:10px}
.chip{display:inline-flex;align-items:center;gap:9px;padding:10px 18px;border:1px solid var(--line);
  border-radius:12px;background:transparent;color:var(--text);font:inherit;cursor:pointer;user-select:none}
.chip:hover{border-color:var(--muted)}
.chip.active{border-color:var(--accent);background:var(--accent-bg)}
.chip input{width:20px;height:20px;accent-color:var(--accent);margin:0;cursor:pointer}
#toggles{margin-bottom:14px}
.mapwrap{border-radius:18px;overflow:hidden;background:#0b0b0d;line-height:0}
#map{width:100%;height:auto;display:block;cursor:grab;touch-action:none}
#legend{display:flex;flex-wrap:wrap;gap:8px 26px;margin:14px 0 4px;min-height:24px}
.leg{display:flex;align-items:center;gap:10px;font-size:17px}
.leg .bar{display:inline-block;width:140px;height:22px;border-radius:3px;border:1px solid #ffffff22}
.leg .sw{width:22px}
#readout{margin:6px 0 20px;min-height:24px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:26px}
.card{background:var(--card);border-radius:14px;padding:14px 18px}
.card .k{color:var(--muted);font-size:17px}
.card .v{font-size:40px;font-weight:600;line-height:1.15}
.good{color:var(--go-text)} .bad{color:var(--nogo-text)}
.slider{display:grid;grid-template-columns:200px 1fr 110px;align-items:center;gap:14px;margin:8px 0}
.slider input{width:100%;accent-color:var(--accent)}
.slider b{text-align:right;font-size:20px;white-space:nowrap}
@media(max-width:620px){.slider{grid-template-columns:1fr 100px}.slider label{grid-column:1/3}
  .stats{grid-template-columns:1fr 1fr;gap:10px}.card{padding:12px 14px}.card .k{font-size:15px}.card .v{font-size:30px}
  .leg .bar{width:100px}.leg{font-size:15px}.chip{padding:9px 14px}}
#rule{margin:10px 0}
#checks{list-style:none;padding:0;margin:8px 0}
#checks li{padding:3px 0}
#profile{width:100%;height:auto;display:block;background:var(--card);border-radius:14px;touch-action:pan-y;cursor:crosshair}
#conditions{margin:0;font-size:20px;line-height:1.5}
.mapwrap{position:relative}
.zoomctl{position:absolute;top:12px;right:12px;display:flex;gap:6px;line-height:1}
.zoomctl button{min-width:40px;height:40px;border-radius:10px;border:1px solid var(--line);background:#1c1c1fcc;color:var(--text);font:inherit;font-size:18px;cursor:pointer}
.gauge{display:grid;grid-template-columns:150px 1fr 200px;gap:12px;align-items:center;margin:8px 0}
.gbar{height:16px;background:var(--card);border-radius:8px;overflow:hidden}
.gbar i{display:block;height:100%}
.gbar i.good{background:var(--go-text)} .gbar i.warn{background:#ffca28} .gbar i.bad{background:var(--nogo-text)}
#legs{width:100%;border-collapse:collapse}
#legs td,#legs th{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
#stay{margin-top:12px;font-size:18px}
@media(max-width:620px){.gauge{grid-template-columns:1fr 1fr}.gauge .gbar{grid-column:1/3;order:3}}
</style></head>
<body><main>
<h1>Marswalk planner</h1>
<p id="subtitle" class="muted"></p>
<div id="verdict" class="verdict"></div>
<div class="row"><span class="muted">Views:</span><div id="views" class="chips"></div></div>
<div id="toggles" class="chips"></div>
<div class="mapwrap"><canvas id="map"></canvas><div class="zoomctl"><button id="zin" title="Zoom in">+</button><button id="zout" title="Zoom out">−</button><button id="zreset">Reset</button></div></div>
<div id="legend"></div>
<p id="readout" class="muted">Hover or tap the map to read elevation and slope.</p>
<section class="stats" id="stats"></section>
<div class="slider"><label for="suit">Suit time available</label>
  <input id="suit" type="range" min="4" max="12" step="0.5"><b id="suitVal"></b></div>
<div class="slider"><label for="speed">Walking speed</label>
  <input id="speed" type="range" min="1" max="4" step="0.1"><b id="speedVal"></b></div>
<div class="slider"><label for="extra">Extra time at target</label><input id="extra" type="range" min="0" max="3" step="0.25" value="0"><b id="extraVal"></b></div>
<div class="slider"><label for="walk">Walk simulation</label><input id="walk" type="range" min="0" max="1000" value="0"><b><button id="play" class="chip">Play</button></b></div>
<div id="walkinfo" class="verdict go"></div>
<p id="rule" class="muted"></p>
<ul id="checks"></ul>
<h2>EVA suit status when the plan ends</h2><div id="suit-box"></div><div id="stay" class="verdict"></div>
<h2>Route details</h2><section class="stats" id="dest"></section><div style="overflow-x:auto"><table id="legs"></table></div>
<h2>Elevation profile along the route</h2>
<canvas id="profile" width="1100" height="260"></canvas>
<h2>Conditions</h2>
<p id="conditions"></p>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const W = D.W, H = D.H, FONT = 'Roboto,"Segoe UI",system-ui,sans-serif';
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const b64 = s => Uint8Array.from(atob(s), ch => ch.charCodeAt(0));
const elevRaw = new Uint16Array(b64(D.elev).buffer), slopeRaw = b64(D.slope);
const elevAt = (r, c) => D.elevMin + elevRaw[r * W + c] / 65535 * D.elevRange;
const slopeAt = (r, c) => slopeRaw[r * W + c] / 4;

let on = new Set(D.views[D.startView] || []), activeView = D.startView;
let hover = null, routeHover = null, ready = false;
const imgs = {};

// ---------- controls ----------
Object.keys(D.views).forEach(name => {
  const b = document.createElement('button');
  b.className = 'chip'; b.textContent = name; b.dataset.view = name;
  b.onclick = () => { on = new Set(D.views[name]); activeView = name; sync(); draw(); };
  $('views').appendChild(b);
});
D.layers.forEach(name => {
  const l = document.createElement('label'); l.className = 'chip';
  const i = document.createElement('input'); i.type = 'checkbox'; i.dataset.layer = name;
  i.onchange = () => { i.checked ? on.add(name) : on.delete(name); activeView = null; sync(); draw(); };
  l.append(i, name); $('toggles').appendChild(l);
});
function sync() {
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === activeView));
  document.querySelectorAll('[data-layer]').forEach(i => i.checked = on.has(i.dataset.layer));
  const lg = $('legend'); lg.innerHTML = '';
  D.layers.filter(n => on.has(n) && D.legends[n]).forEach(n => {
    const L = D.legends[n], d = document.createElement('div'); d.className = 'leg';
    const bar = document.createElement('span'); bar.className = 'bar' + (L.colors.length < 2 ? ' sw' : '');
    bar.style.background = L.colors.length > 1 ? 'linear-gradient(90deg,' + L.colors.join(',') + ')' : L.colors[0];
    const t = document.createElement('span'); t.textContent = L.label;
    d.append(bar, t); lg.appendChild(d);
  });
}

// ---------- map ----------
const cv = $('map'), ctx = cv.getContext('2d');
function halo(text, x, y, s, size, align) {
  ctx.font = '600 ' + size * s + 'px ' + FONT; ctx.textAlign = align || 'left';
  ctx.lineJoin = 'round'; ctx.lineWidth = 3.5 * s; ctx.strokeStyle = 'rgba(0,0,0,.8)';
  ctx.strokeText(text, x, y); ctx.fillStyle = '#fff'; ctx.fillText(text, x, y);
}
let V = { x: 0, y: 0, w: 1 }, baseAsp = 0.5, pnrIdx = null, walkIdx = null, walkTimer = null;     // V = the part of the map you see (0-1)
function fitMap() {                  // canvas = screen size x pixel density, so lines and text stay crisp
  const dpr = Math.min(window.devicePixelRatio || 1, 2), cssW = cv.parentElement.clientWidth || 1000;
  cv.width = Math.round(cssW * dpr); cv.height = Math.round(cv.width * baseAsp);
}
function draw() {
  if (!ready) return;
  const cw = cv.width, ch = cv.height, s = cw / cv.getBoundingClientRect().width;
  const X = c => ((c + 0.5) / W - V.x) / V.w * cw, Y = r => ((r + 0.5) / H - V.y) / V.w * ch;
  ctx.clearRect(0, 0, cw, ch);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  D.layers.forEach(n => {
    if (imgs[n] && on.has(n)) { ctx.globalAlpha = D.opacity[n] ?? 1; const im = imgs[n], iw = im.naturalWidth, ih = im.naturalHeight; ctx.drawImage(im, V.x * iw, V.y * ih, V.w * iw, V.w * ih, 0, 0, cw, ch); }
  });
  ctx.globalAlpha = 1;
  const hr = D.habitat[0], hc = D.habitat[1];
  if (on.has('Return ring')) {
    const rad = D.limits.ring * 1000 / D.mpp / W * cw / V.w;
    ctx.setLineDash([9 * s, 7 * s]); ctx.lineWidth = 2 * s; ctx.strokeStyle = '#fff';
    ctx.beginPath(); ctx.arc(X(hc), Y(hr), rad, 0, 6.2832); ctx.stroke(); ctx.setLineDash([]);
    halo(D.limits.ring + ' km return ring', X(hc), Math.min(Y(hr) + rad + 18 * s, ch - 8 * s), s, 12, 'center');
  }
  if (on.has('Route')) {
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.beginPath(); for (let i = 0; i < D.route.length; i += 2) ctx[i ? 'lineTo' : 'moveTo'](X(D.route[i + 1]), Y(D.route[i]));
    ctx.lineWidth = 7 * s; ctx.strokeStyle = 'rgba(0,0,0,.55)'; ctx.stroke();
    ctx.lineWidth = 3.5 * s; ctx.strokeStyle = css('--route'); ctx.stroke();
    D.markers.forEach(m => {
      ctx.beginPath(); ctx.arc(X(m.c), Y(m.r), 6 * s, 0, 6.2832);
      ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 2 * s; ctx.strokeStyle = 'rgba(0,0,0,.7)'; ctx.stroke();
      const last = m === D.markers[D.markers.length - 1];
      halo(m.name, X(m.c), Y(m.r) + (last ? -14 : 20) * s, s, 12, 'center');
    });
  }
  if (on.has('Route') && pnrIdx != null) {
    const px = X(D.route[pnrIdx * 2 + 1]), py = Y(D.route[pnrIdx * 2]);
    ctx.beginPath(); ctx.arc(px, py, 8 * s, 0, 6.2832); ctx.fillStyle = '#ff5252'; ctx.fill();
    ctx.lineWidth = 2 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
    halo('Point of no return', px, py - 14 * s, s, 12, 'center');
  }
  const kmView = V.w * W * D.mpp / 1000;                            // scale bar
  const bar = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10].filter(v => v <= kmView * 0.4).pop() || 0.05;
  const bx = 16 * s, by = ch - 18 * s, bw = bar / kmView * cw;
  ctx.lineWidth = 4 * s; ctx.strokeStyle = 'rgba(0,0,0,.8)'; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + bw, by); ctx.stroke();
  ctx.lineWidth = 2 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
  halo(bar + ' km   (zoom x' + (1 / V.w).toFixed(1) + ')', bx, by - 8 * s, s, 12, 'left');
  if (walkIdx != null) {
    const wx = X(D.route[walkIdx * 2 + 1]), wy = Y(D.route[walkIdx * 2]);
    ctx.beginPath(); ctx.arc(wx, wy, 7 * s, 0, 6.2832); ctx.fillStyle = '#ff9800'; ctx.fill();
    ctx.lineWidth = 2.5 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
    halo('Astronaut', wx, wy - 13 * s, s, 12, 'center');
  }
  const mark = (p, color) => { ctx.beginPath(); ctx.arc(X(p.c), Y(p.r), 8 * s, 0, 6.2832);
    ctx.lineWidth = 2.5 * s; ctx.strokeStyle = color; ctx.stroke(); };
  if (hover) mark(hover, '#fff');
  if (routeHover) mark(routeHover, '#ffd400');
}
function mapPoint(e) {
  const rc = cv.getBoundingClientRect();
  return { r: Math.max(0, Math.min(H - 1, Math.floor((V.y + (e.clientY - rc.top) / rc.height * V.w) * H))),
           c: Math.max(0, Math.min(W - 1, Math.floor((V.x + (e.clientX - rc.left) / rc.width * V.w) * W))) };
}
function onMap(e) {
  const p = mapPoint(e); hover = p; routeHover = null;
  const km = Math.hypot(p.r - D.habitat[0], p.c - D.habitat[1]) * D.mpp / 1000;
  $('readout').textContent = 'Elevation ' + elevAt(p.r, p.c).toFixed(0) + ' m  \u00b7  Slope ' +
    slopeAt(p.r, p.c).toFixed(1) + '\u00b0  \u00b7  ' + km.toFixed(1) + ' km from ' + D.markers[0].name.toLowerCase() +
    '  \u00b7  pixel (row ' + p.r + ', col ' + p.c + ')';
  draw();
}
let drag = null;
const clampV = () => { V.w = Math.max(1 / 24, Math.min(1, V.w));
  V.x = Math.max(0, Math.min(1 - V.w, V.x)); V.y = Math.max(0, Math.min(1 - V.w, V.y)); };
function zoomAt(f, fx, fy) {         // fx, fy = where in the window (0-1) stays put while zooming
  const nx = V.x + fx * V.w, ny = V.y + fy * V.w; V.w = V.w / f; clampV();
  V.x = nx - fx * V.w; V.y = ny - fy * V.w; clampV(); draw();
}
const resetView = () => { V = { x: 0, y: 0, w: 1 }; draw(); };
cv.addEventListener('wheel', e => { e.preventDefault(); const rc = cv.getBoundingClientRect();
  zoomAt(e.deltaY < 0 ? 1.3 : 1 / 1.3, (e.clientX - rc.left) / rc.width, (e.clientY - rc.top) / rc.height); }, { passive: false });
cv.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, vx: V.x, vy: V.y };
  cv.setPointerCapture(e.pointerId); onMap(e); });
cv.addEventListener('pointermove', e => {
  if (drag && V.w < 1) { const rc = cv.getBoundingClientRect();
    V.x = drag.vx - (e.clientX - drag.x) / rc.width * V.w; V.y = drag.vy - (e.clientY - drag.y) / rc.height * V.w; clampV(); }
  onMap(e); });
cv.addEventListener('pointerup', () => { drag = null; });
cv.addEventListener('pointerleave', () => { hover = null; draw(); });
cv.addEventListener('dblclick', resetView);
$('zin').onclick = () => zoomAt(1.6, .5, .5); $('zout').onclick = () => zoomAt(1 / 1.6, .5, .5); $('zreset').onclick = resetView;
window.addEventListener('resize', () => { fitMap(); draw(); });

let loaded = 0; const names = Object.keys(D.images);
names.forEach(n => {
  const im = new Image();
  im.onload = () => {
    imgs[n] = im;
    if (++loaded === names.length) {
      const base = imgs.Terrain || im;
      baseAsp = base.naturalHeight / base.naturalWidth; fitMap();
      ready = true; draw();
    }
  };
  im.src = D.images[n];
});

// ---------- numbers, sliders, verdict ----------
const L = D.limits;
$('suit').value = L.suit; $('speed').value = L.speed;
function recalc() {
  const suit = +$('suit').value, speed = +$('speed').value;
  $('suitVal').textContent = suit.toFixed(1).replace('.0', '') + ' h';
  $('speedVal').textContent = speed.toFixed(1) + ' km/h';
  const trip = 2 * D.distanceKm / speed + L.stops, plan = trip + L.margin, spare = suit - plan;
  const okT = spare >= -1e-9, okS = D.maxSlope <= L.slope, okR = D.farthestKm <= L.ring;
  const sp = Math.round(spare * 10) / 10;
  const spareTxt = (sp > 0 ? '+' : sp < 0 ? '\u2212' : '') + Math.abs(sp).toFixed(1) + ' h';
  const card = (k, v, cls) => '<div class="card"><div class="k">' + k + '</div><div class="v ' + (cls || '') + '">' + v + '</div></div>';
  $('stats').innerHTML = card('Route distance', D.distanceKm.toFixed(1) + ' km') +
    card('Max slope on route', D.maxSlope.toFixed(1) + '\u00b0', okS ? '' : 'bad') +
    card('Round trip + stops', trip.toFixed(1) + ' h') +
    card('Time spare', spareTxt, okT ? 'good' : 'bad');
  const v = $('verdict'), go = okT && okS && okR;
  v.className = 'verdict ' + (go ? 'go' : 'nogo');
  v.textContent = go ? 'Verdict: go' : 'Verdict: no-go, ' +
    (!okT ? 'shorten route' : !okS ? 'route too steep' : 'too far from base');
  $('rule').textContent = 'Rule: go if round trip + ' + L.stops + ' h of stops + ' + Math.round(L.margin * 60) +
    ' min margin fits in suit time (walking at ' + speed.toFixed(1) + ' km/h).';
  const line = (ok, t) => '<li class="' + (ok ? 'good' : 'bad') + '">' + (ok ? '\u2713 ' : '\u2717 ') + t + '</li>';
  $('checks').innerHTML =
    line(okT, 'Time: round trip + stops + margin = ' + plan.toFixed(1) + ' h, suit gives ' + suit.toFixed(1) + ' h') +
    line(okS, 'Slope: steepest ground on route is ' + D.maxSlope.toFixed(1) + '\u00b0, limit is ' + L.slope + '\u00b0') +
    line(okR, 'Distance: farthest point is ' + D.farthestKm.toFixed(1) + ' km from base, return ring is ' + L.ring + ' km');
  suitPanel(suit, speed);
}
function suitPanel(suit, speed) {
  const extra = +$('extra').value; $('extraVal').textContent = Math.round(extra * 60) + ' min';
  const k = suit / D.suitBase, trip = 2 * D.distanceKm / speed + L.stops, need = trip + extra;
  let limit = Infinity, limName = '';
  $('suit-box').innerHTML = Object.keys(D.supplies).map(n => {
    const have = D.supplies[n] * k, left = have - need, pct = Math.max(0, left / have * 100);
    if (have < limit) { limit = have; limName = n; }
    const cls = left < L.margin ? 'bad' : left < L.margin + 0.5 ? 'warn' : 'good';
    return '<div class="gauge"><span>' + n + '</span><div class="gbar"><i class="' + cls + '" style="width:' + pct.toFixed(0) +
      '%"></i></div><b>' + pct.toFixed(0) + '% left (' + Math.max(0, left).toFixed(1) + ' h)</b></div>';
  }).join('');
  const maxExtra = limit - trip - L.margin, safe = maxExtra >= extra - 1e-9, mins = Math.max(0, Math.floor(maxExtra * 60));
  const st = $('stay'); st.className = 'verdict ' + (safe ? 'go' : 'nogo');
  st.textContent = safe
    ? (extra > 0 ? 'Staying ' + Math.round(extra * 60) + ' min longer is safe. ' : '') + 'You can stay up to ' + mins + ' min longer at the target (limit: ' + limName + ').'
    : 'Not safe: ' + Math.round(extra * 60) + ' min longer would use the ' + Math.round(L.margin * 60) + ' min reserve (' + limName + ' runs out first). ' +
      (mins > 0 ? 'Maximum extra time is ' + mins + ' min.' : 'Head back now.');
  const dmax = (limit - L.margin - L.stops) / 2 * speed;                 // farthest safe distance out
  pnrIdx = dmax < D.distanceKm ? Math.max(0, D.routeKm.findIndex(v => v >= dmax)) : null;
  $('suit-box').innerHTML += '<p class="muted">' + (pnrIdx == null
    ? 'The whole route is inside the safe range. Farthest safe distance out: ' + dmax.toFixed(1) + ' km.'
    : 'Point of no return at route km ' + Math.max(0, dmax).toFixed(1) + ': going farther, the suit cannot get you home with the reserve left.') + '</p>';
  const T = D.target, mk = D.markers;
  const card = (a, b) => '<div class="card"><div class="k">' + a + '</div><div class="v" style="font-size:30px">' + b + '</div></div>';
  $('dest').innerHTML = card('Target elevation', T.elev.toFixed(0) + ' m') + card('Direction from base', T.dir + ' (' + T.bearing.toFixed(0) + '\u00b0)') +
    card('Slope at target', T.slope.toFixed(1) + '\u00b0') + card('Air temperature there', T.temp.toFixed(0) + ' \u00b0C') +
    card('Clay at target', Math.round(T.clay * 100) + '%');
  const idx = mk.map(m => Math.max(D.routeKm.findIndex(v => v >= m.km - 1e-6), 0));
  let t = '<tr><th>Leg</th><th>Distance</th><th>Climb</th><th>Descent</th><th>Avg slope</th><th>Max slope</th><th>Walk time</th></tr>';
  for (let j = 1; j < idx.length; j++) {
    const a = idx[j - 1], b = idx[j]; let up = 0, dn = 0, sl = 0, mx = 0;
    for (let i = a + 1; i <= b; i++) { const d = D.routeM[i] - D.routeM[i - 1]; if (d > 0) up += d; else dn -= d; }
    for (let i = a; i <= b; i++) { sl += D.routeSlope[i]; mx = Math.max(mx, D.routeSlope[i]); }
    const km = D.routeKm[b] - D.routeKm[a];
    t += '<tr><td>' + mk[j - 1].name + ' to ' + mk[j].name + '</td><td>' + km.toFixed(2) + ' km</td><td>' + up.toFixed(0) + ' m</td><td>' +
      dn.toFixed(0) + ' m</td><td>' + (sl / (b - a + 1)).toFixed(1) + '\u00b0</td><td>' + mx.toFixed(1) + '\u00b0</td><td>' +
      Math.round(km / speed * 60) + ' min</td></tr>';
  }
  $('legs').innerHTML = t; walkUpdate();
}
$('suit').oninput = $('speed').oninput = $('extra').oninput = recalc;
function walkUpdate() {
  const f = +$('walk').value / 1000, i = Math.round(f * (D.routeKm.length - 1));
  walkIdx = f > 0 ? i : null;
  const box = $('walkinfo');
  if (walkIdx == null) { box.className = 'verdict go'; box.textContent = 'Move the slider or press Play to walk the route.'; draw(); return; }
  const speed = +$('speed').value, k = +$('suit').value / D.suitBase, km = D.routeKm[i], t = km / speed;
  let limit = Infinity, name = '';
  Object.keys(D.supplies).forEach(n => { const h = D.supplies[n] * k; if (h < limit) { limit = h; name = n; } });
  const left = limit - t, back = km / speed, ok = left - back >= L.margin - 1e-9;
  box.className = 'verdict ' + (ok ? 'go' : 'nogo');
  box.textContent = km.toFixed(2) + ' km out, ' + Math.round(t * 60) + ' min walked. ' + name + ' left: ' + Math.max(0, left * 60).toFixed(0) +
    ' min. Way back: ' + Math.round(back * 60) + ' min. ' + (ok ? 'Safe to continue.' : 'Turn back now.');
  draw();
}
$('walk').oninput = walkUpdate;
$('play').onclick = () => {
  if (walkTimer) { clearInterval(walkTimer); walkTimer = null; $('play').textContent = 'Play'; return; }
  if (+$('walk').value >= 1000) $('walk').value = 0;
  $('play').textContent = 'Pause';
  walkTimer = setInterval(() => {
    const w = $('walk'); w.value = +w.value + 4; walkUpdate();
    if (+w.value >= 1000) { clearInterval(walkTimer); walkTimer = null; $('play').textContent = 'Play'; }
  }, 40);
};
$('conditions').textContent = D.conditions; $('subtitle').textContent = D.subtitle;

// ---------- elevation profile ----------
const pv = $('profile'), pc = pv.getContext('2d');
function fitProfile() {              // chart keeps a sensible height on phones and wide screens
  const cssW = pv.getBoundingClientRect().width || 1000, dpr = 2;
  const cssH = Math.max(150, Math.min(260, cssW * 0.25));
  pv.width = Math.round(cssW * dpr); pv.height = Math.round(cssH * dpr); pv.style.height = cssH + 'px';
}
const pScale = () => pv.width / pv.getBoundingClientRect().width;     // internal px per screen px
const pPad = ps => ({ l: 14 * ps, r: 14 * ps, t: 40 * ps, b: 34 * ps });
function drawProfile(idx) {
  const ps = pScale(), P = pPad(ps), w = pv.width, h = pv.height;
  const m = D.routeM, km = D.routeKm, n = m.length, lo = Math.min(...m), hi = Math.max(...m), pad = (hi - lo) * 0.12 || 1;
  const x = i => P.l + (km[i] / km[n - 1]) * (w - P.l - P.r);
  const y = v => P.t + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (h - P.t - P.b);
  pc.clearRect(0, 0, w, h);
  pc.beginPath(); pc.moveTo(x(0), h - P.b); for (let i = 0; i < n; i++) pc.lineTo(x(i), y(m[i]));
  pc.lineTo(x(n - 1), h - P.b); pc.closePath(); pc.fillStyle = 'rgba(125,117,214,.5)'; pc.fill();
  pc.beginPath(); for (let i = 0; i < n; i++) pc[i ? 'lineTo' : 'moveTo'](x(i), y(m[i]));
  pc.lineWidth = 2.5 * ps; pc.lineJoin = 'round'; pc.strokeStyle = css('--profile'); pc.stroke();
  pc.fillStyle = css('--muted'); pc.font = 14 * ps + 'px ' + FONT;
  pc.textAlign = 'left'; pc.fillText(D.relief.toFixed(0) + ' m relief', P.l, 24 * ps);
  pc.fillText('0 km', P.l, h - 10 * ps); pc.textAlign = 'right'; pc.fillText(D.distanceKm.toFixed(1) + ' km', w - P.r, h - 10 * ps);
  D.markers.forEach(mk => { const i = Math.max(km.findIndex(v => v >= mk.km - 1e-6), 0);
    pc.beginPath(); pc.arc(x(i), y(m[i]), 4.5 * ps, 0, 6.2832); pc.fillStyle = '#fff'; pc.fill(); });
  if (idx != null) {
    pc.beginPath(); pc.moveTo(x(idx), P.t - 6 * ps); pc.lineTo(x(idx), h - P.b); pc.strokeStyle = '#ffd400'; pc.lineWidth = 2 * ps; pc.stroke();
    pc.beginPath(); pc.arc(x(idx), y(m[idx]), 5.5 * ps, 0, 6.2832); pc.fillStyle = '#ffd400'; pc.fill();
  }
}
function onProfile(e) {
  const rc = pv.getBoundingClientRect(), n = D.routeM.length, ps = pScale(), P = pPad(ps);
  const f = Math.max(0, Math.min(1, ((e.clientX - rc.left) * ps - P.l) / (pv.width - P.l - P.r)));
  const target = f * D.routeKm[n - 1]; let i = D.routeKm.findIndex(v => v >= target); if (i < 0) i = n - 1;
  routeHover = { r: D.route[i * 2], c: D.route[i * 2 + 1] }; hover = null;
  $('readout').textContent = 'Route km ' + D.routeKm[i].toFixed(2) + '  \u00b7  Elevation ' + D.routeM[i].toFixed(0) +
    ' m  \u00b7  Slope ' + D.routeSlope[i].toFixed(1) + '\u00b0';
  drawProfile(i); draw();
}
pv.addEventListener('pointermove', onProfile); pv.addEventListener('pointerdown', onProfile);
pv.addEventListener('pointerleave', () => { routeHover = null; drawProfile(); draw(); });

window.addEventListener('resize', () => { fitProfile(); drawProfile(); });
sync(); recalc(); fitProfile(); drawProfile();
</script></body></html>
"""

page = HTML_TEMPLATE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(page)
print(f"Saved {OUTPUT_HTML} ({len(page) / 1e6:.1f} MB) and elevation_profile.png. Open {OUTPUT_HTML} in your browser.")
