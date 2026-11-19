"""The import audit of a Windows executable: every DLL it imports must be part of Windows itself."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from target_platform.provision import ToolError

# Windows 10 and later ship these, the Universal CRT among them.
SYSTEM_DLLS = frozenset({"advapi32.dll", "gdi32.dll", "imm32.dll", "kernel32.dll", "ole32.dll", "oleaut32.dll",
                         "setupapi.dll", "shell32.dll", "user32.dll", "version.dll", "winmm.dll", "ws2_32.dll",
                         "bcrypt.dll", "comdlg32.dll", "dwmapi.dll", "hid.dll", "ntdll.dll", "shlwapi.dll",
                         "uxtheme.dll", "dbghelp.dll", "cfgmgr32.dll", "dinput8.dll", "xinput1_4.dll",
                         "crypt32.dll", "iphlpapi.dll", "avrt.dll"})
UNIVERSAL_CRT = re.compile(r"^api-ms-win-crt-[a-z]+-l1-1-0\.dll$")
DLL_NAME = re.compile(r"^\s*DLL Name: (\S+)\s*$", re.MULTILINE)


class ForeignImport(Exception):
    """The executable imports a DLL Windows does not ship."""


def audit(executable: Path, toolchain: Path) -> list[str]:
    """The DLLs `executable` imports, read with the llvm-mingw root `toolchain`'s objdump; all must be Windows'."""
    objdump = toolchain / "bin" / "llvm-objdump"
    completed = subprocess.run([str(objdump), "-p", str(executable)], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise ToolError(f"llvm-objdump cannot read {executable}: {completed.stderr.strip()}")
    imports = sorted({name.lower() for name in DLL_NAME.findall(completed.stdout)})
    if not imports:
        raise ToolError(f"llvm-objdump listed no imports in {executable}")
    foreign = [name for name in imports if name not in SYSTEM_DLLS and not UNIVERSAL_CRT.match(name)]
    if foreign:
        raise ForeignImport(f"{executable.name} imports DLLs Windows does not ship: {', '.join(foreign)}")
    return imports
