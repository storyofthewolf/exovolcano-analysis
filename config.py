"""
config.py - Batch configuration loader for exovolcano analysis.

A batch YAML describes one planet (the geophysical constants and the diagnostic
variable lists) and the ~20 eruption cases run on it.  Constants that are a
property of the planet are written once, at batch level, so they cannot drift
between cases.  Per-case keys override the batch-level value of the same name.

    experiments/exovolc_ben1.yaml
        root_dir:  '/gpfsm/.../archive/'
        g_const:   9.121824
        r_air:     188.965172522727
        r_earth:   5797410.0
        optics_file: '...r1.0um_mie.nc'    # batch default for the per-case key
        volc_reff:   1.0
        scalar_vars:  [...]
        profile_vars: [...]
        cases:
          - name: exovolc_ben1_h10s9       # inherits the optics above
          - name: exovolc_ben1_h11s10
            volc_reff: 0.5                 # ...or overrides it

For each case, 'folder' and 'file_pattern' are derived from the case name:

    folder       = '<case>/atm/hist'          (override with folder_template)
    file_pattern = '<case>.cam.h1.*.nc'       (override with file_template)

The case is selected by the CASE environment variable, which run_batch.py sets
per subprocess and run_time_series.py sets from its --case flag.  With no CASE
set, a single-case batch runs that case; a multi-case batch errors and lists
the available names.

Usage:
    python run_time_series.py exovolc_ben1.yaml --case exovolc_ben1_h11s10
    python run_batch.py exovolc_ben1.yaml        # every case in the batch
"""

import os
import sys
import glob
import yaml


# ---------------------------------------------------------------------------
# Config file resolution
# ---------------------------------------------------------------------------

EXPERIMENTS_DIR = 'experiments'

# Keys a case may set for itself.  Everything else in the YAML is batch-wide.
# optics_file/volc_reff are here because the optics table and effective radius
# are varied within a batch, not across it.
CASE_KEYS = ('optics_file', 'volc_reff',
             'mie_wavelength_um', 'mie_refractive_index_real',
             'mie_refractive_index_imag',
             'folder', 'file_pattern')

DEFAULT_FOLDER_TEMPLATE = '{case}/atm/hist'
DEFAULT_FILE_TEMPLATE   = '{case}.cam.h1.*.nc'


def _find_config_file():
    """Resolve the batch YAML path from CLI arg, env var, or default."""
    if len(sys.argv) > 1 and sys.argv[1].endswith('.yaml'):
        name = sys.argv[1]
        if os.path.exists(name):
            return name
        return os.path.join(EXPERIMENTS_DIR, name)
    if 'CONFIG' in os.environ:
        return os.environ['CONFIG']
    return os.path.join(EXPERIMENTS_DIR, 'experiment.yaml')


def _load_yaml(path):
    if not os.path.exists(path):
        sys.exit(f"ERROR: Config file not found: '{path}'")
    with open(path) as f:
        return yaml.safe_load(f)


def _parse_cases(cfg, path):
    """Return the batch's case list as dicts, validating names.

    Accepts either a bare string or a mapping with a 'name' key per entry.
    """
    raw = cfg.get('cases')
    if not raw:
        sys.exit(
            f"ERROR: '{path}' has no 'cases:' section.\n"
            f"       Batch YAMLs list their eruption cases under 'cases:'.\n"
            f"       See experiments/template.yaml."
        )

    cases = []
    for i, entry in enumerate(raw):
        if isinstance(entry, str):
            case = {'name': entry}
        elif isinstance(entry, dict):
            case = dict(entry)
        else:
            sys.exit(f"ERROR: cases[{i}] in '{path}' must be a name or a mapping.")

        if not case.get('name'):
            sys.exit(f"ERROR: cases[{i}] in '{path}' has no 'name'.")

        unknown = set(case) - set(CASE_KEYS) - {'name'}
        if unknown:
            sys.exit(
                f"ERROR: case '{case['name']}' sets batch-level key(s): "
                f"{', '.join(sorted(unknown))}.\n"
                f"       Per-case keys are: {', '.join(CASE_KEYS)}.\n"
                f"       Everything else belongs at batch level, so it stays "
                f"consistent across the batch."
            )
        cases.append(case)

    # A repeated name would have both cases write to data/<name>/, silently
    # overwriting. Fail loudly instead.
    seen = {}
    for case in cases:
        if case['name'] in seen:
            sys.exit(f"ERROR: duplicate case name '{case['name']}' in '{path}'. "
                     f"Case names must be unique — they are the output directory.")
        seen[case['name']] = True

    return cases


def _select_case(cases, path):
    """Pick the active case from $CASE, or the only one if the batch has one."""
    wanted = os.environ.get('CASE')

    if wanted:
        for case in cases:
            if case['name'] == wanted:
                return case
        names = '\n'.join(f"    {c['name']}" for c in cases)
        sys.exit(f"ERROR: case '{wanted}' not found in '{path}'. Available:\n{names}")

    if len(cases) == 1:
        return cases[0]

    names = '\n'.join(f"    {c['name']}" for c in cases)
    sys.exit(
        f"ERROR: '{path}' defines {len(cases)} cases; select one with --case, "
        f"or run them all with:\n"
        f"    python run_batch.py {os.path.basename(path)}\n"
        f"Available cases:\n{names}"
    )


def _resolve(cfg, case):
    """Merge the active case over the batch defaults and derive paths."""
    merged = dict(cfg)
    merged.pop('cases', None)
    for key in CASE_KEYS:
        if key in case:
            merged[key] = case[key]

    name = case['name']
    folder_template = cfg.get('folder_template', DEFAULT_FOLDER_TEMPLATE)
    file_template   = cfg.get('file_template',   DEFAULT_FILE_TEMPLATE)

    merged.setdefault('folder',       folder_template.format(case=name))
    merged.setdefault('file_pattern', file_template.format(case=name))
    if isinstance(merged['file_pattern'], str):
        merged['file_pattern'] = [merged['file_pattern']]

    merged['case_name'] = name
    return merged


_config_path = _find_config_file()
_batch = _load_yaml(_config_path)
CASES  = _parse_cases(_batch, _config_path)
_case  = _select_case(CASES, _config_path)
_cfg   = _resolve(_batch, _case)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

CASE_NAME    = _cfg['case_name']
ROOT_DIR     = _cfg['root_dir']
FOLDER       = _cfg['folder']
FILE_PATTERN = _cfg['file_pattern']
G_CONST      = float(_cfg['g_const'])
R_AIR        = float(_cfg['r_air'])
R_EARTH      = float(_cfg['r_earth'])
FIGURES_DIR  = _cfg.get('figures_dir', 'figures')
DATA_DIR     = _cfg.get('data_dir', 'data')

# Variable lists: each entry is a dict with keys 'name' and 'method'
SCALAR_VARS   = _cfg.get('scalar_vars', [])
PROFILE_VARS  = _cfg.get('profile_vars', [])
ZONAL_VARS    = _cfg.get('zonal_mean_vars', [])
ZONAL_PERIODS = _cfg.get('zonal_mean_periods', {}).get('increment', [])

# Aerosol optics — optics_file and volc_reff are per-case (see CASE_KEYS)
OPTICS_FILE = _cfg.get('optics_file', None)
VOLC_REFF   = float(_cfg.get('volc_reff',   1.0))
RHO_AEROSOL = float(_cfg.get('rho_aerosol', 1.84))
MIE_WAVE_UM = _cfg.get('mie_wavelength_um', None)
MIE_N_REAL  = float(_cfg.get('mie_refractive_index_real', 1.43))
MIE_N_IMAG  = float(_cfg.get('mie_refractive_index_imag', 0.0))

# Backwards-compatible alias
OUTPUT_DIR = FIGURES_DIR


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

def get_batch_name():
    """Returns the batch YAML filename stem, e.g. 'exovolc_ben1'."""
    return os.path.splitext(os.path.basename(_config_path))[0]


def get_case_names(path=None):
    """Returns the list of case names in a batch YAML (default: the active one).

    Used by run_batch.py to enumerate a batch without importing it as config.
    """
    if path is None:
        return [c['name'] for c in CASES]
    return [c['name'] for c in _parse_cases(_load_yaml(path), path)]


def get_file_list():
    """Discovers and returns a sorted list of files based on configuration."""
    file_list = []
    for pattern in FILE_PATTERN:
        full_path = os.path.join(ROOT_DIR, FOLDER, pattern)
        expanded = os.path.expanduser(full_path)
        print(f"Searching: {expanded}")
        file_list.extend(glob.glob(expanded))

    file_list = sorted(set(file_list))

    if not file_list:
        print("\n" + "!" * 50)
        print("ERROR: No NetCDF files found!")
        print(f"  case:         {CASE_NAME}")
        print(f"  root_dir:     {ROOT_DIR}")
        print(f"  folder:       {FOLDER}")
        print(f"  file_pattern: {FILE_PATTERN}")
        print("!" * 50 + "\n")

    return file_list


def get_experiment_name():
    """Returns the active case name — the output directory under data/ and figures/.

    e.g. batch 'exovolc_ben1.yaml', case 'exovolc_ben1_h11s10'
         -> data/exovolc_ben1_h11s10/
    """
    print(f"Batch: {get_batch_name()}   Case: {CASE_NAME}")
    return CASE_NAME
