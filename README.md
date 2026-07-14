# exovolcano_analysis_scripts

Post-processing diagnostics for CAM volcanic eruption simulations. Reads CAM `h1` NetCDF history files, computes global scalar and vertical profile time series, and produces quicklook figures. Designed for both Earth-like and exoplanet atmospheres — physical constants (gravity, gas constant, planet radius) are per-experiment rather than hard-coded.

## Requirements

- Python 3.9+
- `numpy`, `xarray`, `dask`, `matplotlib`, `pandas`, `pyyaml`, `netcdf4`
- `miepython` — only needed if using the optional Mie AOD calculation

## Running

```bash
python run_time_series.py <experiment>.yaml
```

The script looks for `<experiment>.yaml` in the `experiments/` directory. You can also pass a full path or set the `CONFIG` environment variable:

```bash
python run_time_series.py experiments/t1d_vei7.yaml
CONFIG=experiments/ben2_vei7.yaml python run_time_series.py
```

Outputs are written under `figures/<exp_name>/` and `data/<exp_name>/`.


## Running batch

Run multiple cases at once.  Cases each use multiple processors set by --nthreads, but are processed serially.  

```bash
# Named cases on the command line
python run_batch.py exp_3Tg.yaml exp_10Tg.yaml exp_30Tg.yaml --nthreads 16 --time

# From a text file
python run_batch.py --batch-file my_cases.txt --no-aod

# Mixed
python run_batch.py exp_baseline.yaml --batch-file sensitivity_runs.txt
```

'''my_cases.txt''' example format

```
#Sensitivity suite - May 2026
exp_3Tg_low.yaml
exp_3Tg_mid.yaml
exp_10Tg_low.yaml
# exp_30Tg_high.yaml   <- disabled for now
```


### Runtime flags

Any combination of these flags can be appended to the command:

| Flag | Effect |
|------|--------|
| `--time` | Print a per-section timing summary at the end |
| `--nthreads N` | Use N dask threads (default: 8) |
| `--output-dir DIR` | Write both figures and data under `DIR` (as `DIR/figures/`, `DIR/data/`) |
| `--figures-dir DIR` | Root directory for PNG output (overrides `--output-dir`) |
| `--data-dir DIR` | Root directory for CSV output (overrides `--output-dir`) |
| `--no-scalars` | Skip scalar time series (computation + CSV) |
| `--no-profiles` | Skip profile time series (computation + CSV) |
| `--no-plots` | Skip all figure output (CSV data is still written) |
| `--no-aod` | Skip AOD calculation |
| `--no-zonal` | Skip zonal mean snapshots |
| `--list-experiments` | List available YAMLs in `experiments/` and exit |

These flags override the YAML config — you do not need to comment out YAML sections to skip a step:

```bash
# Fast diagnostic pass — skip the two most expensive sections
python run_time_series.py ben2_vei7.yaml --no-zonal --no-aod --time

# Write CSVs only, no figures
python run_time_series.py ben2_vei7.yaml --no-plots

# Full run with timing on an allocated compute node
python run_time_series.py ben2_vei7.yaml --nthreads 32 --time

# See what experiments are available
python run_time_series.py --list-experiments
```

## Performance

The pipeline uses a multithreaded dask scheduler for all reductions (scalars, profiles, geometry, zonal means). Key design choices:

- All grid geometry is fully lazy — pressure, layer thickness, and altitude are built as dask arrays and only evaluated when needed.
- Scalars are batched into a single `dask.compute()` call; profiles likewise. Each group does one parallel Lustre read pass rather than one pass per variable.
- Zonal mean variables are all preloaded in a single batched `dask.compute()` call before the per-period loop.
- `pressure_1d` and `altitude_1d` (used for CSV/plot labeling) are derived from the first timestep only — not a full-dataset mean — to avoid an expensive extra scan.

Typical runtimes for a ~1000-timestep run at 96×144 grid:

| Environment | Threads | Total time |
|-------------|---------|------------|
| MacBook Pro | 8 | ~15 s |
| HPC login node (shared) | 8 | 135–340 s (variable due to contention) |
| HPC compute node (`salloc`) | 8 | ~185 s |
| HPC compute node (`salloc`) | 32 | ~50 s |

On the login node, timing variance is high because threads compete with other users. For consistent performance, claim a compute node interactively with `salloc` and pass `--nthreads` to match your allocation.

## Experiments

**All configuration — including AOD settings — lives in the experiment YAML file** passed on the command line. There is no separate config file to edit. To enable a feature, add the corresponding keys to your YAML.

A fully-annotated template covering every available field is at:

```
experiments/template.yaml
```

Copy it, rename it for your run, and fill in your values. To see all available configs:

```bash
python run_time_series.py --list-experiments
```

## Experiment YAML reference

The sections below describe every key. All optional keys have defaults and can be omitted.

### Input files (required)

```yaml
root_dir: '/path/to/cesm/archive/'
folder:   'run_name/atm/hist'        # subdirectory under root_dir
file_pattern:
  - 'run_name.cam.h1.0001-01-01-00000.nc'
  - 'run_name.cam.h1.0001-04-11-00000.nc'
  # one line per CAM h1 file to include
```

### Physical constants (required)

These must match the planet being simulated. Do not use Earth values for exoplanet runs — grid geometry, layer mass, and AOD all depend on them.

```yaml
g_const: 9.80665         # surface gravity [m/s²]  Earth: 9.80665
r_air:   287.058         # specific gas constant [J/kg/K]  Earth air: 287, pure CO2: 188.965
r_earth: 6.371e6         # mean planet radius [m]
```

### Output directories (optional)

```yaml
output_dir:  '/scratch/$USER/exovolc'   # parent of both: <output_dir>/figures/ and /data/
figures_dir: 'figures'   # PNGs go to figures/<exp_name>/
data_dir:    'data'      # CSVs go to data/<exp_name>/scalar/ and .../profiles/
```

`~` and `$VARS` are expanded, and a relative path is taken relative to the repo
rather than the working directory, so output lands in the same place regardless
of where the job was launched.

`figures_dir`/`data_dir` override `output_dir`. Any of the three can be
overridden per-run from the command line, which both entry points accept:

```bash
python run_batch.py exovolc_ben.yaml --output-dir /scratch/$USER/exovolc
```

**On an HPC system, do not leave these at their defaults.** A batch of ~20 cases
will exceed a typical `$HOME` quota. Point `output_dir` at scratch or a project
filesystem.

### Scalar time series (optional)

```yaml
scalar_vars:
  - name: SO2
    method: mass_integral     # Σ(q × air_mass_cell) [kg]
  - name: VOLCHZMD
    method: volume_integral   # Σ(ρ × cell_volume) [kg]; VOLCHZMD g/cm³→kg/m³ handled internally
  - name: TS
    method: area_mean         # Gaussian-weighted global mean [native units]
```

### Vertical profile time series (optional)

```yaml
profile_vars:
  - name: T
    method: area_mean    # always area_mean regardless of value given
```

### Zonal mean snapshots (optional)

Produces a contour plot and CSV for each variable at each requested day. The nearest available timestep is used.

```yaml
zonal_mean_vars:
  - name: T
  - name: SO2
  - name: H2SO4
  - name: VOLCHZMD

zonal_mean_periods:
  increment: [0, 1, 4, 10, 50, 100]   # days since start
```

Both sections must be present to enable zonal output. Omitting either silently skips the section. Use `--no-zonal` at runtime to skip without editing the YAML.

### AOD calculation (optional)

AOD requires VOLCHZMD in the CAM output. **All AOD settings are in the same experiment YAML.** If `optics_file` is absent or `null`, the entire AOD section is skipped with a printed warning.

```yaml
# Required to enable AOD:
optics_file: '/path/to/volc_pw1975_n68_r1.0um_mie.nc'   # pre-computed Mie optics table

# Optional tuning (defaults shown):
volc_reff:   1.0    # effective particle radius [µm] — used by Mie path only (see note below)
rho_aerosol: 1.84   # bulk aerosol density [g/cm³] — used only by Mie path

# Optional single-wavelength Mie AOD (uncomment all three to enable):
# mie_wavelength_um:         0.55   # wavelength [µm]
# mie_refractive_index_real: 1.43   # real refractive index
# mie_refractive_index_imag: 0.0    # imaginary part (positive convention)
```

The band-interpolated 550 nm AOD is always computed when `optics_file` is set. The Mie block adds a second AOD calculation at a custom wavelength and requires `miepython` to be installed.

---

## Plots produced

### Scalar time series

| Filename | Contents |
|----------|----------|
| `quicklook_sulfur_budget.png` | SO2 + H2SO4 + VOLCHZMD total masses plus their sum |
| `quicklook_TS.png` | Global mean surface temperature |
| `quicklook_TGCLDLWP.png` | Global mean total liquid water path |
| `quicklook_TMQ.png` | Global mean total precipitable water |
| `quicklook_Q_mass.png` | Global total water vapor mass |

Each plot uses a shared x-axis of days since the first time step.

### Profile Hovmoller diagrams

One `quicklook_profile_<VAR>.png` per entry in `profile_vars`. The y-axis is log-pressure in mb with the surface at the bottom. Variables in the log-scale group (SO2, H2SO4, Q, VOLCHZMD) use a `LogNorm` colormap spanning 4 orders of magnitude below the peak value. All other variables use a linear colormap clipped to the 2nd–98th percentile of the data.

### Zonal mean contour plots (requires `zonal_mean_vars` and `zonal_mean_periods`)

One `zonal/zonal_<VAR>_day<DAY>.png` per (variable, day) pair. The x-axis is latitude in degrees (full range), the y-axis is log-pressure in mb with the surface at the bottom — the same layout as the profile Hovmoller plots. Log-scale variables (SO2, H2SO4, Q, VOLCHZMD) use `LogNorm` spanning 4 decades below the peak; all others use linear scale clipped to the 2nd–98th percentile.

### AOD plots (requires `optics_file`)

| Filename | Contents |
|----------|----------|
| `aod/aod_550nm_band_timeseries.png` | Global mean AOD at 550 nm (band-interpolated Kext) |
| `aod/aod_550nm_band_zonal_hovmoller.png` | Zonal mean AOD vs time (linear latitude axis) |
| `aod/aod_<W>um_mie_timeseries.png` | Global mean AOD at `mie_wavelength_um` (Mie Kext) |
| `aod/aod_<W>um_mie_zonal_hovmoller.png` | Zonal mean AOD at `mie_wavelength_um` vs time |

The Mie pair is only produced when `mie_wavelength_um` is set in the YAML.

---

## Output structure

```
data/<exp>/
    scalar/     <var>.csv           — two columns: days, value
    profiles/   <var>.csv           — # pressure_Pa and # altitude_m comment lines,
                                      then days + per-level columns
    aod/        aod_<tag>.csv       — two columns: days, global-mean AOD
                aod_zonal_<tag>.csv — days + per-lat columns
    zonal/      <var>_day<DAY>.csv  — rows=pressure levels [mb], cols=latitudes [°]
figures/<exp>/
    quicklook_*.png
    aod/        aod_<tag>_timeseries.png
                aod_<tag>_zonal_hovmoller.png
    zonal/      zonal_<var>_day<DAY>.png
```

Zonal CSV format: first row is header `pressure_mb, lat1, lat2, ...`; each subsequent row is one pressure level. Written with `pandas.DataFrame.to_csv()`. Read with `pd.read_csv(path)`.

Profile CSVs write pressure and altitude coordinates as `# pressure_Pa:` and `# altitude_m:` comment lines before the column header. Read in pandas with `pd.read_csv(path, comment='#')`.

---

## AOD calculation details

AOD is computed from the VOLCHZMD field (aerosol mass density, g/cm³) and the layer thickness dz (m):

```
AOD_layer  = Kext [cm²/g] × ρ [g/cm³] × dz [cm]
AOD_column = Σ AOD_layer  (sum over lev)
```

### Band-interpolated Kext (default)

The optics file `volc_pw1975_n68_r1.0um_mie.nc` contains pre-computed Mie extinction efficiencies on a grid of 68 wavenumber bands × N particle radii. The 550 nm band is found by locating the band center nearest to 18182 cm⁻¹.

**Current limitation: only single-radius optics files (nbins=1) are supported.** For nbins=1, `volc_reff` is not used in the band Kext lookup — Kext is read directly from the single available bin. Supporting multi-bin files would require validating the `rbins` units in the file and testing log-log interpolation against known references.

### Single-wavelength Mie Kext (optional)

When `mie_wavelength_um` is set, `miepython` computes Kext directly:

```
m    = n_real - i × |n_imag|    (miepython sign convention)
Kext = Q_ext × 3 / (4 × r_eff_cm × ρ_bulk)   [cm²/g]
```

This is useful for wavelengths outside the optics table or for sensitivity tests with different refractive indices.

---

## Code structure

```
run_time_series.py   Orchestrator: arg parsing, calls compute/optics, saves outputs
config.py            YAML loader; exposes all experiment parameters as module constants
compute.py           Pure computation: grid geometry, mass integrals, area means, zonal means
optics.py            Pure computation: optics table I/O, Kext lookup, Mie, AOD
aod_plots.py         AOD-specific plot functions (timeseries, zonal Hovmoller)
zonal_plots.py       Zonal mean contour plot function; defines LOG_SCALE_DECADES
experiments/         One YAML per model run
data/                CSV output (scalar/, profiles/, aod/, zonal/ subdirectories per experiment)
figures/             PNG output (one subdirectory per experiment, with aod/ and zonal/ sub-dirs)
```

`compute.py` and `optics.py` contain no plotting or file I/O (except `optics.load_band_optics`). All grid geometry is computed in `compute.compute_geometry()` as lazy dask-backed DataArrays and passed downstream as a plain dict. Reductions over multiple variables are batched into single `dask.compute()` calls so the scheduler can parallelize across chunks in one pass.
