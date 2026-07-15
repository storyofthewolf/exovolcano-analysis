#!/usr/bin/env python3
"""
fetch_exovolc.py — sync exovolc analysis output from the cluster to local.

Only the boiled-down analysis output is fetched (CSVs and PNGs, a few MB per
case). The ~2 TB of raw CAM history files stays on the remote — this package
exists precisely to reduce it to something tractable.

Usage:
    python fetch_exovolc.py <name> [<name> ...]   # batch(es) and/or case(s)
    python fetch_exovolc.py --all                  # every case on remote
    python fetch_exovolc.py --prefix exovolc_pin   # cases starting with a prefix
    python fetch_exovolc.py --list                 # show remote cases, fetch nothing

Each NAME may be either:
    * a BATCH   (e.g. "pinatubo") — expands to every case in that batch, or
    * a CASE    (e.g. "exovolc_pinatubo_fid") — fetches just that one case.

Options:
    --all              Discover and sync every case on the remote
    --prefix PREFIX    Discover and sync all cases whose name starts with PREFIX
    --list             List the batches/cases found on the remote and exit
    --data-only        Skip figures/
    --figures-only     Skip data/
    --dry-run          Show what would be transferred without doing it
    --remote HOST      Override default SSH host
    --remote-base DIR  Override default remote base path
    --local-base DIR   Override default local destination

Configuration (highest precedence first):
    CLI flags  →  environment variables  →  fetch_config.yaml  →  built-in
The env vars are EXOVOLC_HOST / EXOVOLC_REMOTE_BASE / EXOVOLC_LOCAL_BASE.
fetch_config.yaml lives next to this script (git-ignored); see
fetch_config.yaml.example for the keys.

Layout
------
A batch run of ~20 cases writes, on the remote:

    <remote_base>/<batch>/data/<case>/{scalar,profiles,aod,zonal}/
    <remote_base>/<batch>/figures/<case>/{,aod,zonal}/

where <batch> is a grouping (e.g. "pinatubo") and <case> is the globally
unique case name (e.g. "exovolc_pinatubo_fid"). Cases are discovered by
listing the <case> dirs inside each batch's data/ and figures/.

Locally the batch grouping is preserved and the duplicated <case> level that
the writer nests under data/ and figures/ is flattened out:

    <local_base>/<batch>/<case>/data/{scalar,profiles,aod,zonal}/
    <local_base>/<batch>/<case>/figures/{,aod,zonal}/
"""

import argparse
import os
import shlex
import subprocess
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#
# Resolution order (highest precedence first): CLI flag > env var >
# fetch_config.yaml > built-in default. This block resolves the env-var /
# file / built-in layers into the DEFAULT_* values argparse falls back on; a
# CLI flag then overrides those.

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_SCRIPT_DIR, "fetch_config.yaml")

_BUILTIN = {
    "remote_host": "",
    "remote_base": "/gpfsm/dnb07/projects/p54/users/etwolf/exovolc",
    "local_base": os.path.join(os.path.expanduser("~"), "research", "exovolc"),
}


def _load_file_config(path):
    """Read remote_host / remote_base / local_base from a small YAML file.

    Kept dependency-free: parses the handful of `key: value` lines we care
    about by hand rather than requiring PyYAML just for three strings. Missing
    file or missing keys are fine — the caller falls back to other layers.
    """
    cfg = {}
    if not os.path.isfile(path):
        return cfg
    wanted = {"remote_host", "remote_base", "local_base"}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            if key not in wanted:
                continue
            val = val.strip().strip("'").strip('"')
            if val:
                cfg[key] = os.path.expanduser(os.path.expandvars(val))
    return cfg


def _resolve(key, env_var):
    """env var > fetch_config.yaml > built-in, for one setting."""
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    if key in _FILE_CONFIG:
        return _FILE_CONFIG[key]
    return _BUILTIN[key]


_FILE_CONFIG = _load_file_config(_CONFIG_FILE)

DEFAULT_REMOTE_HOST = _resolve("remote_host", "EXOVOLC_HOST")
DEFAULT_REMOTE_BASE = _resolve("remote_base", "EXOVOLC_REMOTE_BASE")
DEFAULT_LOCAL_BASE = _resolve("local_base", "EXOVOLC_LOCAL_BASE")

# The two output trees a case produces. Fetched separately so --data-only /
# --figures-only work, and so each can be un-nested independently.
SUBTREES = ("data", "figures")


# ---------------------------------------------------------------------------
# Remote discovery
# ---------------------------------------------------------------------------

def _run_remote(remote_host, pipeline):
    """Run a shell pipeline on the remote under bash, return CompletedProcess.

    The remote login shell may be tcsh (as it is on NCCS Discover), which does
    not understand bash's `2>/dev/null` redirection ("Ambiguous output
    redirect"). Wrap in `bash -c` so the pipeline runs under bash regardless of
    the remote user's default shell.
    """
    cmd = "bash -c " + shlex.quote(pipeline)
    return subprocess.run(
        ["ssh", remote_host, cmd], capture_output=True, text=True
    )


def discover_cases(remote_host, remote_base):
    """Map the remote layout.

    Returns (batches, cases) where:
        batches = {batch_name: [case_name, ...]}   grouping, sorted per batch
        cases   = {case_name: batch_name}          reverse lookup

    A batch is a directory directly under remote_base that contains data/ or
    figures/. A case is a subdirectory of that data/ (or figures/):

        <remote_base>/<batch>/{data,figures}/<case>/

    One SSH call. We list the case dirs two levels below each data/figures dir
    and print "<batch>\\t<case>" for each, so a single pass builds both maps.
    """
    remote_base = remote_base.rstrip("/")
    # For every <base>/<batch>/{data,figures}/<case>/ directory, emit
    # "<batch><TAB><case>". awk pulls the batch and case out of the full path
    # relative to remote_base. sort -u collapses the data/figures duplication.
    #
    # awk -F/ on an absolute path leaves field 1 empty (the leading slash), so
    # path component N lands in awk field N+1. remote_base has count('/')
    # components; the <batch> that follows it is one deeper, hence +2.
    depth = remote_base.count("/") + 2  # awk field index (1-based) of <batch>
    pipeline = (
        f"find {remote_base} -mindepth 3 -maxdepth 3 -type d "
        f"\\( -path '*/data/*' -o -path '*/figures/*' \\) 2>/dev/null "
        f"| awk -F/ '{{print ${depth} \"\\t\" $NF}}' | sort -u"
    )
    result = _run_remote(remote_host, pipeline)
    if result.returncode != 0:
        print(f"ERROR: could not list remote cases:\n{result.stderr}",
              file=sys.stderr)
        sys.exit(1)

    batches = {}
    cases = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        batch, case = line.split("\t", 1)
        batch, case = batch.strip(), case.strip()
        if not batch or not case:
            continue
        if case in cases and cases[case] != batch:
            print(f"WARNING: case '{case}' appears in two batches "
                  f"({cases[case]} and {batch}); keeping the first.",
                  file=sys.stderr)
            continue
        batches.setdefault(batch, [])
        if case not in batches[batch]:
            batches[batch].append(case)
        cases[case] = batch

    for batch in batches:
        batches[batch].sort()

    if not cases:
        print(f"ERROR: no cases found under {remote_host}:{remote_base}\n"
              f"       (looked for <batch>/{{data,figures}}/<case>/ dirs)",
              file=sys.stderr)
        sys.exit(1)

    return batches, cases


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


def sync_case(batch, case, remote_host, remote_base, local_base,
              do_data=True, do_figures=True, dry_run=False, verbose=False):
    """Fetch one case, preserving the batch grouping and flattening the
    duplicated case-name level out of the remote path.

    Remote:  <remote_base>/<batch>/data/<case>/...   (case repeated by writer)
    Local:   <local_base>/<batch>/<case>/data/...    (case appears once)

    The un-nesting uses rsync's trailing-slash rule: a source ending in '/'
    copies the CONTENTS of that directory into the destination, so the remote's
    inner '<case>/' level is consumed by the copy rather than recreated.
    """
    wanted = [s for s, want in (("data", do_data), ("figures", do_figures)) if want]
    remote_base = remote_base.rstrip("/")

    errors = 0
    for subtree in wanted:
        src = f"{remote_host}:{remote_base}/{batch}/{subtree}/{case}/"
        dst = os.path.join(local_base, batch, case, subtree) + os.sep

        if not dry_run:
            os.makedirs(dst, exist_ok=True)

        print(f"  {subtree:8s} {src}")
        print(f"           -> {dst}")

        rc = rsync(src, dst, dry_run=dry_run, verbose=verbose)
        if rc != 0:
            # rsync exits 23/24 when the source path doesn't exist — e.g. a case
            # that has data/ but no figures/ (run with --no-plots). Not fatal.
            if rc in (23, 24):
                print(f"  NOTE: no {subtree}/ for '{case}' on remote — skipped.")
            else:
                print(f"  WARNING: rsync failed for {subtree}/ (exit {rc})",
                      file=sys.stderr)
                errors += 1

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("names", nargs="*", metavar="NAME",
                   help="One or more batch names and/or case names to fetch")
    p.add_argument("--all", dest="all_cases", action="store_true",
                   help="Discover and fetch all cases on the remote")
    p.add_argument("--prefix", metavar="PREFIX",
                   help="Discover and fetch all cases starting with PREFIX")
    p.add_argument("--list", dest="list_only", action="store_true",
                   help="List the batches/cases found on the remote and exit")
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
                   help="Base path on remote (default: EXOVOLC_REMOTE_BASE / config)")
    p.add_argument("--local-base", metavar="DIR", default=DEFAULT_LOCAL_BASE,
                   help="Local destination root (default: EXOVOLC_LOCAL_BASE / config)")
    return p.parse_args()


def resolve_selection(names, batches, cases):
    """Expand a list of batch-or-case NAMEs into a sorted list of case names.

    A name that matches a batch expands to all cases in that batch. A name that
    matches a case selects just that case. Unknown names are collected and
    reported together.
    """
    selected = []
    missing = []
    for name in names:
        if name in batches:
            selected.extend(batches[name])
        elif name in cases:
            selected.append(name)
        else:
            missing.append(name)
    # De-dupe (a batch + one of its cases both named) while keeping sorted order.
    return sorted(set(selected)), missing


def main():
    args = parse_args()

    if not args.remote:
        print("ERROR: no remote host specified.\n"
              "Set EXOVOLC_HOST, add remote_host to fetch_config.yaml, or pass "
              "--remote HOST", file=sys.stderr)
        sys.exit(1)

    if not (args.names or args.all_cases or args.prefix or args.list_only):
        print("ERROR: provide at least one batch/case NAME, --all, "
              "--prefix PREFIX, or --list", file=sys.stderr)
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

    # One SSH call to map the remote layout: which cases exist and which batch
    # each belongs to. Needed for every mode — a name alone doesn't say whether
    # it's a batch or a case, nor which batch a case lives in.
    print("\nDiscovering cases on remote ...")
    batches, cases = discover_cases(args.remote, args.remote_base)
    print(f"  found {len(cases)} case(s) in {len(batches)} batch(es)")

    if args.list_only:
        print()
        for batch in sorted(batches):
            print(f"  {batch}/")
            for case in batches[batch]:
                print(f"      {case}")
        sys.exit(0)

    # Select which cases to fetch
    if args.all_cases:
        selected = sorted(cases)
    elif args.prefix:
        selected = sorted(n for n in cases if n.startswith(args.prefix))
        if not selected:
            print(f"ERROR: no cases match prefix '{args.prefix}'.\n"
                  f"       Run --list to see what's on the remote.", file=sys.stderr)
            sys.exit(1)
    else:
        selected, missing = resolve_selection(args.names, batches, cases)
        if missing:
            print(f"ERROR: name(s) not found on remote: {', '.join(missing)}\n"
                  f"       (not a known batch or case)\n"
                  f"       Run --list to see what's available.", file=sys.stderr)
            sys.exit(1)

    print(f"\nFetching {len(selected)} case(s)"
          f"{' [DRY RUN]' if args.dry_run else ''}:")
    for name in selected:
        print(f"  {cases[name]}/{name}")

    total_errors = 0
    for name in selected:
        print(f"\n{'=' * 60}")
        print(f"  Case: {cases[name]}/{name}")
        print(f"{'=' * 60}")
        total_errors += sync_case(
            batch=cases[name],
            case=name,
            remote_host=args.remote,
            remote_base=args.remote_base,
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
