#!/usr/bin/env python

"""
plot_lonlat_aod_from_csv.py - Replot lonlat_aod.py's CSV output locally.

lonlat_aod.py must run on the HPC node with the raw CAM archive; this script
re-renders its already-fetched CSVs (data/<case>/lonlat/aod_day<D>.csv)
without needing config.py/compute.py/optics.py or any NetCDF access, so
plotting tweaks (color scale, ticks, styling) can be iterated on locally.
Mirrors lonlat_aod.py's plotting block exactly -- keep the two in sync.

Usage:
    python plot_lonlat_aod_from_csv.py --case-dir /path/to/exovolc_hunga_fid \
        --vent-lat -20.0 --vent-lon 185.0
"""

import os
import sys
import glob
import argparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

parser = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--case-dir', required=True, metavar='DIR',
                     help='Case directory containing data/lonlat/aod_day*.csv '
                          '(figures/lonlat/ is created as a sibling of data/)')
parser.add_argument('--vent-lat', type=float, default=None,
                     help='Vent latitude for an optional marker on the map')
parser.add_argument('--vent-lon', type=float, default=None,
                     help='Vent longitude (0-360 convention) for an optional marker')
args = parser.parse_args()

if (args.vent_lat is None) != (args.vent_lon is None):
    parser.error('--vent-lat and --vent-lon must be given together')

case_dir    = os.path.abspath(args.case_dir)
case_name   = os.path.basename(case_dir)
data_dir    = os.path.join(case_dir, 'data', 'lonlat')
figures_dir = os.path.join(case_dir, 'figures', 'lonlat')
os.makedirs(figures_dir, exist_ok=True)

csv_files = sorted(glob.glob(os.path.join(data_dir, 'aod_day*.csv')))
if not csv_files:
    raise SystemExit(f"No CSVs found in {data_dir}")

for csv_path in csv_files:
    tag = os.path.splitext(os.path.basename(csv_path))[0].replace('aod_', '')
    actual_day = float(tag.replace('day', ''))

    df = pd.read_csv(csv_path, index_col=0)
    lat = df.index.values.astype(float)
    lon_plot = df.columns.values.astype(float)
    snap = df.values

    fig, ax = plt.subplots(figsize=(7, 3.2))

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
    ax.set_title(f'{case_name}: AOD at 550 nm, day {actual_day:.0f}')
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)

    plt.tight_layout()
    png_path = os.path.join(figures_dir, f"aod_{tag}.png")
    plt.savefig(png_path, dpi=150)
    plt.close()
    print(f"  Saved figure : {png_path}  (peak={np.nanmax(snap):.4f})")

print("\nDone.")
