# target-platform

Pinned toolchains and target libraries for building a product on its release platforms from a Linux host:
Linux for the host's own architecture with the host's compiler, Windows x86-64 with
[llvm-mingw](https://github.com/mstorsjo/llvm-mingw) (Clang, libc++, UCRT, static), macOS for the Mac's own
architecture, Android arm64-v8a with the pinned NDK and `android-port`'s native prefix. SDL's Linux build leaves out
the XScreenSaver extension: SDL inhibits the screensaver over D-Bus first.

| file | owns |
|---|---|
| `target_platform/provision.py` | the toolchain pins, the dependency root, keyed library prefixes, the CMake definitions |
| `target_platform/libraries.py` | building `libraries.json`'s pinned, checksummed sources into a prefix (stdlib only, so a container image can run it alone) |
| `target_platform/windows_imports.py` | `audit(executable, toolchain)`: the DLLs a Windows executable imports, refused unless Windows ships them all (`SYSTEM_DLLS`, the Universal CRT) |
| `target_platform/libraries.json` | the library pins: url, sha256, platforms, CMake options |
| `cmake/toolchains/llvm-mingw-x86_64.cmake` | the Windows toolchain file |

## Use

```sh
uv run --project <this checkout> --frozen python -m target_platform provision windows [--library SDL3 ...]
```

prints one CMake definition per line (`CMAKE_TOOLCHAIN_FILE`, `LLVM_MINGW_ROOT`, `CMAKE_PREFIX_PATH`,
`CMAKE_FIND_ROOT_PATH`, ...). Missing pieces are downloaded, checksummed and built first. A prefix lives under
the dependency root (`--root`, else `TARGET_PLATFORM_DEPENDENCY_ROOT`, else `~/.cache/target-platform/deps`),
keyed by the toolchain, the pins, the builder and the library selection, so every build tree with the same
inputs reuses it. Python callers import `target_platform.provision` and pass their own root
(`provision(platform, root, environment, names)`).

A new library is an entry in `libraries.json`: a release tarball pinned by sha256, static on Windows and macOS.

Built with AI assistance (Claude and other LLMs).

MIT licence.
