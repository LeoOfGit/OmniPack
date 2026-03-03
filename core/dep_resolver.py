"""
dep_resolver.py — Dependency Graph Resolver for OmniPack

Resolves package dependency relationships by running a lightweight
`importlib.metadata` scan inside the target Python environment via subprocess.
Returns a structured JSON dependency graph.
"""
import os
import json
import subprocess
import textwrap
import re
from typing import Dict, List, Optional
from core.manager_base import Package, DepRequirement


# This script is injected into target Python environments via subprocess.
# It uses only stdlib modules (importlib.metadata, json, re, sys).
_RESOLVER_SCRIPT = textwrap.dedent(r'''
import importlib.metadata
import json
import re
import sys

def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()

def build_graph():
    all_dists = list(importlib.metadata.distributions())
    installed = {}

    for dist in all_dists:
        name = dist.metadata['Name']
        version = dist.metadata['Version']
        norm = normalize(name)
        if norm in installed:
            continue  # Skip duplicates
        installed[norm] = {
            'name': name,
            'version': version,
            'requires': [],
            'required_by': [],
        }

    for dist in all_dists:
        name = dist.metadata['Name']
        norm = normalize(name)
        if norm not in installed:
            continue
        raw_requires = dist.metadata.get_all('Requires-Dist') or []

        grouped_requires = {}
        for req_str in raw_requires:
            # Skip extras-only dependencies
            if re.search(r'extra\s*==', req_str):
                continue

            dep_name = re.split(r'[\s;>=<!\[\(]', req_str.strip())[0]
            dep_norm = normalize(dep_name)

            # Extract version constraint
            version_match = re.search(r'([\(]?[>=<!=~]+[\d\w.*,>=<!=~ ]+[\)]?)', req_str)
            constraint = version_match.group(1).strip() if version_match else ''

            if dep_norm not in grouped_requires:
                grouped_requires[dep_norm] = {
                    'name': dep_name,
                    'constraints': []
                }
            if constraint:
                grouped_requires[dep_norm]['constraints'].append(constraint)

        for dep_norm, data in grouped_requires.items():
            is_installed = dep_norm in installed
            combined_constraint = ', '.join(data['constraints'])

            installed[norm]['requires'].append({
                'name': data['name'],
                'norm_name': dep_norm,
                'constraint': combined_constraint,
                'is_installed': is_installed,
            })

            if is_installed:
                installed[dep_norm]['required_by'].append(norm)

    print(json.dumps(installed, ensure_ascii=False))

build_graph()
''')


def resolve_dependencies_subprocess(py_exe: str) -> Optional[Dict]:
    """
    Run dependency resolution in the target Python environment.
    Returns a dict: {norm_name: {name, version, requires: [...], required_by: [...]}}
    Returns None on failure.
    """
    try:
        result = subprocess.run(
            [py_exe, "-c", _RESOLVER_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return None


def merge_dependency_info(packages: List[Package], dep_data: Dict) -> List[Package]:
    """
    Merge dependency resolution data into existing Package objects.
    This enriches the flat package list with tree structure information.

    Returns the same list of packages, now with dependency fields populated,
    plus any "ghost" (missing) dependencies added.
    """
    if not dep_data:
        return packages

    # Build lookup from existing packages
    pkg_map: Dict[str, Package] = {}
    for pkg in packages:
        pkg_map[pkg.norm_name] = pkg

    # Enrich existing packages with dependency info
    for norm_name, info in dep_data.items():
        if norm_name not in pkg_map:
            continue

        pkg = pkg_map[norm_name]

        # Set requires
        pkg.requires = [
            DepRequirement(
                name=dep['name'],
                norm_name=dep['norm_name'],
                constraint=dep.get('constraint', ''),
                is_installed=dep.get('is_installed', True),
            )
            for dep in info.get('requires', [])
        ]

        # Set required_by
        pkg.required_by = info.get('required_by', [])

        # Determine if top-level
        pkg.is_top_level = len(pkg.required_by) == 0

    # Create ghost packages for missing dependencies
    all_norm_names = set(pkg_map.keys())
    ghost_packages = []

    for norm_name, info in dep_data.items():
        if norm_name not in pkg_map:
            continue
        for dep in info.get('requires', []):
            dep_norm = dep['norm_name']
            if not dep.get('is_installed', True) and dep_norm not in all_norm_names:
                ghost = Package(
                    name=dep['name'],
                    version="",
                    norm_name=dep_norm,
                    is_missing=True,
                    is_top_level=False,
                    version_constraint=dep.get('constraint', ''),
                )
                ghost_packages.append(ghost)
                all_norm_names.add(dep_norm)
                pkg_map[dep_norm] = ghost

    packages.extend(ghost_packages)

    # Build dep_graph dict for the Environment
    dep_graph = {pkg.norm_name: pkg for pkg in packages}

    return packages, dep_graph
