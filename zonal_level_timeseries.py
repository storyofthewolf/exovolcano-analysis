#!/usr/bin/env python

"""
zonal_level_timeseries.py - Zonal-mean field at a fixed altitude, as a full
latitude-time series.

Standalone, one-off script in the same spirit as lonlat_aod.py: NOT part of
the run_time_series.py/run_batch.py pipeline. It exists because the pipeline's
zonal section writes one CSV per (variable, day) at a handful of snapshot
days, which is the wrong shape for a latitude-time Hovmoller spanning years.
Here the lon-mean (time, lev, lat) field is sliced at ONE level and written as
a single (time x lat) CSV.

Motivating comparison: Schoeberl et al. (2024, JGR, 10.1029/2024JD041296)
Figure 3 plots zonal-mean constituent fields on exactly this basis -- part a
aerosol extinction at 20 km, part b MLS water vapor at 25 km -- as latitude
versus time through 2022/23. Matching that panel needs a daily series at a
fixed altitude, which is what this produces.

Usage (run where the raw CAM archive lives; the local remote_analysis/ tree
holds only already-reduced CSVs):

    python zonal_level_timeseries.py --batch exovolc_hunga_phase2.yaml \
        --case exovolc_hunga_r0.4_so2_1.0tg --var Q --altitude-km 25

--altitude-km selects the model level whose day-0 mean altitude is nearest
the requested height; the level actually used, and its altitude, are printed
and written into the CSV header so the choice is auditable.

Output:
    data/<case>/zonal_level/<VAR>_<ALT>km.csv
        header comments carry the level index, its day-0 altitude and
        pressure, then a days_since_start + one-column-per-latitude table.
"""

import os
import sys
import argparse

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--batch', required=True, metavar='batch.yaml',
                    help='Batch YAML (looked up in experiments/, or a full path)')
parser.add_argument('--case', required=True, metavar='NAME',
                    help='Case name within the batch')
parser.add_argument('--var', required=True, metavar='VAR',
                    help='Variable name, e.g. Q')
parser.add_argument('--altitude-km', type=float, required=True,
                    help='Target altitude in km; nearest model level is used')
parser.add_argument('--output-dir', default=None,
                    help='Parent for data/ (default: repo data/)')
args = parser.parse_args()

os.environ['CASE'] = args.case
if args.output_dir:
    os.environ['EXOVOLC_OUTPUT_DIR'] = args.output_dir
sys.argv = [sys.argv[0], args.batch]

import numpy as np
import pandas as pd
import dask

import config
import compute

exp_name = config.get_experiment_name()
data_dir = os.path.join(config.DATA_DIR, exp_name, 'zonal_level')
os.makedirs(data_dir, exist_ok=True)

file_list = config.get_file_list()
if not file_list:
    raise SystemExit("No files found. Check config.")

print(f"\nExperiment : {exp_name}")
print(f"Variable   : {args.var}")
print(f"Data       : {data_dir}")

ds, gw_values = compute.load_dataset(file_list)

with ds:
    days = compute.days_since_start(ds)
    geom = compute.compute_geometry(ds, gw_values)

    # Day-0 mean altitude profile picks the level; z_mid is (time, lev, lat, lon).
    z0 = geom['z_mid'].isel(time=0).mean(dim=('lat', 'lon'))
    z0_km = np.asarray(dask.compute(z0.data)[0]) / 1000.0
    ilev = int(np.argmin(np.abs(z0_km - args.altitude_km)))
    print(f"Requested {args.altitude_km} km -> level {ilev} "
          f"at {z0_km[ilev]:.2f} km (day-0 global mean)")

    print("Computing lon-mean and slicing the level...")
    zonal = compute.preload_zonal_mean(ds, args.var)      # lazy (time, lev, lat)
    slab = dask.compute(zonal.isel(lev=ilev).data)[0]     # (time, lat)

    lat = ds['lat'].values
    pres_pa = float(np.asarray(dask.compute(
        geom['mid_p'].isel(time=0, lev=ilev).mean(dim=('lat', 'lon')).data)[0]))

    units = ds[args.var].attrs.get('units', 'unknown')

out = os.path.join(data_dir, f"{args.var}_{args.altitude_km:g}km.csv")
df = pd.DataFrame(slab, index=days, columns=[f"{v:.4f}" for v in lat])
df.index.name = 'days_since_start'
with open(out, 'w') as f:
    f.write(f"# variable: {args.var}\n")
    f.write(f"# units: {units}\n")
    f.write(f"# requested_altitude_km: {args.altitude_km}\n")
    f.write(f"# level_index: {ilev}\n")
    f.write(f"# level_altitude_km: {z0_km[ilev]:.4f}\n")
    f.write(f"# level_pressure_Pa: {pres_pa:.4f}\n")
    df.to_csv(f)

print(f"  Saved {out}  ({df.shape[0]} times x {df.shape[1]} lats), "
      f"peak={np.nanmax(slab):.4g} {units}")
print("\nDone.")
