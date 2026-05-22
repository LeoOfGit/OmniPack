r"""Patch Nuitka's SconsUtils.py to support MSVC_USE_SCRIPT.

This enables Nuitka+SCons to use a Visual Studio installation that is not
discoverable via registry or vswhere (e.g. VS Insiders, non-standard paths).

Usage:
    python patch_nuitka_msvc.py            # apply the patch
    python patch_nuitka_msvc.py --check    # check if already patched (exit code)
    python patch_nuitka_msvc.py --revert   # remove the patch
"""
import argparse
import os
import sys
import re
from importlib.util import find_spec

_MARKER = "    # Support MSVC_USE_SCRIPT from the process environment"

_PATCH_BLOCK = _MARKER + """ so that
    # non-standard Visual Studio installations (e.g. Insiders) can be
    # used without registry/vswhere detection.
    msvc_use_script = os.environ.get("MSVC_USE_SCRIPT")
    if msvc_use_script:
        args["MSVC_USE_SCRIPT"] = msvc_use_script
        # Monkey-patch msvc_exists to return True so SCons skips
        # registry-based version detection entirely.
        import SCons.Tool.MSCommon.vc  # pylint: disable=I0021,import-error
        import SCons.Tool.msvc  # pylint: disable=I0021,import-error

        SCons.Tool.msvc.msvc_exists = SCons.Tool.MSCommon.msvc_exists = (
            SCons.Tool.MSCommon.vc.msvc_exists
        ) = lambda *args, **kwargs: True

"""

_ORIGINAL_LINE = "tools = [\"default\"]"


def find_scons_utils():
    """Find Nuitka's SconsUtils.py path."""
    spec = find_spec("nuitka")
    if spec is None or spec.origin is None:
        print("Error: Nuitka is not installed in the current environment.")
        sys.exit(1)
    nuitka_dir = os.path.dirname(spec.origin)
    path = os.path.join(nuitka_dir, "build", "SconsUtils.py")
    if not os.path.isfile(path):
        print(f"Error: SconsUtils.py not found at {path}")
        sys.exit(1)
    return path


def is_patched(path):
    """Check whether the file already contains the patch marker."""
    with open(path, "r", encoding="utf-8") as f:
        return _MARKER in f.read()


def apply(path):
    """Apply the MSVC_USE_SCRIPT patch."""
    if is_patched(path):
        print("Already patched.")
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)

    # Find the line containing 'tools = ["default"]'
    insertion_point = None
    for i, line in enumerate(lines):
        if _ORIGINAL_LINE in line:
            insertion_point = i + 1  # insert *after* this line
            break

    if insertion_point is None:
        print(f"Error: could not locate '{_ORIGINAL_LINE}' in {path}")
        sys.exit(1)

    new_lines = lines[:insertion_point] + ["\n", _PATCH_BLOCK] + lines[insertion_point:]

    new_content = "".join(new_lines)

    # Verify the patch looks correct
    if _MARKER not in new_content:
        print("Error: patch content verification failed.")
        sys.exit(1)

    # Write back
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Invalidate .pyc cache
    import importlib.util
    pyc = importlib.util.cache_from_source(path)
    if os.path.isfile(pyc):
        os.remove(pyc)
        print(f"  Removed cache: {pyc}")
    
    # Also clean up the __pycache__ directory for any other version suffixes
    pycache_dir = os.path.join(os.path.dirname(path), "__pycache__")
    if os.path.isdir(pycache_dir):
        base = os.path.basename(path).replace(".py", "")
        for entry in os.listdir(pycache_dir):
            if entry.startswith(base):
                p = os.path.join(pycache_dir, entry)
                os.remove(p)
                print(f"  Removed cache: {p}")

    print(f"Patched: {path}")


def revert(path):
    """Remove the MSVC_USE_SCRIPT patch."""
    if not is_patched(path):
        print("Not patched.")
        return

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    marker_idx = None
    env_idx = None
    for i, line in enumerate(lines):
        if _MARKER in line:
            marker_idx = i
        if marker_idx is not None and "env = Environment(" in line:
            env_idx = i
            break

    if marker_idx is None or env_idx is None:
        print("Error: could not locate patch boundaries.")
        sys.exit(1)

    # Remove from the blank line before marker to the blank line before env = Environment
    # Walk back from marker_idx to find the preceding blank line
    start = marker_idx
    while start > 0 and lines[start - 1].strip() != "":
        start -= 1
    # Include the blank line separator if any
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1

    new_lines = lines[:start] + lines[env_idx:]
    new_content = "".join(new_lines)

    if _MARKER in new_content:
        print("Error: patch removal verification failed.")
        sys.exit(1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Invalidate .pyc cache
    pycache_dir = os.path.join(os.path.dirname(path), "__pycache__")
    if os.path.isdir(pycache_dir):
        base = os.path.basename(path).replace(".py", "")
        for entry in os.listdir(pycache_dir):
            if entry.startswith(base):
                p = os.path.join(pycache_dir, entry)
                os.remove(p)
                print(f"  Removed cache: {p}")

    print(f"Reverted: {path}")


def main():
    parser = argparse.ArgumentParser(description="Patch/Revert Nuitka SconsUtils for MSVC_USE_SCRIPT")
    parser.add_argument("--check", action="store_true", help="Check if already patched (exit 0=yes, 1=no)")
    parser.add_argument("--revert", action="store_true", help="Remove the patch")
    args = parser.parse_args()

    path = find_scons_utils()

    if args.check:
        patched = is_patched(path)
        print(f"Patched: {patched}")
        sys.exit(0 if patched else 1)
    elif args.revert:
        revert(path)
    else:
        apply(path)


if __name__ == "__main__":
    main()
