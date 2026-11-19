"""The release platforms a product builds for beside the Linux host: their toolchain and target libraries.

Windows x86-64 cross-compiles with llvm-mingw; macOS builds natively for the Mac's own architecture; Android
arm64-v8a cross-compiles with the pinned NDK against the shared android-port native prefix (SDL3, SDL3_image,
FreeType, fmt). Each platform's libraries (libraries.json) land under the caller's dependency root, keyed by
the pins and library set that shape them, and are reused by every build tree. MoltenVK, which a macOS
package carries, is pinned here too.
"""

from __future__ import annotations

import hashlib
import platform as host_platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from dataclasses import dataclass

from target_platform import libraries as target_libraries

REPOSITORY = Path(__file__).resolve().parents[1]
WINDOWS_TOOLCHAIN_FILE = REPOSITORY / "cmake" / "toolchains" / "llvm-mingw-x86_64.cmake"
WINDOWS_TRIPLE = "x86_64-w64-mingw32"
LLVM_MINGW_RELEASE = "20260922"
LLVM_MINGW_NAME = f"llvm-mingw-{LLVM_MINGW_RELEASE}-ucrt-ubuntu-22.04-x86_64"
LLVM_MINGW_URL = (f"https://github.com/mstorsjo/llvm-mingw/releases/download/{LLVM_MINGW_RELEASE}/"
                  f"{LLVM_MINGW_NAME}.tar.xz")
LLVM_MINGW_SHA256 = "bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21"
# The oldest macOS the package runs on: std::format of floating point needs 13.3.
MACOS_DEPLOYMENT_TARGET = "13.3"
# Written into a pinned library prefix; a macOS host configure refuses an SDL3 from a prefix without it.
PINNED_PREFIX_STAMP = "target-platform-libraries.json"
MOLTENVK_RELEASE = "v1.4.2"
MOLTENVK_URL = f"https://github.com/KhronosGroup/MoltenVK/releases/download/{MOLTENVK_RELEASE}/MoltenVK-macos.tar"
MOLTENVK_SHA256 = "f95765a6229cb7b915990a2890ce12ebe36a730b021545d3d52ae69ce4c4024e"
ANDROID_NDK_VERSION = "28.2.13676358"
ANDROID_ABI = "arm64-v8a"
# SDL_GPU draws through Vulkan, which Android has from 7.0 (API 24).
ANDROID_API = 24
ANDROID_PORT_REPOSITORY = "https://github.com/SomeoneIsWorking/android-port.git"
PLATFORMS = ("windows", "macos", "android")


class ToolError(Exception):
    """A platform could not be provisioned."""


@dataclass(frozen=True)
class Provisioned:
    definitions: list[str]
    prefix: Path


def dependency_root(environment: Mapping[str, str], project: str) -> Path:
    """``<PROJECT>_DEPENDENCY_ROOT``, else ``<cache>/<project>/deps``."""
    variable = f"{project.upper().replace('-', '_')}_DEPENDENCY_ROOT"
    if environment.get(variable):
        return Path(environment[variable])
    if environment.get("XDG_CACHE_HOME"):
        return Path(environment["XDG_CACHE_HOME"]) / project / "deps"
    return Path.home() / ".cache" / project / "deps"


def _download(url: str, sha256: str, root: Path, name: str) -> Path:
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / name
    if not archive.is_file():
        partial = archive.with_suffix(".part")
        with urllib.request.urlopen(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(archive)
    actual = target_libraries.sha256_of(archive)
    if actual != sha256:
        raise ToolError(f"{url}: sha256 {actual}, pinned {sha256}")
    return archive


def extracted(url: str, sha256: str, root: Path, directory: str, marker: Path) -> Path:
    """Extract a pinned tar or zip archive into ``root`` once; ``marker`` (relative to ``root / directory``) proves it."""
    if (root / directory / marker).exists():
        return root / directory
    archive = _download(url, sha256, root, url.rsplit("/", 1)[1])
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            source.extractall(root)
    else:
        with tarfile.open(archive) as source:
            source.extractall(root, filter="data")
    archive.unlink()
    if not (root / directory / marker).exists():
        raise ToolError(f"{url} did not hold {directory}/{marker}")
    return root / directory


def llvm_mingw(root: Path) -> Path:
    return extracted(LLVM_MINGW_URL, LLVM_MINGW_SHA256, root, LLVM_MINGW_NAME,
                      Path("bin") / f"{WINDOWS_TRIPLE}-clang")


def moltenvk(root: Path) -> Path:
    """The pinned MoltenVK dylib a macOS package carries."""
    library = Path("MoltenVK") / "dynamic" / "dylib" / "macOS" / "libMoltenVK.dylib"
    return extracted(MOLTENVK_URL, MOLTENVK_SHA256, root / f"moltenvk-{MOLTENVK_RELEASE}", "MoltenVK",
                      library) / library


def architecture(platform: str) -> str:
    """The CPU a platform build targets: x86-64 for Windows, the building Mac's own for macOS, arm64 for Android."""
    if platform == "macos":
        return "arm64" if host_platform.machine() == "arm64" else "x86_64"
    if platform == "android":
        return "arm64"
    return "x86_64"


def android_ndk(environment: Mapping[str, str]) -> Path:
    """The pinned NDK inside the SDK ANDROID_HOME (or ANDROID_SDK_ROOT) names."""
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if environment.get(variable):
            ndk = Path(environment[variable]) / "ndk" / ANDROID_NDK_VERSION
            if (ndk / "build" / "cmake" / "android.toolchain.cmake").is_file():
                return ndk
    raise ToolError(f"Android NDK {ANDROID_NDK_VERSION} is missing: set ANDROID_HOME to an SDK and run "
                    f"`sdkmanager \"ndk;{ANDROID_NDK_VERSION}\"`")


def android_port_checkout(root: Path, environment: Mapping[str, str]) -> Path:
    """The workspace's shared/android-port checkout, else a clone of its main under the dependency root."""
    candidates = [Path(environment["SHARED_DIR"]) / "android-port"] if environment.get("SHARED_DIR") else []
    candidates += [REPOSITORY.parent / "android-port", REPOSITORY.parents[2] / "shared" / "android-port"]
    for candidate in candidates:
        if (candidate / "tools" / "android_port.py").is_file():
            return candidate
    clone = root / "android-port"
    if not (clone / ".git").is_dir():
        subprocess.run(["git", "clone", "--quiet", ANDROID_PORT_REPOSITORY, str(clone)], check=True)
    return clone


def android_prefix(root: Path, environment: Mapping[str, str], ndk: Path) -> Path:
    """The android-port native prefix for the pinned NDK, API and ABI, built by android-port when missing."""
    prefix = root / "android" / f"ndk-{ANDROID_NDK_VERSION}" / f"android-{ANDROID_API}" / ANDROID_ABI
    checkout = android_port_checkout(root, environment)
    subprocess.run(["uv", "run", "--directory", str(checkout), "--frozen", "python", "tools/android_port.py",
                    "build-native-deps", "--ndk", str(ndk), "--abi", ANDROID_ABI, "--api", str(ANDROID_API),
                    "--prefix", str(prefix)], check=True)
    return prefix


def _keyed(root: Path, platform: str, kind: str, *parts: bytes) -> Path:
    digest = hashlib.sha256(platform.encode())
    for part in parts:
        digest.update(part)
    return root / f"{platform}-{architecture(platform)}" / kind / digest.hexdigest()[:16]


def provision(platform: str, root: Path, environment: Mapping[str, str],
              names: Sequence[str] | None = None) -> Provisioned:
    """Build the platform's libraries (all pinned, or those `names` lists) when missing; return what uses them."""
    if platform not in PLATFORMS:
        raise ToolError(f"no target platform {platform!r}; known: {', '.join(PLATFORMS)}")
    if platform == "android":
        return _provision_android(root, environment)
    if platform == "windows":
        toolchain = llvm_mingw(root)
        library_arguments = [f"-DCMAKE_TOOLCHAIN_FILE={WINDOWS_TOOLCHAIN_FILE}", f"-DLLVM_MINGW_ROOT={toolchain}"]
        shaping = (LLVM_MINGW_NAME.encode(), WINDOWS_TOOLCHAIN_FILE.read_bytes())
    else:
        arch = architecture(platform)
        library_arguments = [f"-DCMAKE_OSX_DEPLOYMENT_TARGET={MACOS_DEPLOYMENT_TARGET}", f"-DCMAKE_OSX_ARCHITECTURES={arch}"]
        shaping = (MACOS_DEPLOYMENT_TARGET.encode(), arch.encode())
    selection = b"" if names is None else ",".join(sorted(set(names))).encode()
    libraries = _keyed(root, platform, "libraries", *shaping, target_libraries.PINS.read_bytes(),
                       Path(target_libraries.__file__).read_bytes(), selection)
    prefix = libraries / "prefix"
    try:
        if not (libraries / "complete").is_file():
            target_libraries.build_libraries(platform, prefix, libraries / "work",
                                             [*library_arguments, f"-DCMAKE_FIND_ROOT_PATH={prefix}"], names)
            shutil.rmtree(libraries / "work", ignore_errors=True)
            (libraries / "complete").touch()
    except target_libraries.Refused as error:
        raise ToolError(f"{platform} target dependencies: {error}") from error
    # Lets a consumer's macOS host configure tell the pinned SDL3 from another one.
    stamp = prefix / PINNED_PREFIX_STAMP
    if not stamp.is_file():
        stamp.write_bytes(target_libraries.PINS.read_bytes())
    definitions = [*library_arguments, f"-DCMAKE_PREFIX_PATH={prefix}"]
    if platform == "windows":
        definitions += [f"-DCMAKE_FIND_ROOT_PATH={prefix}"]
        if (prefix / "lib" / "libzs.a").is_file():
            # zlib's static MinGW name, which FindZLIB does not search.
            definitions += [f"-DZLIB_LIBRARY={prefix / 'lib' / 'libzs.a'}"]
    return Provisioned(definitions, prefix)


def _provision_android(root: Path, environment: Mapping[str, str]) -> Provisioned:
    ndk = android_ndk(environment)
    prefix = android_prefix(root, environment, ndk)
    return Provisioned([f"-DCMAKE_TOOLCHAIN_FILE={ndk / 'build' / 'cmake' / 'android.toolchain.cmake'}",
            f"-DANDROID_ABI={ANDROID_ABI}", f"-DANDROID_PLATFORM=android-{ANDROID_API}", "-DANDROID_STL=c++_shared",
            f"-DCMAKE_PREFIX_PATH={prefix}", f"-DCMAKE_FIND_ROOT_PATH={prefix}",
            # SDL_image's installed Findwebp leaves libwebp's sharpyuv to this hook.
            f"-Dwebp_LINK_LIBRARIES={prefix / 'lib' / 'libsharpyuv.a'}"], prefix)
