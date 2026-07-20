#!/usr/bin/env python
"""
run_batch.py - Run run_time_series.py for every case in one or more batches.

A batch YAML lists its eruption cases under 'cases:'.  This script expands each
batch into its cases and runs run_time_series.py once per case, in sequence.

Usage:
    python run_batch.py exovolc_ben1.yaml [flags]
    python run_batch.py exovolc_ben1.yaml exovolc_ben2.yaml [flags]
    python run_batch.py exovolc_ben1.yaml --case exovolc_ben1_h11s10 [--case ...]
    python run_batch.py exovolc_ben1.yaml --dry-run

Batch YAML names are looked up in experiments/ unless a path separator is
present.

--case restricts the run to the named case(s); repeat it for several.  Without
it, every case in every listed batch is run.

--dry-run prints the case list and exits without running anything.

--output-dir sends every case's output to another filesystem, as
DIR/figures/<case>/ and DIR/data/<case>/.  A batch of ~20 cases will exhaust a
typical HPC $HOME quota, so on a cluster point this at scratch:

    python run_batch.py exovolc_ben1.yaml --output-dir /scratch/$USER/exovolc

All other flags are forwarded verbatim to run_time_series.py,
e.g. --nthreads 32 --no-zonal --time
"""

import argparse
import concurrent.futures as cf
import os
import subprocess
import sys
import time

import yaml

EXPERIMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'experiments')


def resolve_batch(path):
    """Look a batch YAML up in experiments/ unless it's an explicit path."""
    if os.path.exists(path):
        return path
    candidate = os.path.join(EXPERIMENTS_DIR, path)
    if os.path.exists(candidate):
        return candidate
    sys.exit(f"ERROR: batch YAML not found: {path}")


def load_cases(path):
    """Return the list of case names declared in a batch YAML."""
    with open(path) as f:
        batch = yaml.safe_load(f) or {}

    raw = batch.get('cases')
    if not raw:
        sys.exit(f"ERROR: '{path}' has no 'cases:' section. "
                 f"See experiments/template.yaml.")

    names = []
    for entry in raw:
        name = entry if isinstance(entry, str) else (entry or {}).get('name')
        if not name:
            sys.exit(f"ERROR: a case in '{path}' has no 'name'.")
        names.append(name)
    return names


def parse_args():
    parser = argparse.ArgumentParser(
        prog='run_batch.py',
        description='Run run_time_series.py for every case in one or more batches.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'batches', nargs='+', metavar='batch.yaml',
        help='One or more batch YAML names.',
    )
    parser.add_argument(
        '--case', action='append', metavar='NAME', default=None,
        help='Run only this case (repeatable). Default: every case in the batch.',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='List the cases that would run, then exit.',
    )
    parser.add_argument(
        '--yes', '-y', action='store_true',
        help='Skip the confirmation prompt. Implied when stdin is not a TTY, '
             'so batch scheduler jobs (sbatch) run unattended.',
    )
    parser.add_argument(
        '--jobs', '-j', type=int, default=1, metavar='N',
        help='Run N cases concurrently (default 1 = sequential). Cases are '
             'independent, so on a many-core node N cases at moderate '
             '--nthreads beats one case at a huge --nthreads. Keep '
             'N * nthreads at or under your core allocation.',
    )
    parser.add_argument(
        '--nthreads', type=int, default=None, metavar='N',
        help='Forwarded to run_time_series.py.',
    )
    parser.add_argument(
        '--output-dir', metavar='DIR', default=None,
        help='Write every case under DIR (as DIR/figures/ and DIR/data/). '
             'Use this to keep a batch off a quota-limited $HOME.',
    )
    parser.add_argument(
        '--figures-dir', metavar='DIR', default=None,
        help='Root directory for PNG output. Overrides --output-dir.',
    )
    parser.add_argument(
        '--data-dir', metavar='DIR', default=None,
        help='Root directory for CSV output. Overrides --output-dir.',
    )
    parser.add_argument('--time',        action='store_true')
    parser.add_argument('--no-scalars',  action='store_true')
    parser.add_argument('--no-profiles', action='store_true')
    parser.add_argument('--no-plots',    action='store_true')
    parser.add_argument('--no-aod',      action='store_true')
    parser.add_argument('--no-zonal',    action='store_true')

    return parser.parse_args()


def build_forward_flags(args):
    """Reconstruct flags to pass through to run_time_series.py."""
    flags = []
    if args.nthreads is not None:
        flags += ['--nthreads', str(args.nthreads)]
    for flag in ('output_dir', 'figures_dir', 'data_dir'):
        value = getattr(args, flag)
        if value:
            flags += ['--' + flag.replace('_', '-'), value]
    for flag in ('time', 'no_scalars', 'no_profiles', 'no_plots', 'no_aod', 'no_zonal'):
        if getattr(args, flag):
            flags.append('--' + flag.replace('_', '-'))
    return flags


def expand(batches, only_cases):
    """Expand batch YAMLs into a flat list of (batch_path, case_name)."""
    jobs = []
    for batch_arg in batches:
        path = resolve_batch(batch_arg)
        for case in load_cases(path):
            if only_cases and case not in only_cases:
                continue
            jobs.append((path, case))

    if only_cases:
        found = {case for _, case in jobs}
        missing = [c for c in only_cases if c not in found]
        if missing:
            sys.exit(f"ERROR: case(s) not found in the given batch(es): "
                     f"{', '.join(missing)}")

    if not jobs:
        sys.exit("ERROR: no cases to run.")
    return jobs


def run_one(batch_path, case, forward_flags, capture=False):
    """Run one case. With capture, hold its output and print it as one block.

    Concurrent cases share a stdout, so streaming them live interleaves the
    lines of several cases into an unreadable log. Capturing keeps each case's
    output contiguous, at the cost of only seeing it once the case finishes.
    """
    cmd = [sys.executable, 'run_time_series.py', batch_path,
           '--case', case] + forward_flags
    header = f"\n{'=' * 60}\n  Case: {case}\n{'=' * 60}"

    t0 = time.perf_counter()
    if capture:
        result = subprocess.run(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        elapsed = time.perf_counter() - t0
        print(header)
        print(result.stdout, end='' if result.stdout.endswith('\n') else '\n')
        sys.stdout.flush()
    else:
        print(header)
        result = subprocess.run(cmd)
        elapsed = time.perf_counter() - t0

    return result.returncode, elapsed


def main():
    args = parse_args()
    jobs = expand(args.batches, args.case)

    print(f"\nBatch run: {len(jobs)} case(s)")
    current = None
    for batch_path, case in jobs:
        if batch_path != current:
            print(f"  {os.path.basename(batch_path)}")
            current = batch_path
        print(f"      {case}")

    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return

    forward_flags = build_forward_flags(args)

    # Under sbatch there is no TTY, so prompting would raise EOFError and abort
    # the whole batch without running a single case -- an exit-0 no-op that
    # reads as success in the job log. Only prompt when someone is watching.
    if not (args.yes or not sys.stdin.isatty()):
        try:
            answer = input("\nProceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if answer not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(0)

    results = []
    t_batch_start = time.perf_counter()
    interrupted = False

    # A 50+ case batch runs for hours. If it is cut short -- Ctrl-C, or the
    # scheduler killing the job at its walltime -- still report what finished,
    # so the survivors can be skipped on the next attempt with --case.
    try:
        if args.jobs > 1:
            # Cases are independent processes, so concurrency is just a pool.
            # Output is captured per case to keep each one's log contiguous.
            with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {
                    pool.submit(run_one, batch_path, case, forward_flags, True): case
                    for batch_path, case in jobs
                }
                try:
                    for future in cf.as_completed(futures):
                        case = futures[future]
                        returncode, elapsed = future.result()
                        status = 'OK' if returncode == 0 else f'FAILED (exit {returncode})'
                        results.append((case, status, elapsed))
                except KeyboardInterrupt:
                    # Drop queued cases; those already running still finish.
                    for future in futures:
                        future.cancel()
                    raise
        else:
            for batch_path, case in jobs:
                returncode, elapsed = run_one(batch_path, case, forward_flags)
                status = 'OK' if returncode == 0 else f'FAILED (exit {returncode})'
                results.append((case, status, elapsed))
    except KeyboardInterrupt:
        interrupted = True
        print("\n\nInterrupted -- reporting cases finished so far.")

    if not results:
        print("\nNo cases ran.")
        sys.exit(1)

    # Summary
    total_elapsed = time.perf_counter() - t_batch_start
    print(f"\n{'=' * 60}")
    print(f"  Batch summary  ({len(results)} of {len(jobs)} cases,  "
          f"{total_elapsed:.1f} s total)")
    print(f"{'=' * 60}")
    # Report in batch order, not completion order, so the summary reads the
    # same whether the run was sequential or concurrent.
    order = {case: i for i, (_, case) in enumerate(jobs)}
    results.sort(key=lambda r: order[r[0]])
    col_w = max(len(r[0]) for r in results)
    for name, status, elapsed in results:
        print(f"  {name:<{col_w}}   {elapsed:>8.1f} s   {status}")

    failed = [n for n, s, _ in results if s != 'OK']
    # Compare by name, not by position: with --jobs the cases finish out of
    # order, so slicing jobs by len(results) would name the wrong survivors.
    done = {n for n, _, _ in results}
    remaining = [c for _, c in jobs if c not in done]

    if failed:
        print(f"\n{len(failed)} case(s) FAILED:")
        for name in failed:
            print(f"  {name}")
    if remaining:
        print(f"\n{len(remaining)} case(s) never ran.")
    if failed or remaining:
        # Re-run just the unfinished work.
        retry = ' '.join(f'--case {c}' for c in failed + remaining)
        print(f"\nTo retry those cases:\n  {retry}")
        sys.exit(1)

    if interrupted:
        sys.exit(1)
    print(f"\nAll cases completed successfully.")


if __name__ == '__main__':
    main()
