#!/usr/bin/env python3
"""
fetch_exovolc.py — sync exovolc analysis output from the cluster to local.

Only the boiled-down analysis output is fetched (CSVs and PNGs, a few MB per
case). The ~2 TB of raw CAM history files stays on the remote — this package
exists precisely to reduce it to something tractable.

Usage:
    python fetch_exovolc.py <casename> [<casename> ...]   # specific cases
    python fetch_exovolc.py --all                          # every case on remote
    python fetch_exovolc.py --prefix ben2                  # cases starting with "ben2"
    python fetch_exovolc.py --list                         # show remote cases, fetch nothing

Options:
    --all              Discover and sync every case on the remote
    --prefix PREFIX    Discover and sync all cases whose name starts with PREFIX
    --list             List the cases found on the remote and exit
    --data-only        Skip figures/
    --figures-only     Skip data/
    --dry-run          Show what would be transferred without doing it
    --remote HOST      Override default SSH host (default: EXOVOLC_HOST env var)
    --remote-base DIR  Override default remote base path
    --local-base DIR   Override default local destination

Environment variables (set in your shell profile to avoid typing):
    EXOVOLC_HOST        e.g. "etwolf@discover.nccs.nasa.gov"
    EXOVOLC_REMOTE_BASE e.g. "/gpfsm/dnb07/.../exovolc/analysis"
    EXOVOLC_LOCAL_BASE  e.g. "/Users/wolfe/Desktop/projects/volcanos/remote_analysis"

Layout
------
On the remote, run_time_series.py writes its output under the analysis dir it
was run from, and it names that output for the case:

    <somewhere>/<case>/data/<case>/{scalar,profiles,aod,zonal}/
    <somewhere>/<case>/figures/<case>/{,aod,zonal}/

...where <somewhere> is either <remote_base> directly, or a batch subdirectory
of it (a batch of ~20 cases run together). Both layouts are in use, so the
case directory is found by SEARCHING for the dir that contains data/ and/or
figures/, rather than by assuming a fixed depth.

Locally the case name is not repeated, and any batch level is dropped — every
case gets the same shape, keyed by its (globally unique) name:

    <local_base>/<case>/data/{scalar,profiles,aod,zonal}/
    <local_base>/<case>/figures/{,aod,zonal}/
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

# The two output trees a case produces. Fetched separately so --data-only /
# --figures-only work, and so each can be un-nested independently.
SUBTREES = ("data", "figures")


# ---------------------------------------------------------------------------
# Remote discovery
# ---------------------------------------------------------------------------

def discover_cases(remote_host, remote_base):
    """Return {case_name: remote_case_dir} for every case under remote_base.

    A case directory is one that CONTAINS a 'data' or 'figures' subdirectory.
    Searching for that marker (rather than assuming a depth) handles both
    layouts in use: a case sitting directly under remote_base, and a case
    nested one level down inside a batch directory.

    One SSH call. -maxdepth 3 covers <base>/<case>/data and
    <base>/<batch>/<case>/data without descending into the output trees.
    """
    remote_base = remote_base.rstrip("/")
    # Print the PARENT of each data/ or figures/ dir found — that parent is the
    # case dir. sort -u collapses the data/figures pair down to one line each.
    find_cmd = (
        f"find {remote_base} -mindepth 2 -maxdepth 3 "
        f"\\( -name data -o -name figures \\) -type d "
        f"-exec dirname {{}} \\; 2>/dev/null | sort -u"
    )
    result = subprocess.run(
        ["ssh", remote_host, find_cmd], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: could not list remote cases:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    cases = {}
    for line in result.stdout.splitlines():
        path = line.strip().rstrip("/")
        if not path:
            continue
        name = os.path.basename(path)
        if name in cases and cases[name] != path:
            print(f"WARNING: duplicate case name '{name}' on remote:\n"
                  f"           {cases[name]}\n"
                  f"           {path}\n"
                  f"         Local layout is keyed by case name, so these would "
                  f"collide. Skipping the second.", file=sys.stderr)
            continue
        cases[name] = path

    if not cases:
        print(f"ERROR: no cases found under {remote_host}:{remote_base}\n"
              f"       (looked for directories containing data/ or figures/)",
              file=sys.stderr)
        sys.exit(1)

    return cases


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------

def rsync(src, dst, dry_run=False, verbose=False):
    """Run one rsync. Returns the return code."""
    flags = ["-az", "--stats"]
    if verbose:
        flags += ["-v", "--progress"]
    if dry_run:
        flags.append("--dry-run")

    result = subprocess.run(["rsync"] + flags + [src, dst])
    return result.returncode


def sync_case(name, remote_case_dir, remote_host, local_base,
              do_data=True, do_figures=True, dry_run=False, verbose=False):
    """Fetch one case, flattening the duplicated case name out of the path.

    Remote:  <remote_case_dir>/data/<name>/...     (name repeated by the writer)
    Local:   <local_base>/<name>/data/...          (name appears once)

    The un-nesting is done by rsync's trailing-slash rule: a source ending in
    '/' copies the CONTENTS of that directory into the destination. So the
    remote's inner '<name>/' level is consumed by the copy rather than
    recreated locally.
    """
    wanted = [s for s, want in (("data", do_data), ("figures", do_figures)) if want]

    errors = 0
    copied = []
    for subtree in wanted:
        # The writer nests the output under a dir named for the case. Source
        # that inner dir, with a trailing slash, so its contents land directly
        # in <local>/<name>/<subtree>/.
        src = f"{remote_host}:{remote_case_dir}/{subtree}/{name}/"
        dst = os.path.join(local_base, name, subtree) + os.sep

        if not dry_run:
            os.makedirs(dst, exist_ok=True)

        print(f"  {subtree:8s} {src}")
        print(f"           -> {dst}")

        rc = rsync(src, dst, dry_run=dry_run, verbose=verbose)
        if rc != 0:
            # rsync exits 23/24 when the source path doesn't exist — e.g. a case
            # that has data/ but no figures/ (run with --no-plots). Not fatal.
            if rc in (23, 24):
                print(f"  NOTE: no {subtree}/ for '{name}' on remote — skipped.")
            else:
                print(f"  WARNING: rsync failed for {subtree}/ (exit {rc})",
                      file=sys.stderr)
                errors += 1
        else:
            copied.append(subtree)

    return errors


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
                   help="Discover and fetch all cases on the remote")
    p.add_argument("--prefix", metavar="PREFIX",
                   help="Discover and fetch all cases starting with PREFIX")
    p.add_argument("--list", dest="list_only", action="store_true",
                   help="List the cases found on the remote and exit")
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
                   help="Base path on remote (default: EXOVOLC_REMOTE_BASE env)")
    p.add_argument("--local-base", metavar="DIR", default=DEFAULT_LOCAL_BASE,
                   help="Local destination root (default: EXOVOLC_LOCAL_BASE env)")
    return p.parse_args()


def main():
    args = parse_args()

    if not args.remote:
        print("ERROR: no remote host specified.\n"
              "Set EXOVOLC_HOST env var or pass --remote HOST", file=sys.stderr)
        sys.exit(1)

    if not (args.casenames or args.all_cases or args.prefix or args.list_only):
        print("ERROR: provide at least one casename, --all, --prefix PREFIX, or --list",
              file=sys.stderr)
        sys.exit(1)

    if args.data_only and args.figures_only:
        print("ERROR: --data-only and --figures-only are mutually exclusive.",
              file=sys.stderr)
        sys.exit(1)

    do_data    = not args.figures_only
    do_figures = not args.data_only

    print(f"\nRemote : {args.remote}:{args.remote_base}")
    print(f"Local  : {args.local_base}")
    print(f"Sync   : {' + '.join(s for s, w in (('data', do_data), ('figures', do_figures)) if w)}")

    # One SSH call to map case name -> remote dir. Needed for every mode: the
    # remote nests some cases under a batch dir, so a name alone doesn't
    # determine its path.
    print("\nDiscovering cases on remote ...")
    available = discover_cases(args.remote, args.remote_base)
    print(f"  found {len(available)} case(s)")

    if args.list_only:
        base = args.remote_base.rstrip("/")
        print()
        for name in sorted(available):
            rel = os.path.relpath(available[name], base)
            # Show the batch grouping where one exists, since it's dropped locally
            note = "" if rel == name else f"   (under {os.path.dirname(rel)}/)"
            print(f"  {name}{note}")
        sys.exit(0)

    # Select which cases to fetch
    if args.all_cases:
        selected = sorted(available)
    elif args.prefix:
        selected = sorted(n for n in available if n.startswith(args.prefix))
        if not selected:
            print(f"ERROR: no cases match prefix '{args.prefix}'.\n"
                  f"       Run --list to see what's on the remote.", file=sys.stderr)
            sys.exit(1)
    else:
        selected = []
        missing = []
        for name in args.casenames:
            if name in available:
                selected.append(name)
            else:
                missing.append(name)
        if missing:
            print(f"ERROR: case(s) not found on remote: {', '.join(missing)}\n"
                  f"       Run --list to see what's available.", file=sys.stderr)
            sys.exit(1)

    print(f"\nFetching {len(selected)} case(s)"
          f"{' [DRY RUN]' if args.dry_run else ''}:")
    for name in selected:
        print(f"  {name}")

    total_errors = 0
    for name in selected:
        print(f"\n{'=' * 60}")
        print(f"  Case: {name}")
        print(f"{'=' * 60}")
        total_errors += sync_case(
            name,
            remote_case_dir=available[name],
            remote_host=args.remote,
            local_base=args.local_base,
            do_data=do_data,
            do_figures=do_figures,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

    print(f"\nDone. {len(selected)} case(s) processed, {total_errors} error(s)."
          f"{' DRY RUN — nothing copied.' if args.dry_run else ''}")
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
