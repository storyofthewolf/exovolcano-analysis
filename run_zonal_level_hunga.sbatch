#!/bin/bash
#SBATCH --job-name=exovolc_zonlev
#SBATCH --account=s2427
#SBATCH --time=04:00:00
#SBATCH --mem=480gb
#SBATCH -N 1
#SBATCH --constraint=mil
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=126
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.out

# Zonal-mean latitude-time fields at fixed altitude, for the Schoeberl et al.
# (2024, 10.1029/2024JD041296) Figure 3 comparison:
#   part a  aerosol extinction coefficient at 20 km  -> VOLCHZMD at 20 km
#   part b  MLS water vapor at 25 km                 -> Q at 25 km
#
# The main pipeline's zonal section writes one CSV per (variable, day) at a
# few snapshot days, which cannot produce a multi-year Hovmoller. This runs
# zonal_level_timeseries.py instead, which writes the whole time series at one
# level as a single CSV.
#
# Cases: the manuscript fiducial plus the case it superseded, so the figure can
# show both, and the dry control for differencing the water field.

set -u

source /usr/share/lmod/lmod/init/bash
module load python/GEOSpyD/25.3.1-0/3.13

REPO=/gpfsm/dhome/etwolf/pythonWorkspace/exovolcano-analysis
REMOTE_BASE=/gpfsm/dnb07/projects/p54/users/etwolf/exovolc

cd "$REPO" || { echo "ERROR: cannot cd to REPO=$REPO"; exit 1; }

python -c 'import xarray, dask, netCDF4, numpy, pandas, yaml' || {
    echo "ERROR: python environment is missing a required package."; exit 1; }

echo "host:    $(hostname)"
echo "started: $(date)"
echo

# case:batch pairs. The fiducial and dry control live in different suites.
run_one () {
    local case="$1" batch="$2" var="$3" alt="$4"
    echo "### $case  $var @ ${alt}km"
    python zonal_level_timeseries.py \
        --batch "$batch" \
        --case "$case" \
        --var "$var" \
        --altitude-km "$alt" \
        --output-dir "$REMOTE_BASE/$(basename "$batch" .yaml | sed 's/^exovolc_//')"
}

status=0
# Manuscript fiducial (phase 2)
run_one exovolc_hunga_r0.4_so2_1.0tg exovolc_hunga_phase2.yaml Q        25 || status=$?
run_one exovolc_hunga_r0.4_so2_1.0tg exovolc_hunga_phase2.yaml VOLCHZMD 20 || status=$?
# Superseded fiducial and the dry control (phase 1)
run_one exovolc_hunga_fid            exovolc_hunga.yaml        Q        25 || status=$?
run_one exovolc_hunga_fid            exovolc_hunga.yaml        VOLCHZMD 20 || status=$?
run_one exovolc_hunga_h2o_none       exovolc_hunga.yaml        Q        25 || status=$?

echo
echo "finished: $(date)  (exit $status)"
exit $status
