#!/usr/bin/env python3
"""Build the libraries a packaged product links, from pinned and checksummed sources.

    libraries.py libraries --platform linux|windows|macos --prefix DIR --work DIR [--library NAME...] [-- CMAKE_ARG...]

`libraries` builds the entries of libraries.json for the platform (all, or those named) into one prefix,
passing the trailing CMake arguments (a toolchain file) to each. Stdlib only: a container image runs this
file before any project environment exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

PINS = Path(__file__).resolve().with_name("libraries.json")


class Refused(Exception):
    pass


def run(command: Sequence[object], cwd: Path | None = None, environment: Mapping[str, str] | None = None) -> None:
    arguments = [str(part) for part in command]
    print(f"[target-platform] {' '.join(arguments)}", flush=True)
    if subprocess.run(arguments, cwd=cwd, env=environment, check=False).returncode != 0:
        raise Refused(f"{arguments[0]} failed")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, sha256: str, downloads: Path) -> Path:
    downloads.mkdir(parents=True, exist_ok=True)
    path = downloads / f"{sha256[:16]}.tar.gz"
    if not path.is_file():
        partial = path.with_suffix(".part")
        with urllib.request.urlopen(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(path)
    actual = sha256_of(path)
    if actual != sha256:
        raise Refused(f"{url}: sha256 {actual}, pinned {sha256}")
    return path


def unpack(archive: Path, destination: Path) -> Path:
    """Extract a single-top-directory archive into a fresh ``destination`` and return that directory."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise Refused(f"{archive} does not hold one top directory")
    return children[0]


def libraries(platform: str, names: Sequence[str] | None = None) -> list[dict]:
    """The pinned entries for `platform`, in pin order: all, or exactly those `names` lists."""
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    known = {entry["name"] for entry in pins["libraries"]}
    unknown = sorted(set(names or ()) - known)
    if unknown:
        raise Refused(f"no pinned library {', '.join(unknown)}; known: {', '.join(sorted(known))}")
    return [entry for entry in pins["libraries"]
            if platform in entry["platforms"] and (names is None or entry["name"] in names)]


def build_libraries(platform: str, prefix: Path, work: Path, cmake_arguments: Sequence[str],
                    names: Sequence[str] | None = None) -> None:
    prefix.mkdir(parents=True, exist_ok=True)
    for entry in libraries(platform, names):
        source = unpack(fetch(entry["url"], entry["sha256"], work / "downloads"), work / "src" / entry["name"])
        build = work / "build" / entry["name"]
        if build.exists():
            shutil.rmtree(build)
        options = [*entry["options"].get("all", []), *entry["options"].get(platform, [])]
        run(["cmake", "-S", source, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             "-DCMAKE_INSTALL_LIBDIR=lib", f"-DCMAKE_INSTALL_PREFIX={prefix}", f"-DCMAKE_PREFIX_PATH={prefix}",
             *cmake_arguments, *options])
        run(["cmake", "--build", build])
        run(["cmake", "--install", build])
        shutil.rmtree(build)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    libs = commands.add_parser("libraries")
    libs.add_argument("--platform", choices=("linux", "windows", "macos"), required=True)
    libs.add_argument("--prefix", type=Path, required=True)
    libs.add_argument("--work", type=Path, required=True)
    libs.add_argument("--library", action="append", help="build only this pinned library (repeatable)")
    libs.add_argument("cmake_arguments", nargs="*")
    args = parser.parse_args(argv)
    try:
        build_libraries(args.platform, args.prefix.resolve(), args.work.resolve(), args.cmake_arguments, args.library)
    except Refused as error:
        print(f"[target-platform] REFUSED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
