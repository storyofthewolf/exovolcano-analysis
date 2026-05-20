#!/usr/bin/env python
"""
run_batch.py - Run run_time_series.py sequentially for a list of experiments.

Usage:
    python run_batch.py exp1.yaml exp2.yaml exp3.yaml [flags]
    python run_batch.py --batch-file cases.txt [flags]
    python run_batch.py case1.yaml case2.yaml --prefix experiments/batch_A/

--prefix prepends a string to every YAML name before passing it to
run_time_series.py.  It is consumed by run_batch.py and not forwarded.
Example: --prefix experiments/batch_A/ turns case1.yaml into
experiments/batch_A/case1.yaml.

All other flags are forwarded verbatim to run_time_series.py,
e.g. --nthreads 16 --no-aod --time

--batch-file format: one experiment YAML name per line; blank lines and
lines starting with '#' are ignored.
"""

import argparse
import subprocess
import sys
import time


def load_batch_file(path):
    with open(path) as f:
        lines = f.readlines()
    return [ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith('#')]


def parse_args():
    parser = argparse.ArgumentParser(
        prog='run_batch.py',
        description='Run run_time_series.py for multiple experiment YAMLs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'configs', nargs='*', metavar='experiment.yaml',
        help='One or more experiment YAML names.',
    )
    parser.add_argument(
        '--batch-file', metavar='FILE',
        help='Text file listing experiment YAMLs, one per line.',
    )
    # Capture remaining flags to forward to run_time_series.py
    parser.add_argument(
        '--nthreads', type=int, default=None, metavar='N',
        help='Forwarded to run_time_series.py.',
    )
    parser.add_argument('--time',       action='store_true')
    parser.add_argument('--no-scalars', action='store_true')
    parser.add_argument('--no-profiles',action='store_true')
    parser.add_argument('--no-plots',   action='store_true')
    parser.add_argument('--no-aod',     action='store_true')
    parser.add_argument('--no-zonal',   action='store_true')
    parser.add_argument(
        '--prefix', default='', metavar='PREFIX',
        help='String prepended to every YAML name (e.g. experiments/batch_A/).',
    )

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


def run_one(yaml_name, prefix, forward_flags):
    full_name = prefix + yaml_name
    cmd = [sys.executable, 'run_time_series.py', full_name] + forward_flags
    print(f"\n{'='*60}")
    print(f"  Case: {full_name}")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    result = subprocess.run(cmd)
    elapsed = time.perf_counter() - t0
    return result.returncode, elapsed


def main():
    args = parse_args()

    cases = list(args.configs)
    if args.batch_file:
        cases += load_batch_file(args.batch_file)

    if not cases:
        print("ERROR: No experiment YAMLs specified. Use positional args or --batch-file.")
        sys.exit(1)

    forward_flags = build_forward_flags(args)

    print(f"\nBatch run: {len(cases)} case(s)")
    for c in cases:
        print(f"  {c}")

    results = []
    t_batch_start = time.perf_counter()

    for yaml_name in cases:
        returncode, elapsed = run_one(yaml_name, args.prefix, forward_flags)
        status = 'OK' if returncode == 0 else f'FAILED (exit {returncode})'
        results.append((args.prefix + yaml_name, status, elapsed))

    # Summary
    total_elapsed = time.perf_counter() - t_batch_start
    print(f"\n{'='*60}")
    print(f"  Batch summary  ({len(cases)} cases,  {total_elapsed:.1f} s total)")
    print(f"{'='*60}")
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
