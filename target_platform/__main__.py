"""Provision a release platform's toolchain and pinned libraries and print the CMake definitions that use them.

    python -m target_platform provision windows|macos|android [--root DIR] [--library NAME...]

Prints one definition per line (the toolchain file, LLVM_MINGW_ROOT, the library prefix), ready to pass to a
CMake configure. A missing toolchain or library prefix is downloaded (checksummed) and built first; a later
call with the same pins only prints. The root defaults to TARGET_PLATFORM_DEPENDENCY_ROOT, else
<cache>/target-platform/deps.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from target_platform import provision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m target_platform", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    provide = commands.add_parser("provision", help="build what is missing and print the CMake definitions")
    provide.add_argument("platform", choices=provision.PLATFORMS)
    provide.add_argument("--root", type=Path, help="dependency root (default: TARGET_PLATFORM_DEPENDENCY_ROOT "
                                                   "or the user cache)")
    provide.add_argument("--library", action="append",
                         help="build only this pinned library (repeatable; default: every one for the platform)")
    args = parser.parse_args(argv)
    root = args.root or provision.dependency_root(os.environ, "target-platform")
    try:
        result = provision.provision(args.platform, root.resolve(), os.environ, args.library)
    except provision.ToolError as error:
        print(f"[target-platform] REFUSED: {error}", file=sys.stderr)
        return 2
    print("\n".join(result.definitions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
