"""
Helpers for parsing npm package specs with optional dist-tags.

Examples:
- "eslint" -> ("eslint", None)
- "eslint@beta" -> ("eslint", "beta")
- "@scope/cli" -> ("@scope/cli", None)
- "@scope/cli@rc" -> ("@scope/cli", "rc")
"""

from __future__ import annotations

from typing import Optional, Tuple


def split_npm_spec(spec: str) -> Tuple[str, Optional[str]]:
    """Split npm package spec into package name and tag/version."""
    raw = (spec or "").strip()
    if not raw:
        return "", None

    if raw.startswith("@"):
        slash_idx = raw.find("/")
        last_at = raw.rfind("@")
        if slash_idx != -1 and last_at > slash_idx:
            name = raw[:last_at]
            tag = raw[last_at + 1 :].strip()
            if name and tag:
                return name, tag
        return raw, None

    if "@" in raw:
        name, tag = raw.rsplit("@", 1)
        name = name.strip()
        tag = tag.strip()
        if name and tag:
            return name, tag

    return raw, None


def has_explicit_tag(spec: str) -> bool:
    """Whether spec already includes @tag/@version suffix."""
    _, tag = split_npm_spec(spec)
    return bool(tag)


def extract_npm_package_name(spec: str) -> str:
    """
    Extract the installed package name from an npm spec.

    Returns an empty string for local paths, workspace/file/git installs, or
    any spec that cannot be safely mapped back to a single package entry.
    """
    raw = (spec or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered in {".", ".."}:
        return ""

    if raw.startswith(("./", "../", ".\\", "..\\", "/", "\\")):
        return ""

    if lowered.startswith(("file:", "git+", "git://", "http://", "https://", "github:", "workspace:", "link:")):
        return ""

    if "@npm:" in lowered:
        raw = raw[:lowered.find("@npm:")]

    name, _tag = split_npm_spec(raw)
    name = (name or "").strip()
    if not name or any(ch.isspace() for ch in name):
        return ""

    if name.startswith("@"):
        slash_idx = name.find("/")
        if slash_idx <= 1 or slash_idx == len(name) - 1:
            return ""

    return name.lower()
