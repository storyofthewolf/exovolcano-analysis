# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Analysis

```bash
# Run with a named experiment (looks in experiments/ directory)
python run_time_series.py ben2_vei7.yaml

# Run with an explicit path
python run_time_series.py experiments/hab2_vei7.yaml

# Run via environment variable
CONFIG=experiments/t1d_vei7.yaml python run_time_series.py

# List available experiment YAMLs
python run_time_series.py --list-experiments

# Print usage / key reference
python run_time_series.py --help
```

Outputs go to `figures/<exp_name>/` and `data/<exp_name>/` with subdirectories `scalar/`, `profiles/`, `aod/`, and `zonal/`. All directories are auto-created.

The experiment name is derived from the YAML filename stem (e.g. `experiments/ben2_vei7.yaml` → `ben2_vei7`), not from the `file_pattern` prefix.

### Runtime flags

All flags are parsed by argparse before `config.py` is imported. After parsing, `sys.argv` is rewritten to contain only the YAML argument so `config.py` sees a clean argv.

| Flag | Effect |
|------|--------|
| `--time` | Print a per-section timing summary at the end |
| `--nthreads N` | Use N dask threads (default: 8) |
| `--output-dir DIR` | Write figures and data under `DIR` (`DIR/figures/`, `DIR/data/`) |
| `--figures-dir DIR` | Root directory for PNG output (overrides `--output-dir`) |
| `--data-dir DIR` | Root directory for CSV output (overrides `--output-dir`) |
| `--no-scalars` | Skip scalar time series |
| `--no-profiles` | Skip profile time series |
| `--no-plots` | Skip all figure output (CSVs still written) |
| `--no-aod` | Skip AOD calculation |
| `--no-zonal` | Skip zonal mean snapshots |
| `--list-experiments` | List YAMLs in `experiments/` and exit |

```bash
# Typical fast cluster run
python run_time_series.py ben2_vei7.yaml --nthreads 32 --no-zonal --time
```

## Architecture

The pipeline has six modules:

**`config.py`** — Loads `experiments/<name>.yaml` at import time (via CLI arg, `CONFIG` env var, or default). Stores the resolved path as `_config_path`. `_resolve_output_dirs()` resolves `FIGURES_DIR`/`DATA_DIR` to **absolute** paths, highest precedence first: `EXOVOLC_FIGURES_DIR`/`EXOVOLC_DATA_DIR` env → `EXOVOLC_OUTPUT_DIR` env → YAML `figures_dir`/`data_dir` → YAML `output_dir` (parent of both) → `figures`/`data`. The env vars are set by `run_time_series.py` from `--figures-dir`/`--data-dir`/`--output-dir` **before** `import config`. `~` and `$VARS` are expanded; a relative path anchors to `REPO_DIR`, not the CWD, so output does not follow the launch directory. Exposes path constants (`ROOT_DIR`, `FIGURES_DIR`, `DATA_DIR`), physical constants (`G_CONST`, `R_AIR`, `R_EARTH`), variable lists (`SCALAR_VARS`, `PROFILE_VARS`, `ZONAL_VARS`, `ZONAL_PERIODS`), and AOD parameters (`OPTICS_FILE`, `VOLC_REFF`, `RHO_AEROSOL`, `MIE_WAVE_UM`, `MIE_N_REAL`, `MIE_N_IMAG`). `get_experiment_name()` derives the name from the YAML filename stem via `_config_path`.

**`compute.py`** — Pure computation engine; no I/O or side effects. Reads CAM NetCDF output via xarray/dask, builds grid geometry from hybrid pressure coordinates, and computes global diagnostics. Key functions:
- `load_dataset()` — opens multi-file CAM NetCDF as a lazy dask-backed xarray Dataset (`chunks={'time': 200}`); extracts `gw` (Gaussian weights) from the first file separately to avoid mfdataset inflation
- `compute_geometry()` — builds pressure, layer thickness (dp), altitude (z_mid), cell area, air mass, and cell volume as **lazy dask-backed DataArrays** using explicit dask broadcasting (not xarray) to avoid coordinate inflation bugs with mfdataset. `PS` and `T` are kept as dask arrays — no eager `.values` load. The cumsum for `z_mid` uses `dask.array.cumsum`. First-timestep diagnostics are batched into a single `da.compute(PS_da[0], dp_pa_da[0], z_mid_da[0])` call.
- `compute_scalar()` — returns a **lazy** DataArray (no `.load()`); caller batches with `dask.compute()`
- `compute_profile()` — returns a **lazy** DataArray (no `.load()`); caller batches with `dask.compute()`
- `preload_zonal_mean(ds, name)` — returns a lazy lon-mean DataArray; callers should batch multiple variables with `dask.compute()` before accessing `.values`
- `compute_zonal_mean(days, target_day, zonal_np)` — slices a pre-loaded `(time, lev, lat)` numpy array; no I/O

**`optics.py`** — Pure computation engine for aerosol optics; no plotting or I/O except `load_band_optics`. Key functions:
- `load_band_optics(filepath)` — opens `volc_pw1975_n68_r1.0um_mie.nc`; `rbins` are stored in cm and returned as-is (no unit conversion). **Only nbins=1 is currently supported** — for single-bin files, the radius value is not used in the Kext lookup.
- `select_band_550nm(wvn_centers)` — finds band index nearest to 18182 cm⁻¹
- `interpolate_kext(optics, i_wave, reff_um)` — for nbins=1, returns `kext[0]` directly; `reff_um` is ignored. Multi-bin log-log interpolation is implemented but unvalidated.
- `mie_kext(wavelength_um, reff_um, ...)` — calls `miepython.efficiencies(m, diameter_um, wavelength_um)`; note this version of miepython uses diameter + wavelength in the same units, not the old size-parameter `mie(m, x)` API
- `compute_aod(volchzmd_vals, dz_m_vals, kext_cgs)` — pure numpy; multiplies dz by 100 for m→cm, sums over lev, returns `(time, lat, lon)`

**`aod_plots.py`** — AOD-specific plot functions. Callers pass the `aod/` subdirectory (`figures/<exp_name>/aod/`) so AOD figures are kept separate from top-level quicklook plots.

**`zonal_plots.py`** — Zonal mean contour plot function. Also defines `LOG_SCALE_DECADES` — the single authoritative dict of which variables use `LogNorm` and how many decades to span. `run_time_series.py` imports `LOG_SCALE_DECADES` from here for use in the Hovmoller plots too. Key function:
- `plot_zonal_mean(lat, pressure_1d, data_2d, name, units, actual_day, figures_dir, filename, log_scale)` — contour plot with log-pressure y-axis (surface at bottom), latitude x-axis, same colormap logic as Hovmoller plots

**`run_time_series.py`** — Orchestrator. Uses argparse to parse all flags, rewrites `sys.argv` to just the YAML arg, then imports config → compute → optics → saves CSVs → makes quicklook plots. Key behaviors:
- All flags parsed by argparse before any other imports; `sys.argv` is rewritten to `[argv[0], yaml_path]` before `import config`
- Uses a **threaded dask scheduler** (`dask.config.set(scheduler='threads', num_workers=N)`); default 8 threads, overridden by `--nthreads N`
- Scalars are collected as lazy DataArrays then materialized in a **single `dask.compute()` call** — one parallel pass over all scalar variables
- Profiles are collected as lazy DataArrays then materialized in a **separate single `dask.compute()` call** — do not combine scalars and profiles into one call, as the combined graph is too large for the threaded scheduler
- Zonal variables are all preloaded in a **single batched `dask.compute()` call** before the per-period loop
- `pressure_1d` and `altitude_1d` are derived from `isel(time=0)` — first timestep only, not a full-dataset mean
- Imports `LOG_SCALE_DECADES` from `zonal_plots` — do not define it in both places
- Runtime summary box auto-sizes column widths to the longest label name

## Performance notes

- `compute_scalar()` and `compute_profile()` return **lazy** DataArrays. Do not call `.load()` inside those functions — the orchestrator batches them with `dask.compute()`.
- `preload_zonal_mean()` returns a **lazy** DataArray. Always batch multiple variables with `dask.compute()` before looping over periods.
- The geometry arrays (`dp_pa`, `mid_p`, `dz`, `z_mid`, `air_mass_cell`, `cell_volume`) are dask-backed. Passing them into xarray reductions keeps the full graph lazy until `dask.compute()` is called.
- Do NOT combine scalars and profiles into a single `dask.compute()` call — the combined graph causes hangs with the threaded scheduler. Keep them as separate passes.
- `pressure_1d`/`altitude_1d` use `isel(time=0)` — this avoids a full-dataset scan just to produce axis labels.
- On an HPC cluster, use `--nthreads 32` (or your core allocation) on a dedicated compute node (`salloc`). On a shared login node keep threads at 4–8 to avoid contention with other users. Login node timing is highly variable due to Lustre contention — not fixable in code.
- **On an HPC cluster, always redirect output off `$HOME`** — `--output-dir /scratch/$USER/...`, or `output_dir:` in the batch YAML. A batch of ~20 cases writes enough figures and CSVs to exceed a typical `$HOME` quota, which fails the run partway through. The default (`figures/`, `data/` in the repo) is for local development only.

## Experiment YAML Schema

A fully-annotated template is at `experiments/template.yaml`. Key fields:

```yaml
root_dir: '/path/to/runs/'      # base directory for NetCDF input files
folder: 'exp_name'              # subdirectory under root_dir
file_pattern:                   # list of NetCDF filenames (CAM h1 history)
  - 'exp_name.cam.h1.0001-01-01-00000.nc'

g_const:  9.121824              # planet-specific gravity [m/s^2]
r_air:    188.965172522727      # gas constant for atmosphere [J/kg/K]
r_earth:  5797410.0             # planet radius [m]

# Output — omit for the repo-local defaults (figures/, data/). On HPC, set
# output_dir to scratch: it is the parent of both, giving <output_dir>/figures/
# and <output_dir>/data/. figures_dir/data_dir override it independently.
# ~ and $VARS expand; relative paths anchor to the repo, not the CWD.
output_dir: '/scratch/$USER/exovolc'

scalar_vars:                    # global scalar time series to compute
  - name: SO2
    method: mass_integral       # or volume_integral or area_mean

profile_vars:                   # vertical profile (time, lev) to compute
  - name: T
    method: area_mean

zonal_mean_vars:                # zonal mean snapshots at selected days
  - name: T
  - name: SO2

zonal_mean_periods:             # both sections required to enable zonal output
  increment: [0, 1, 4, 10, 50, 100]   # days since start

# AOD — omit optics_file (or set to null) to skip the entire AOD section
optics_file: '/path/to/volc_pw1975_n68_r1.0um_mie.nc'
volc_reff:   1.0                # effective particle radius [µm] (used by Mie path only)
rho_aerosol: 1.84               # bulk aerosol density [g/cm³]
# mie_wavelength_um:         0.55   # optional; requires miepython
# mie_refractive_index_real: 1.43
# mie_refractive_index_imag: 0.0
```

## Output Structure

```
data/<exp>/
    scalar/     <var>.csv                    — two columns: days, value
    profiles/   <var>.csv                    — # pressure_Pa and # altitude_m comment lines,
                                               then days + per-level columns
    aod/        aod_<tag>.csv               — two columns: days, global-mean AOD
                aod_zonal_<tag>.csv         — days + per-lat columns
    zonal/      <var>_day<DAY>.csv          — rows=pressure levels [mb],
                                               cols=latitudes [degrees]
figures/<exp>/
    quicklook_*.png                          — scalar and profile plots
    aod/        aod_<tag>_timeseries.png
                aod_<tag>_zonal_hovmoller.png
    zonal/      zonal_<var>_day<DAY>.png    — one contour plot per (var, day)
```

Zonal CSV format: first row is header `pressure_mb, lat1, lat2, ...`; each subsequent row is one pressure level. Written with `pandas.DataFrame.to_csv()`. Read with `pd.read_csv(path)`.

Profile CSVs write pressure and altitude coordinates as `# pressure_Pa:` and `# altitude_m:` comment lines before the column header. Read in pandas with `pd.read_csv(path, comment='#')`.

## Key Domain Details

- **Physical constants are planet-specific**, not Earth-standard. Each experiment encodes its planet's gravity and radius (e.g., `g_const = 9.80665 * 0.93`). Do not substitute standard Earth values.
- **VOLCHZMD** is sulfate aerosol mass density (g/cm³); `volume_integral` multiplies by 1000 to convert to kg/m³ before integrating. AOD uses it directly in g/cm³ with a CGS Kext.
- **Gaussian weights (`gw`)**: CAM uses a Gaussian latitude grid. `gw` values sum to 2.0 and are used directly with xarray `.weighted()` for exact area-weighted means — no cosine-latitude approximation.
- **Hybrid pressure coordinates**: Pressure is computed from `hyam`, `hybm`, `hyai`, `hybi`, and `PS` using explicit **dask array** broadcasting (not xarray), to avoid a known mfdataset coordinate inflation bug. `PS` and `T` are never loaded eagerly — they remain dask arrays throughout `compute_geometry()`.
- **Lazy geometry**: All 4D geometry fields returned by `compute_geometry()` are dask-backed DataArrays. Downstream reductions in `compute_scalar()` and `compute_profile()` are also lazy; the orchestrator triggers computation via batched `dask.compute()` calls.
- **Profile Hovmoller plots and zonal mean plots**: log-pressure y-axis, surface at bottom. Variables in `LOG_SCALE_DECADES` (SO2, H2SO4, Q, VOLCHZMD) use `LogNorm` colormaps anchored at the data peak; others use linear with 2nd–98th percentile clipping. `LOG_SCALE_DECADES` is defined in `zonal_plots.py` and imported by `run_time_series.py` — do not define it in both places.
- **Experiment name** is the YAML filename stem (`_config_path` in `config.py`), not the `file_pattern` prefix. `get_experiment_name()` uses `os.path.splitext(os.path.basename(_config_path))[0]`.
- **nbins=1 only**: `volc_pw1975_n68_r1.0um_mie.nc` has a single radius bin. `load_band_optics` returns `rbins` in cm as stored. `interpolate_kext` returns `kext[0]` directly for nbins=1; `reff_um` is unused. Multi-bin interpolation would require validating rbins units and testing.
- **miepython API**: The installed version uses `miepython.efficiencies(m, diameter, wavelength)` with both lengths in the same units. The old `miepython.mie(m, x)` size-parameter API does not exist in this version.
