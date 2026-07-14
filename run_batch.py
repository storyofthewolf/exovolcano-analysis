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

All other flags are forwarded verbatim to run_time_series.py,
e.g. --nthreads 32 --no-zonal --time
"""

import argparse
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
        '--nthreads', type=int, default=None, metavar='N',
        help='Forwarded to run_time_series.py.',
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


def run_one(batch_path, case, forward_flags):
    cmd = [sys.executable, 'run_time_series.py', batch_path,
           '--case', case] + forward_flags
    print(f"\n{'=' * 60}")
    print(f"  Case: {case}")
    print(f"{'=' * 60}")
    t0 = time.perf_counter()
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

    for batch_path, case in jobs:
        returncode, elapsed = run_one(batch_path, case, forward_flags)
        status = 'OK' if returncode == 0 else f'FAILED (exit {returncode})'
        results.append((case, status, elapsed))

    # Summary
    total_elapsed = time.perf_counter() - t_batch_start
    print(f"\n{'=' * 60}")
    print(f"  Batch summary  ({len(jobs)} cases,  {total_elapsed:.1f} s total)")
    print(f"{'=' * 60}")
    col_w = max(len(r[0]) for r in results)
    for name, status, elapsed in results:
        print(f"  {name:<{col_w}}   {elapsed:>8.1f} s   {status}")

    n_failed = sum(1 for _, s, _ in results if s != 'OK')
    if n_failed:
        print(f"\n{n_failed} case(s) FAILED.")
        sys.exit(1)
    else:
        print(f"\nAll cases completed successfully.")


if __name__ == '__main__':
    main()
