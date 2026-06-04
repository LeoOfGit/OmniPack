"""
Helpers for extracting package names from pip requirement specs.
"""

from __future__ import annotations

import re


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_DIRECT_REF_SEP = re.compile(r"\s+@\s+")


def canonicalize_pip_name(name: str) -> str:
    """Canonicalize a pip distribution name for matching."""
    return re.sub(r"[-_.]+", "-", str(name or "").strip()).lower()


def extract_pip_requirement_name(spec: str) -> str:
    """
    Extract a canonical distribution name from a pip requirement-like string.

    Returns an empty string for raw URLs, local paths, editable installs without
    an explicit project name, or any spec that cannot be safely mapped to a
    single installed distribution.
    """
    raw = str(spec or "").strip()
    if not raw:
        return ""

    for mod_name in ("packaging.requirements", "pip._vendor.packaging.requirements"):
        try:
            module = __import__(mod_name, fromlist=["Requirement"])
            requirement = module.Requirement(raw)
            return canonicalize_pip_name(requirement.name)
        except Exception:
            pass

    lowered = raw.lower()
    if lowered.startswith("-e ") or lowered.startswith("--editable "):
        editable_target = raw.split(None, 1)[1].strip() if " " in raw else ""
        return extract_pip_requirement_name(editable_target)

    if lowered.startswith(("git+", "http://", "https://", "file://")):
        return ""

    if raw.startswith((".", "/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", raw):
        return ""

    candidate = raw.split(";", 1)[0].strip()
    if not candidate:
        return ""

    if _DIRECT_REF_SEP.search(candidate):
        candidate = _DIRECT_REF_SEP.split(candidate, 1)[0].strip()

    if "[" in candidate:
        candidate = candidate.split("[", 1)[0].strip()

    match = _NAME_RE.match(candidate)
    if not match:
        return ""

    return canonicalize_pip_name(match.group(0))
