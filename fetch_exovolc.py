#!/usr/bin/env python3
"""
fetch_exovolc.py — sync exovolc output from cluster to local machine.

Usage:
    python fetch_exovolc.py <casename> [<casename> ...]   # specific cases
    python fetch_exovolc.py --all                          # every case on remote
    python fetch_exovolc.py --prefix ben2                  # all cases starting with "ben2"

Options:
    --all              Discover and sync all casenames on the remote
    --prefix PREFIX    Discover and sync all casenames whose name starts with PREFIX
    --data-only        Skip figures/
    --figures-only     Skip data/
    --dry-run          Show what would be transferred without doing it
    --remote HOST      Override default SSH host (default: EXOVOLC_HOST env var)
    --remote-base DIR  Override default remote base path
    --local-base DIR   Override default local destination

Environment variables (set in your shell profile to avoid typing):
    EXOVOLC_HOST        e.g. "etwolf@discover.nccs.nasa.gov"
    EXOVOLC_REMOTE_BASE e.g. "/gpfsm/dnb07/projects/p54/users/etwolf/exovolc/analysis"
    EXOVOLC_LOCAL_BASE  e.g. "/Users/etwolf/research/exovolc"
"""

import argparse
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# Defaults — override via env vars or CLI flags
# ---------------------------------------------------------------------------

DEFAULT_REMOTE_HOST = os.environ.get("EXOVOLC_HOST", "")
DEFAULT_REMOTE_BASE = os.environ.get(
    "EXOVOLC_REMOTE_BASE",
    "/gpfsm/dnb07/projects/p54/users/etwolf/exovolc",
)
DEFAULT_LOCAL_BASE = os.environ.get(
    "EXOVOLC_LOCAL_BASE",
    os.path.join(os.path.expanduser("~"), "research", "exovolc"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_rsync(src, dst, dry_run=False, verbose=False, extra_flags=None):
    """
    Run rsync from src to dst.  Returns returncode.
    src / dst follow rsync syntax: remote paths are 'host:path'.
    """
    flags = ["-az", "--stats"]
    if verbose:
        flags += ["-v", "--progress"]
    if dry_run:
        flags.append("--dry-run")
    if extra_flags:
        flags.extend(extra_flags)

    cmd = ["rsync"] + flags + [src, dst]
    print(f"\n  rsync  {src}")
    print(f"      -> {dst}")
    if dry_run:
        print("  [DRY RUN]")

    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def run_rsync_show_cases(src, dst, dry_run=False, extra_flags=None):
    """
    Run rsync with -v and stream output, printing a banner each time a new
    top-level casename is seen (first path component of each transferred file).
    Returns returncode.
    """
    flags = ["-az", "--stats", "-v"]
    if dry_run:
        flags.append("--dry-run")
    if extra_flags:
        flags.extend(extra_flags)

    cmd = ["rsync"] + flags + [src, dst]
    print(f"\n  rsync  {src}")
    print(f"      -> {dst}")
    if dry_run:
        print("  [DRY RUN]")
    print()

    current_case = None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        line = line.rstrip("\n")
        # Detect file transfer lines: non-empty, not a stats line, contains a /
        if line and "/" in line and not line.startswith((" ", "\t", ">")):
            case = line.split("/")[0]
            if case != current_case:
                current_case = case
                print(f"\n  [{case}]")
        else:
            print(line)
        sys.stdout.flush()
    proc.wait()
    return proc.returncode


def discover_casenames(remote_host, remote_base):
    """
    List subdirectories inside remote_base/data/ — each is a casename.
    Uses a single SSH call; returns sorted list of strings.
    """
    cmd = ["ssh", remote_host, f"ls -1d {remote_base}/*/"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: could not list remote cases:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    cases = []
    for line in result.stdout.splitlines():
        # strip trailing slash and path prefix
        name = line.rstrip("/").split("/")[-1]
        if name:
            cases.append(name)
    return sorted(cases)


def sync_case(casename, remote_host, remote_base, local_base,
              do_data=True, do_figures=True, dry_run=False, verbose=False):
    """
    Sync one casename in a single rsync call (one authentication).

    Remote layout: <remote_base>/<casename>/data/<casename>/
                   <remote_base>/<casename>/figures/<casename>/
    Local layout:  <local_base>/data/<casename>/
                   <local_base>/figures/<casename>/
    """
    # Build include/exclude filters so we can selectively skip data or figures
    # while still using a single rsync invocation (one SSH authentication).
    extra_flags = []
    if do_data and not do_figures:
        extra_flags = ["--include=data/***", "--exclude=figures/***"]
    elif do_figures and not do_data:
        extra_flags = ["--include=figures/***", "--exclude=data/***"]

    src = f"{remote_host}:{remote_base}/{casename}/"
    dst = os.path.join(local_base, casename) + "/"
    os.makedirs(dst, exist_ok=True)

    rc = run_rsync(src, dst, dry_run=dry_run, verbose=verbose, extra_flags=extra_flags or None)
    if rc != 0:
        print(f"  WARNING: rsync returned code {rc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("casenames", nargs="*", metavar="CASENAME",
                   help="One or more casenames to fetch")
    p.add_argument("--all", dest="all_cases", action="store_true",
                   help="Discover and fetch all casenames on the remote")
    p.add_argument("--prefix", metavar="PREFIX",
                   help="Discover and fetch all casenames starting with PREFIX")
    p.add_argument("--data-only", action="store_true",
                   help="Skip figures/")
    p.add_argument("--figures-only", action="store_true",
                   help="Skip data/")
    p.add_argument("--verbose", action="store_true",
                   help="Show per-file transfer progress (default: stats summary only)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be transferred (no actual copy)")
    p.add_argument("--remote", metavar="HOST", default=DEFAULT_REMOTE_HOST,
                   help="SSH host string, e.g. etwolf@discover.nccs.nasa.gov")
    p.add_argument("--remote-base", metavar="DIR", default=DEFAULT_REMOTE_BASE,
                   help="Base path on remote (default: EXOVOLC_REMOTE_BASE env or hardcoded)")
    p.add_argument("--local-base", metavar="DIR", default=DEFAULT_LOCAL_BASE,
                   help="Local destination root (default: EXOVOLC_LOCAL_BASE env or ~/research/exovolc)")
    return p.parse_args()


def main():
    args = parse_args()

    if not args.remote:
        print(
            "ERROR: no remote host specified.\n"
            "Set EXOVOLC_HOST env var or pass --remote HOST",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.casenames and not args.all_cases and not args.prefix:
        print("ERROR: provide at least one casename, --all, or --prefix PREFIX", file=sys.stderr)
        sys.exit(1)

    do_data    = not args.figures_only
    do_figures = not args.data_only

    print(f"\nRemote : {args.remote}:{args.remote_base}")
    print(f"Local  : {args.local_base}")
    print(f"Sync   : {'data ' if do_data else ''}{'figures' if do_figures else ''}")

    # --all: sync entire remote base in one rsync call (one authentication)
    if args.all_cases:
        print("\nSyncing all cases in one rsync pass ...")
        extra_flags = []
        if do_data and not do_figures:
            extra_flags = ["--include=*/", "--include=*/data/***", "--exclude=*"]
        elif do_figures and not do_data:
            extra_flags = ["--include=*/", "--include=*/figures/***", "--exclude=*"]
        src = f"{args.remote}:{args.remote_base}/"
        dst = args.local_base + "/"
        os.makedirs(dst, exist_ok=True)
        rc = run_rsync_show_cases(src, dst, dry_run=args.dry_run, extra_flags=extra_flags or None)
        print(f"\nDone. {'DRY RUN — ' if args.dry_run else ''}exit code {rc}.")
        sys.exit(0 if rc == 0 else 1)

    # --prefix: single rsync call using glob filters — no separate SSH discovery
    if args.prefix:
        p = args.prefix
        extra_flags = [f"--include={p}*/"]
        if do_data:
            extra_flags += [f"--include={p}*/data/", f"--include={p}*/data/**"]
        if do_figures:
            extra_flags += [f"--include={p}*/figures/", f"--include={p}*/figures/**"]
        extra_flags += ["--exclude=*"]
        src = f"{args.remote}:{args.remote_base}/"
        dst = args.local_base + "/"
        os.makedirs(dst, exist_ok=True)
        rc = run_rsync_show_cases(src, dst, dry_run=args.dry_run, extra_flags=extra_flags)
        print(f"\nDone. {'DRY RUN — ' if args.dry_run else ''}exit code {rc}.")
        sys.exit(0 if rc == 0 else 1)

    # Specific casenames: one rsync per case (one authentication each)
    total_errors = 0
    for case in args.casenames:
        print(f"\n{'='*60}")
        print(f"  Case: {case}")
        print(f"{'='*60}")
        total_errors += sync_case(
            case,
            remote_host=args.remote,
            remote_base=args.remote_base,
            local_base=args.local_base,
            do_data=do_data,
            do_figures=do_figures,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

    print(f"\nDone. {len(args.casenames)} case(s) processed, {total_errors} error(s).")
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
