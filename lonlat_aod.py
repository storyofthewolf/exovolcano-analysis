#!/usr/bin/env python

"""
lonlat_aod.py - Longitude-latitude AOD snapshots for one case in any batch.

Standalone, one-off script. NOT part of the run_time_series.py/run_batch.py
pipeline and not wired into config.py's YAML schema on purpose: this is the
only place a full (time, lat, lon) field is kept in memory rather than
reduced to a zonal or global mean, and it exists for cases where a
literature AOD comparison is plume-local or regional rather than a global
or zonal mean (first used for Hunga Tonga against Khaykin/Taha -- see
CLAUDE.md / memory hunga-aod-comparison-basis in description_paper).

Reuses compute.py/optics.py unchanged; duplicates just enough of
run_time_series.py's dataset-loading and AOD setup to avoid pulling in the
full pipeline (scalar/profile/zonal sections, CLI flags) for a single-purpose
script.

Usage (run on the HPC login/compute node where the raw CAM archive lives --
the local remote_analysis/ tree only has already-reduced CSVs):

    python lonlat_aod.py --batch exovolc_hunga.yaml --case exovolc_hunga_fid \
        --days 1,4,10,30 --vent-lat -20.0 --vent-lon 185.0

--vent-lat/--vent-lon are optional; omit them to skip the vent marker
entirely for a case where it isn't meaningful.

Output:
    data/<case>/lonlat/aod_day<D>.csv     (lat x lon grid, day in filename)
    figures/<case>/lonlat/aod_day<D>.png  (map, vent marked if given)
"""

import os
import sys
import argparse

parser = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--batch', required=True, metavar='batch.yaml',
                     help='Batch YAML (looked up in experiments/, or a full path)')
parser.add_argument('--case', required=True, metavar='NAME',
                     help='Case name within the batch, e.g. exovolc_hunga_fid')
parser.add_argument('--days', default='1,4,10,30', metavar='D1,D2,...',
                     help='Comma-separated target days since eruption (default: 1,4,10,30)')
parser.add_argument('--vent-lat', type=float, default=None,
                     help='Vent latitude for an optional marker on the map')
parser.add_argument('--vent-lon', type=float, default=None,
                     help='Vent longitude (0-360 convention) for an optional marker')
parser.add_argument('--output-dir', default=None,
                     help='Parent for figures/ and data/ (default: repo figures/data)')
args = parser.parse_args()

if (args.vent_lat is None) != (args.vent_lon is None):
    parser.error('--vent-lat and --vent-lon must be given together')

target_days = [float(d) for d in args.days.split(',')]

# config.py resolves the batch/case from sys.argv[1] and the CASE env var,
# same mechanism run_time_series.py uses -- set both before importing it.
os.environ['CASE'] = args.case
if args.output_dir:
    os.environ['EXOVOLC_OUTPUT_DIR'] = args.output_dir
sys.argv = [sys.argv[0], args.batch]

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import dask

import config
import compute
import optics

if config.OPTICS_FILE is None:
    raise SystemExit("ERROR: 'optics_file' not set for this case; AOD requires it.")

exp_name    = config.get_experiment_name()
figures_dir = os.path.join(config.FIGURES_DIR, exp_name, 'lonlat')
data_dir    = os.path.join(config.DATA_DIR,    exp_name, 'lonlat')
os.makedirs(figures_dir, exist_ok=True)
os.makedirs(data_dir,    exist_ok=True)

file_list = config.get_file_list()
if not file_list:
    raise SystemExit("No files found. Check config.")

print(f"\nExperiment : {exp_name}")
print(f"Figures    : {figures_dir}")
print(f"Data       : {data_dir}")

ds, gw_values = compute.load_dataset(file_list)

with ds:
    days = compute.days_since_start(ds)

    print("Computing grid geometry...")
    geom = compute.compute_geometry(ds, gw_values)

    print("Loading VOLCHZMD and dz (full lon-lat field, no reduction)...")
    volchzmd_vals, dz_vals = dask.compute(ds['VOLCHZMD'].data, geom['dz'].data)
    lat = ds['lat'].values
    lon = ds['lon'].values

    band_optics = optics.load_band_optics(config.OPTICS_FILE)
    i_wave      = optics.select_band_550nm(band_optics['wvn_centers'])
    kext_550    = optics.interpolate_kext(band_optics, i_wave, config.VOLC_REFF)
    print(f"Band 550 nm index={i_wave}, "
          f"center={band_optics['wvn_centers'][i_wave]:.1f} cm-1, "
          f"Kext={kext_550:.4f} cm2/g  (reff={config.VOLC_REFF} um)")

    print("Computing AOD (time, lat, lon), no lon reduction...")
    aod_2d_t = optics.compute_aod(volchzmd_vals, dz_vals, kext_550)   # (time, lat, lon)

    lon_shifted = np.where(lon > 180.0, lon - 360.0, lon)
    order = np.argsort(lon_shifted)
    lon_plot = lon_shifted[order]

    for target_day in target_days:
        i_time     = int(np.argmin(np.abs(days - target_day)))
        actual_day = float(days[i_time])
        snap       = aod_2d_t[i_time][:, order]   # (lat, lon), lon reordered to -180..180

        tag  = f"day{actual_day:07.2f}"
        csv_path = os.path.join(data_dir, f"aod_{tag}.csv")
        df = pd.DataFrame(snap, index=lat, columns=lon_plot)
        df.index.name = 'lat'
        df.to_csv(csv_path)
        print(f"  Saved data   : {csv_path}  (actual day {actual_day:.2f}, "
              f"peak={np.nanmax(snap):.4f})")

        fig, ax = plt.subplots(figsize=(7, 3.2))

        # Log scale anchored at this snapshot's own peak, 4 decades of dynamic
        # range below it -- matches the LOG_SCALE_DECADES convention zonal_plots.py
        # uses for SO2/H2SO4/Q/VOLCHZMD.
        decades = 4
        vmax = max(np.nanmax(snap), 1e-12)
        vmin = vmax / 10**decades
        levels = np.logspace(np.log10(vmin), np.log10(vmax), 25)
        plot_data = np.where(snap > 0, snap, np.nan)
        cf = ax.contourf(lon_plot, lat, plot_data,
                         levels=levels, norm=mcolors.LogNorm(vmin=vmin, vmax=vmax),
                         cmap='magma_r', extend='min')
        cf.set_edgecolor('face')
        cbar = fig.colorbar(cf, ax=ax, pad=0.02)
        cbar.set_label('AOD at 550 nm')
        # Explicit one-tick-per-decade labels: the default LogNorm tick
        # locator can crowd or drop labels entirely over a narrow 4-decade
        # span, so set them by hand from the same vmin/vmax used for the norm.
        tick_decades = np.arange(np.floor(np.log10(vmin)), np.ceil(np.log10(vmax)) + 1)
        cbar.set_ticks(10.0**tick_decades)
        cbar.set_ticklabels([f"$10^{{{int(d)}}}$" for d in tick_decades])

        if args.vent_lat is not None:
            vent_lon_shifted = args.vent_lon - 360.0 if args.vent_lon > 180.0 else args.vent_lon
            ax.plot(vent_lon_shifted, args.vent_lat, marker='^', color='cyan',
                    markersize=8, markeredgecolor='black', markeredgewidth=0.8,
                    linestyle='none')

        ax.set_xlabel('Longitude (deg)')
        ax.set_ylabel('Latitude (deg)')
        ax.set_title(f'{exp_name}: AOD at 550 nm, day {actual_day:.0f}')
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)

        plt.tight_layout()
        png_path = os.path.join(figures_dir, f"aod_{tag}.png")
        plt.savefig(png_path, dpi=150)
        plt.close()
        print(f"  Saved figure : {png_path}")

print("\nDone.")
