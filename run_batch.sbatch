#!/bin/bash
#SBATCH --job-name=exovolc_analysis
#SBATCH --account=s2427
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --time=12:00:00
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.out

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

# Match the dask thread count to the cores actually allocated.
NTHREADS=${SLURM_CPUS_PER_TASK:-8}

echo "host:     $(hostname)"
echo "started:  $(date)"
echo "batches:  ${BATCHES[*]}"
echo "output:   $REMOTE_BASE/<batch>"
echo "threads:  $NTHREADS"
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
