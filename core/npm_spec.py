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

