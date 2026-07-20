#!/bin/bash
#SBATCH --job-name=exovolc_analysis
#SBATCH --account=s2427
#SBATCH --qos=long
#SBATCH --time=24:00:00
#SBATCH --mem=480gb
#SBATCH -N 1
#SBATCH --constraint=mil
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.out

# NOTE ON THE ALLOCATION SHAPE -- this differs from the CESM run scripts on
# purpose. A CESM job asks for --ntasks-per-node 126 because CAM is MPI and
# wants 126 ranks. run_batch.py is a SINGLE Python process using a threaded
# dask scheduler, so it wants one task holding many cores instead. Asking for
# 126 tasks here would leave SLURM_CPUS_PER_TASK at 1 and quietly run the
# analysis single-threaded on a full node.
#
# Node (Supermicro TwinPro, AMD Milan EPYC): 2 x 64-core sockets = 128 cores,
# 512 GB memory. 126 = 128 less 2 for system overhead, matching the core count
# the CESM scripts request; 480gb leaves headroom under the 512 GB total.
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=126

# Batch analysis of the eruption suites (54 cases across three batches).
#
#   sbatch run_batch.sbatch                      # all three batches
#   sbatch run_batch.sbatch exovolc_hunga.yaml   # one batch
#
# Output goes to scratch, NOT $HOME: 54 cases of figures and CSVs will blow
# past a typical $HOME quota and fail the run partway through.
#
# There is no prompt under sbatch -- run_batch.py skips it when stdin is not a
# TTY. A failing case does not stop the batch; the summary at the end lists
# every failure with a ready-made --case retry line.

set -u

REPO=/gpfsm/dhome/etwolf/pythonWorkspace/exovolcano-analysis-scripts

# Must match remote_base in fetch_config.yaml, otherwise fetch_exovolc.py will
# not find what this run produces. fetch expects <remote_base>/<batch>/{data,
# figures}/<case>/, so point --output-dir at <remote_base>/<batch> -- one
# directory per batch, set per-batch in the loop below.
REMOTE_BASE=/gpfsm/dnb07/projects/p54/users/etwolf/exovolc

# Batches to run; overridden by any arguments passed to sbatch.
BATCHES=("exovolc_hunga.yaml" "exovolc_pinatubo.yaml" "exovolc_tambora.yaml")
if [ "$#" -gt 0 ]; then
    BATCHES=("$@")
fi

# Fail loudly rather than leaving a bare exit code in the job log.
cd "$REPO" || { echo "ERROR: cannot cd to REPO=$REPO"; exit 1; }

if [ ! -d "$REMOTE_BASE" ]; then
    mkdir -p "$REMOTE_BASE" || {
        echo "ERROR: cannot create REMOTE_BASE=$REMOTE_BASE"; exit 1; }
fi
if [ ! -w "$REMOTE_BASE" ]; then
    echo "ERROR: REMOTE_BASE not writable: $REMOTE_BASE"
    exit 1
fi

# Catch a missing/incomplete Python environment now, not 9 cases deep. A batch
# job does not inherit an interactively loaded module or conda env, so this is
# where that shows up.
python -c 'import xarray, dask, netCDF4, numpy, pandas, matplotlib, yaml' || {
    echo "ERROR: python environment is missing a required package."
    echo "       python: $(command -v python)"
    echo "       If you normally 'module load' or activate a conda env for"
    echo "       this, add it to this script above the batch loop."
    exit 1
}

# Cases are independent, and dask's threaded scheduler stops scaling well
# before 126 threads (GIL contention, and this workload is largely Lustre
# I/O-bound). So spend the node on case-level parallelism instead: JOBS cases
# at a time, NTHREADS each, with JOBS * NTHREADS <= the allocation.
#
# 9 x 14 = 126 exactly. These are a starting point, not a tuned result --
# see the timing note at the bottom of this script.
CORES=${SLURM_CPUS_PER_TASK:-8}
JOBS=${JOBS:-9}
NTHREADS=${NTHREADS:-$(( CORES / JOBS ))}
[ "$NTHREADS" -lt 1 ] && NTHREADS=1

echo "host:     $(hostname)"
echo "started:  $(date)"
echo "batches:  ${BATCHES[*]}"
echo "output:   $REMOTE_BASE/<batch>"
echo "cores:    $CORES"
echo "layout:   $JOBS concurrent cases x $NTHREADS threads"
echo

# One run_batch.py call per batch, each writing under its own <batch>
# directory, to produce the <remote_base>/<batch>/{data,figures}/<case>/ layout
# that fetch_exovolc.py discovers.
status=0
for batch in "${BATCHES[@]}"; do
    name=$(basename "$batch" .yaml)      # exovolc_hunga.yaml -> exovolc_hunga
    name=${name#exovolc_}                # -> hunga, matching the fetch batch name

    echo
    echo "############################################################"
    echo "# batch: $name"
    echo "############################################################"

    python run_batch.py "$batch" \
        --output-dir "$REMOTE_BASE/$name" \
        --jobs "$JOBS" \
        --nthreads "$NTHREADS" \
        --time
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "batch '$name' reported failures (exit $rc)"
        status=$rc
    fi
done

echo
echo "finished: $(date)  (exit $status)"
exit $status

# ---------------------------------------------------------------------------
# TUNING JOBS / NTHREADS
#
# 9 x 14 is a guess, not a measurement -- nobody has timed this pipeline on a
# Milan node yet. --time makes every case print a section breakdown; use the
# first real run to find where it actually spends its time. Override without
# editing this file:
#
#     sbatch --export=ALL,JOBS=18,NTHREADS=7 run_batch.sbatch
#
# If cases are I/O-bound on Lustre (likely -- they read multi-GB CAM history),
# more concurrent cases at fewer threads each usually wins, since one case
# blocked on I/O leaves its cores idle. If they turn out to be CPU-bound, push
# the other way.
#
# Memory is unlikely to bind before core count does: 480gb over 9 concurrent
# cases is ~53 GB each, well clear of what one case's dask chunks should need.
# That headroom means JOBS can go well past 9 if the timings favor it -- 18 x 7
# or even 26 x 5 are worth trying. The ceiling to watch is Lustre contention,
# not RAM: enough concurrent readers will slow each other down, and that shows
# up as rising per-case wall time in the --time output rather than as an error.
#
# With only 54 cases, JOBS above ~27 also starts wasting the node on the
# tail -- the last wave runs with most slots idle.
# ---------------------------------------------------------------------------
