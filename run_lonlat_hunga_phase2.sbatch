#!/bin/bash
#SBATCH --job-name=exovolc_lonlat
#SBATCH --account=s2427
#SBATCH --qos=long
#SBATCH --time=04:00:00
#SBATCH --mem=480gb
#SBATCH -N 1
#SBATCH --constraint=mil
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=126
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.out

# Lon-lat (plume-tracked) AOD snapshots for the Hunga phase-2 suite.
#
#   sbatch run_lonlat_hunga_phase2.sbatch
#
# lonlat_aod.py keeps the full (time, lat, lon) AOD field in memory rather
# than reducing to a zonal or global mean, because the Hunga Tonga literature
# reports plume-local AOD far more often than global-mean. See the header of
# lonlat_aod.py and memory hunga-aod-comparison-basis.
#
# DAYS matches the phase-1 fid / sellitto_fid snapshots (1,4,10,30,107) so the
# two phases are directly comparable case-for-case. Do not change it without
# regenerating phase 1 to match.
#
# Output goes to scratch under the same <remote_base>/<batch> layout the main
# pipeline uses, so fetch_exovolc.py picks it up with no extra configuration.

set -u

source /usr/share/lmod/lmod/init/bash
module load python/GEOSpyD/25.3.1-0/3.13

REPO=/gpfsm/dhome/etwolf/pythonWorkspace/exovolcano-analysis
REMOTE_BASE=/gpfsm/dnb07/projects/p54/users/etwolf/exovolc
BATCH_YAML=exovolc_hunga_phase2.yaml
BATCH_NAME=hunga_phase2

DAYS=${DAYS:-1,4,10,30,107}

# Hunga vent, matching hungatonga_phase2.yaml (volc_lat/volc_lon).
VENT_LAT=-20.0
VENT_LON=185.0

CASES=(
    exovolc_hunga_sellitto_1.5tg
    exovolc_hunga_sellitto_2.0tg
    exovolc_hunga_p50
    exovolc_hunga_p70
    exovolc_hunga_k8d
    exovolc_hunga_r0.4
    exovolc_hunga_r0.4_so2_1.0tg
    exovolc_hunga_raikoke_equiv
)
if [ "$#" -gt 0 ]; then
    CASES=("$@")
fi

cd "$REPO" || { echo "ERROR: cannot cd to REPO=$REPO"; exit 1; }

python -c 'import xarray, dask, netCDF4, numpy, pandas, matplotlib, yaml' || {
    echo "ERROR: python environment is missing a required package."; exit 1; }

echo "host:    $(hostname)"
echo "started: $(date)"
echo "days:    $DAYS"
echo "output:  $REMOTE_BASE/$BATCH_NAME"
echo "cases:   ${#CASES[@]}"
echo

# One case at a time: each holds a full (time, lat, lon) AOD field in memory,
# which is exactly the reduction the rest of the pipeline avoids. Running the
# whole suite concurrently is what would put memory at risk, not the core count.
status=0
for case in "${CASES[@]}"; do
    echo "############################################################"
    echo "# case: $case"
    echo "############################################################"
    python lonlat_aod.py \
        --batch "$BATCH_YAML" \
        --case "$case" \
        --days "$DAYS" \
        --vent-lat "$VENT_LAT" \
        --vent-lon "$VENT_LON" \
        --output-dir "$REMOTE_BASE/$BATCH_NAME"
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "case '$case' FAILED (exit $rc)"
        status=$rc
    fi
    echo
done

echo "finished: $(date)  (exit $status)"
exit $status
