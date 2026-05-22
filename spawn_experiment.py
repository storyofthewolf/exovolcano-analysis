#!/usr/bin/env python3
"""
spawn_experiment.py - Clone an experiment YAML with a new casename.

Replaces all occurrences of the source casename (filename stem) with
new_casename in both the filename and file content.

Usage:
    python spawn_experiment.py <source.yaml> <new_casename> [--dir DIR] [--force]

Examples:
    # source and dest both in experiments/exovolc_ben1/
    python spawn_experiment.py exovolc_ben1_h10s9.yaml exovolc_ben1_h11s10 --dir experiments/exovolc_ben1

    # full paths, no --dir needed
    python spawn_experiment.py experiments/exovolc_ben1/exovolc_ben1_h10s9.yaml exovolc_ben1_h11s10
"""

import argparse
import os
import sys


def spawn(source_arg, new_casename, dest_dir=None, force=False):
    # If --dir given, it is the base for both source and dest
    if dest_dir:
        source_path = os.path.join(dest_dir, os.path.basename(source_arg))
        out_dir = dest_dir
    else:
        source_path = source_arg
        out_dir = os.path.dirname(os.path.abspath(source_arg))

    if not os.path.exists(source_path):
        sys.exit(f"ERROR: source file not found: {source_path}")

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
    parser.add_argument("source",       help="Source YAML filename (stem or full path)")
    parser.add_argument("new_casename", help="New casename (e.g. exovolc_ben1_h11s10)")
    parser.add_argument("--dir",        metavar="DIR", default=None,
                        help="Directory for both source and dest (e.g. experiments/exovolc_ben1)")
    parser.add_argument("--force",      action="store_true",
                        help="Overwrite existing output file")
    args = parser.parse_args()

    spawn(args.source, args.new_casename, dest_dir=args.dir, force=args.force)


if __name__ == "__main__":
    main()
