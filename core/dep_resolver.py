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
import ast
import json
import os
import platform
import re
import sys

def normalize(name):
    if name is None:
        return ''
    return re.sub(r'[-_.]+', '-', str(name)).lower()

def get_dist_name(dist):
    name = None
    try:
        name = dist.metadata.get('Name')
    except Exception:
        name = None
    if not name:
        name = getattr(dist, 'name', None)
    if not name:
        return None
    return str(name).strip()

def get_dist_version(dist):
    version = None
    try:
        version = dist.metadata.get('Version')
    except Exception:
        version = None
    if not version:
        version = getattr(dist, 'version', '')
    return str(version or '').strip()

def split_requirement_marker(req_text):
    if ';' not in req_text:
        return req_text.strip(), ''
    requirement_part, marker_part = req_text.split(';', 1)
    return requirement_part.strip(), marker_part.strip()

def _marker_environment():
    impl = getattr(sys, 'implementation', None)
    impl_version = getattr(impl, 'version', None)
    if impl_version is not None:
        version_parts = [str(getattr(impl_version, attr, 0)) for attr in ('major', 'minor', 'micro')]
        implementation_version = '.'.join(version_parts)
    else:
        implementation_version = ''
    return {
        'python_version': '.'.join(str(x) for x in sys.version_info[:2]),
        'python_full_version': '.'.join(str(x) for x in sys.version_info[:3]),
        'os_name': os.name,
        'sys_platform': sys.platform,
        'platform_system': platform.system(),
        'platform_machine': platform.machine(),
        'platform_release': platform.release(),
        'platform_version': platform.version(),
        'platform_python_implementation': platform.python_implementation(),
        'implementation_name': getattr(impl, 'name', ''),
        'implementation_version': implementation_version,
    }

_MARKER_ENV = _marker_environment()

def _tokenize_marker(marker):
    pattern = re.compile(
        r"""
        \s*(
            not\s+in
            |==|!=|<=|>=|<|>
            |\(|\)
            |\band\b|\bor\b|\bin\b
            |"[^"\\]*(?:\\.[^"\\]*)*"
            |'[^'\\]*(?:\\.[^'\\]*)*'
            |[A-Za-z_][A-Za-z0-9_.-]*
        )
        """,
        re.VERBOSE,
    )
    tokens = []
    pos = 0
    while pos < len(marker):
        match = pattern.match(marker, pos)
        if not match:
            raise ValueError(f'Unsupported marker syntax: {marker!r}')
        token = re.sub(r'\s+', ' ', match.group(1).strip())
        tokens.append(token)
        pos = match.end()
    return tokens

def _coerce_marker_token(token):
    if token in _MARKER_ENV:
        return str(_MARKER_ENV[token] or ''), True
    if token[:1] in {'"', "'"}:
        try:
            return str(ast.literal_eval(token)), False
        except Exception:
            return token[1:-1], False
    return str(token), False

def _marker_version_key(value):
    parts = []
    for piece in re.split(r'([0-9]+)', str(value or '')):
        if not piece:
            continue
        parts.append(int(piece) if piece.isdigit() else piece.lower())
    return parts

def _compare_marker_values(left, op, right, version_like=False):
    if op == 'in':
        return str(left) in str(right)
    if op == 'not in':
        return str(left) not in str(right)

    if version_like:
        left_cmp = _marker_version_key(left)
        right_cmp = _marker_version_key(right)
    else:
        left_cmp = str(left).lower()
        right_cmp = str(right).lower()

    if op == '==':
        return left_cmp == right_cmp
    if op == '!=':
        return left_cmp != right_cmp
    if op == '<':
        return left_cmp < right_cmp
    if op == '<=':
        return left_cmp <= right_cmp
    if op == '>':
        return left_cmp > right_cmp
    if op == '>=':
        return left_cmp >= right_cmp
    raise ValueError(f'Unsupported marker operator: {op}')

def _compare_versions(left, right):
    def _parts(value):
        nums = [int(x) for x in re.findall(r'\d+', str(value or ''))]
        return nums[:4]

    a = _parts(left)
    b = _parts(right)
    max_len = max(len(a), len(b), 1)
    a.extend([0] * (max_len - len(a)))
    b.extend([0] * (max_len - len(b)))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0

def _split_constraint_specifiers(constraint):
    raw = str(constraint or '').strip()
    if not raw:
        return []
    if raw.startswith('(') and raw.endswith(')'):
        raw = raw[1:-1].strip()
    return [part.strip() for part in raw.split(',') if part.strip()]

def _pick_stronger_lower(current, candidate):
    if current is None:
        return candidate
    current_op, current_ver = current
    candidate_op, candidate_ver = candidate
    cmp = _compare_versions(candidate_ver, current_ver)
    if cmp > 0:
        return candidate
    if cmp < 0:
        return current
    if candidate_op == '>' and current_op == '>=':
        return candidate
    return current

def _pick_stronger_upper(current, candidate):
    if current is None:
        return candidate
    current_op, current_ver = current
    candidate_op, candidate_ver = candidate
    cmp = _compare_versions(candidate_ver, current_ver)
    if cmp < 0:
        return candidate
    if cmp > 0:
        return current
    if candidate_op == '<' and current_op == '<=':
        return candidate
    return current

def simplify_constraint(constraint):
    specifiers = _split_constraint_specifiers(constraint)
    if len(specifiers) <= 1:
        return ', '.join(specifiers)

    lower = None
    upper = None
    equals = []
    not_equals = []
    others = []
    seen_not_equals = set()
    seen_others = set()

    for spec in specifiers:
        match = re.match(r'(~=|>=|<=|!=|==|>|<)\s*([\d\w.+-]+)', spec)
        if not match:
            if spec not in seen_others:
                others.append(spec)
                seen_others.add(spec)
            continue

        op, ver = match.groups()
        item = (op, ver)
        if op in ('>=', '>'):
            lower = _pick_stronger_lower(lower, item)
        elif op in ('<=', '<'):
            upper = _pick_stronger_upper(upper, item)
        elif op == '==':
            if item not in equals:
                equals.append(item)
        elif op == '!=':
            if item not in seen_not_equals:
                not_equals.append(item)
                seen_not_equals.add(item)
        else:
            if spec not in seen_others:
                others.append(spec)
                seen_others.add(spec)

    simplified = []
    if lower:
        simplified.append(f'{lower[0]}{lower[1]}')
    if upper:
        simplified.append(f'{upper[0]}{upper[1]}')
    for op, ver in equals:
        simplified.append(f'{op}{ver}')
    for op, ver in not_equals:
        simplified.append(f'{op}{ver}')
    simplified.extend(others)

    return ', '.join(simplified)

def _evaluate_marker_fallback(marker):
    tokens = _tokenize_marker(marker)
    idx = 0

    def parse_or():
        nonlocal idx
        value = parse_and()
        while idx < len(tokens) and tokens[idx] == 'or':
            idx += 1
            value = value or parse_and()
        return value

    def parse_and():
        nonlocal idx
        value = parse_atom()
        while idx < len(tokens) and tokens[idx] == 'and':
            idx += 1
            value = value and parse_atom()
        return value

    def parse_atom():
        nonlocal idx
        if idx >= len(tokens):
            raise ValueError('Unexpected end of marker')
        if tokens[idx] == '(':
            idx += 1
            value = parse_or()
            if idx >= len(tokens) or tokens[idx] != ')':
                raise ValueError('Unclosed marker parenthesis')
            idx += 1
            return value
        return parse_comparison()

    def parse_comparison():
        nonlocal idx
        left_token = tokens[idx]
        idx += 1
        if idx >= len(tokens):
            raise ValueError('Missing marker operator')
        op = tokens[idx]
        idx += 1
        if idx >= len(tokens):
            raise ValueError('Missing marker value')
        right_token = tokens[idx]
        idx += 1

        left_value, left_is_env = _coerce_marker_token(left_token)
        right_value, right_is_env = _coerce_marker_token(right_token)
        version_like = (
            left_token in {'python_version', 'python_full_version', 'implementation_version'}
            or right_token in {'python_version', 'python_full_version', 'implementation_version'}
        )
        if left_is_env and not right_is_env and right_token not in _MARKER_ENV and right_token[:1] not in {'"', "'"}:
            right_value = right_token
        return _compare_marker_values(left_value, op, right_value, version_like=version_like)

    result = parse_or()
    if idx != len(tokens):
        raise ValueError('Trailing marker tokens')
    return bool(result)

def marker_applies(marker):
    marker = str(marker or '').strip()
    if not marker:
        return True
    for mod_name in ('packaging.markers', 'pip._vendor.packaging.markers'):
        try:
            module = __import__(mod_name, fromlist=['Marker'])
            return bool(module.Marker(marker).evaluate(environment=dict(_MARKER_ENV)))
        except Exception:
            continue
    try:
        return _evaluate_marker_fallback(marker)
    except Exception:
        return True

def build_graph():
    all_dists = list(importlib.metadata.distributions())
    installed = {}
    dist_entries = []

    for dist in all_dists:
        name = get_dist_name(dist)
        if not name:
            continue
        version = get_dist_version(dist)
        norm = normalize(name)
        if not norm or norm in installed:
            continue  # Skip duplicates
        installed[norm] = {
            'name': name,
            'version': version,
            'requires': [],
            'required_by': [],
        }
        dist_entries.append((norm, dist))

    for norm, dist in dist_entries:
        try:
            raw_requires = dist.metadata.get_all('Requires-Dist') or []
        except Exception:
            raw_requires = []

        grouped_requires = {}
        for req_str in raw_requires:
            if not req_str:
                continue
            req_text = str(req_str).strip()
            if not req_text:
                continue
            # Skip extras-only dependencies
            if re.search(r'extra\s*==', req_text):
                continue

            requirement_part, marker_part = split_requirement_marker(req_text)
            if marker_part and not marker_applies(marker_part):
                continue

            dep_name = re.split(r'[\s;>=<!\[\(]', requirement_part)[0]
            if not dep_name:
                continue
            dep_norm = normalize(dep_name)
            if not dep_norm:
                continue

            # Extract version constraint
            version_match = re.search(r'([\(]?[>=<!=~]+[\d\w.*,>=<!=~ ]+[\)]?)', requirement_part)
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
            combined_constraint = simplify_constraint(', '.join(data['constraints']))

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
        dep_graph = {pkg.norm_name: pkg for pkg in packages}
        return packages, dep_graph

    # Build lookup mapping norm_name to a list of package instances
    pkg_map: Dict[str, List[Package]] = {}
    for pkg in packages:
        if pkg.norm_name not in pkg_map:
            pkg_map[pkg.norm_name] = []
        pkg_map[pkg.norm_name].append(pkg)

    # Enrich existing packages with dependency info
    for norm_name, info in dep_data.items():
        if norm_name not in pkg_map:
            continue

        for pkg in pkg_map[norm_name]:
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
                pkg_map[dep_norm] = [ghost]

    packages.extend(ghost_packages)

    # Build dep_graph dict for the Environment
    # In case of duplicates, keep the user-site one (if any) or just the last one
    dep_graph = {}
    for pkg in packages:
        if pkg.norm_name in dep_graph:
            if pkg.metadata.get("location") == "user":
                dep_graph[pkg.norm_name] = pkg
        else:
            dep_graph[pkg.norm_name] = pkg

    return packages, dep_graph
