#!/usr/bin/env python3
"""
spawn_experiment.py - Clone an experiment YAML with a new casename.

Replaces all occurrences of the source casename (filename stem) with
new_casename in both the filename and file content. Supports cloning to
multiple new casenames in one call, via positional args and/or a text file
listing casenames (one per line).

Usage:
    python spawn_experiment.py <source.yaml> <new_casename> [<new_casename> ...] [--dir DIR] [--force]
    python spawn_experiment.py <source.yaml> --names-file FILE [--dir DIR] [--force]
    python spawn_experiment.py <source.yaml> <new_casename> ... --source-dir SRC --dest-dir DEST [--force]

--dir sets both source and destination to the same directory. Use
--source-dir/--dest-dir instead when cloning across subfolders (e.g. source
in experiments/exovolc_ben1/, new cases going into experiments/exovolc_ben2/).
--dir and --source-dir/--dest-dir are mutually exclusive.

--names-file lists one new casename per line; blank lines and lines starting
with '#' are ignored. Names from the file are appended to any positional
casenames.

Examples:
    # single clone, source and dest both in experiments/exovolc_ben1/
    python spawn_experiment.py exovolc_ben1_h10s9.yaml exovolc_ben1_h11s10 --dir experiments/exovolc_ben1

    # bulk clone, explicit casenames
    python spawn_experiment.py exovolc_ben1_h10s9.yaml exovolc_ben1_h11s10 exovolc_ben1_h12s11 exovolc_ben1_h13s12 \\
        --dir experiments/exovolc_ben1

    # bulk clone from a text file of casenames
    python spawn_experiment.py exovolc_ben1_h10s9.yaml --names-file newcases.txt --dir experiments/exovolc_ben1

    # cross-folder clone: source in exovolc_ben1/, new cases written into exovolc_ben2/
    python spawn_experiment.py exovolc_ben1_h10s9.yaml exovolc_ben2_h11s10 exovolc_ben2_h12s11 \\
        --source-dir experiments/exovolc_ben1 --dest-dir experiments/exovolc_ben2

    # full paths, no --dir needed
    python spawn_experiment.py experiments/exovolc_ben1/exovolc_ben1_h10s9.yaml exovolc_ben1_h11s10
"""

import argparse
import os
import sys


def load_names_file(path):
    with open(path) as f:
        lines = f.readlines()
    return [ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith('#')]


def spawn(source_arg, new_casename, source_dir=None, dest_dir=None, force=False):
    if source_dir:
        source_path = os.path.join(source_dir, os.path.basename(source_arg))
    else:
        source_path = source_arg

    if not os.path.exists(source_path):
        sys.exit(f"ERROR: source file not found: {source_path}")

    if dest_dir:
        out_dir = dest_dir
    elif source_dir:
        out_dir = source_dir
    else:
        out_dir = os.path.dirname(os.path.abspath(source_arg))

    old_casename = os.path.splitext(os.path.basename(source_path))[0]
    dest_path = os.path.join(out_dir, new_casename + ".yaml")

    if os.path.exists(dest_path) and not force:
        sys.exit(f"ERROR: {dest_path} already exists. Use --force to overwrite.")

    with open(source_path) as f:
        content = f.read()

    n_replacements = content.count(old_casename)
    new_content = content.replace(old_casename, new_casename)

    os.makedirs(out_dir, exist_ok=True)

    with open(dest_path, "w") as f:
        f.write(new_content)

    print(f"  source : {source_path}")
    print(f"  dest   : {dest_path}")
    print(f"  '{old_casename}' -> '{new_casename}'  ({n_replacements} replacement(s))")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source",           help="Source YAML filename (stem or full path)")
    parser.add_argument("new_casenames",    nargs="*", metavar="new_casename",
                        help="One or more new casenames (e.g. exovolc_ben1_h11s10)")
    parser.add_argument("--names-file",     metavar="FILE", default=None,
                        help="Text file listing new casenames, one per line ('#' comments and blanks ignored)")
    parser.add_argument("--dir",            metavar="DIR", default=None,
                        help="Directory for both source and dest (e.g. experiments/exovolc_ben1)")
    parser.add_argument("--source-dir",     metavar="DIR", default=None,
                        help="Directory containing the source YAML (use with --dest-dir for cross-folder clones)")
    parser.add_argument("--dest-dir",       metavar="DIR", default=None,
                        help="Directory to write the new YAML(s) into (use with --source-dir for cross-folder clones)")
    parser.add_argument("--force",          action="store_true",
                        help="Overwrite existing output file(s)")
    args = parser.parse_args()

    if args.dir and (args.source_dir or args.dest_dir):
        sys.exit("ERROR: --dir cannot be combined with --source-dir/--dest-dir. Use one or the other.")

    source_dir = args.source_dir or args.dir
    dest_dir = args.dest_dir or args.dir

    new_casenames = list(args.new_casenames)
    if args.names_file:
        new_casenames += load_names_file(args.names_file)

    if not new_casenames:
        sys.exit("ERROR: no new casenames given. Provide positional casenames and/or --names-file.")

    n = len(new_casenames)
    failures = []
    for i, new_casename in enumerate(new_casenames, 1):
        if n > 1:
            print(f"[{i}/{n}] {new_casename}")
        try:
            spawn(args.source, new_casename, source_dir=source_dir, dest_dir=dest_dir, force=args.force)
        except SystemExit as e:
            print(f"  SKIPPED: {e}")
            failures.append(new_casename)

    if n > 1:
        print(f"\n{n - len(failures)}/{n} case(s) spawned successfully.")
        if failures:
            print(f"{len(failures)} failed/skipped: {', '.join(failures)}")
            sys.exit(1)


if __name__ == "__main__":
    main()
