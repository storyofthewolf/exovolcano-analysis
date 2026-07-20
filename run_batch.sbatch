#!/bin/bash
#SBATCH --job-name=exovolc_analysis
#SBATCH --account=s2427
#SBATCH --qos=long
#SBATCH --time=24:00:00
#SBATCH --mem=100gb
#SBATCH -N 1
#SBATCH --constraint=mil
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.out

# NOTE ON THE ALLOCATION SHAPE -- this differs from the CESM run scripts on
# purpose. A CESM job asks for --ntasks-per-node 126 because CAM is MPI and
# wants 126 ranks. run_batch.py is a SINGLE Python process using a threaded
# dask scheduler, so it wants one task holding many cores instead. Asking for
# 126 tasks here would leave SLURM_CPUS_PER_TASK at 1 and quietly run the
# analysis single-threaded on a 126-core node.
#
# 124 = 126 cores on a Milan node, less 2 left for system overhead.
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=124

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

REPO=/gpfsm/dhome/etwolf/pythonWorkspace/exovolcano-analysis

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

cd "$REPO" || exit 1

# Cases are independent, and dask's threaded scheduler stops scaling well
# before 124 threads (GIL contention, and this workload is largely Lustre
# I/O-bound). So spend the node on case-level parallelism instead: JOBS cases
# at a time, NTHREADS each, with JOBS * NTHREADS <= the allocation.
#
# 8 x 15 = 120 of 124 cores. These are a starting point, not a tuned result --
# see the timing note at the bottom of this script.
CORES=${SLURM_CPUS_PER_TASK:-8}
JOBS=${JOBS:-8}
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
# 8 x 15 is a guess, not a measurement -- nobody has timed this pipeline on a
# Milan node yet. --time makes every case print a section breakdown; use the
# first real run to find where it actually spends its time. Override without
# editing this file:
#
#     sbatch --export=ALL,JOBS=16,NTHREADS=7 run_batch.sbatch
#
# If cases are I/O-bound on Lustre (likely -- they read multi-GB CAM history),
# more concurrent cases at fewer threads each usually wins, since one case
# blocked on I/O leaves its cores idle. If they turn out to be CPU-bound,
# push the other way. Memory is the limit on raising JOBS: --mem=100gb across
# JOBS cases is ~12 GB per case at 8, and each case holds dask chunks of a
# multi-GB dataset. Watch for OOM kills before raising it much higher.
# ---------------------------------------------------------------------------
