import json
import os
import re
import threading
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from core.network_proxy import normalize_proxy_settings
from core.network_proxy import urlopen as proxy_urlopen
from core.source_profiles import PYPI_OFFICIAL_INDEX, detect_system_pip_index_url
from core.utils import get_app_root, get_persistent_root


CACHE_FILENAME = "pypi_search_cache.json"
SEED_FILENAME = "pypi_search_seed.json"
PARTIAL_DOWNLOAD_FILENAME = "pypi_search_cache.download"
PARTIAL_META_FILENAME = "pypi_search_cache.download.meta.json"
DEFAULT_STALE_AFTER_HOURS = 24

_cache_lock = threading.Lock()
_index_lock = threading.Lock()
_in_memory_payload = None
_in_memory_index = None
_background_refresh_lock = threading.Lock()
_background_refresh_thread = None
_refresh_state_lock = threading.Lock()
_active_download_lock = threading.Lock()
_active_download_response = None
_refresh_cancel_event = threading.Event()


def _new_refresh_state() -> dict:
    return {
        "running": False,
        "can_cancel": False,
        "stage": "idle",
        "message": "",
        "started_at": "",
        "finished_at": "",
        "source_mode": "",
        "source_url": "",
        "source_label": "",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "percent": None,
        "resume_from_bytes": 0,
        "error": "",
        "logs": [],
    }


_refresh_state = _new_refresh_state()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso_utc(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clone_refresh_state() -> dict:
    with _refresh_state_lock:
        copied = dict(_refresh_state)
        copied["logs"] = list(_refresh_state.get("logs", []))
        return copied


def _append_refresh_log(message: str):
    text = str(message or "").strip()
    if not text:
        return
    line = f"[{_utc_now_iso()}] {text}"
    with _refresh_state_lock:
        logs = _refresh_state.get("logs", [])
        logs.append(line)
        if len(logs) > 200:
            del logs[: len(logs) - 200]
        _refresh_state["logs"] = logs


def _update_refresh_state(**kwargs):
    with _refresh_state_lock:
        for key, value in kwargs.items():
            _refresh_state[key] = value


def get_refresh_state() -> dict:
    return _clone_refresh_state()


def cache_file_path() -> Path:
    return get_persistent_root() / CACHE_FILENAME


def seed_file_path() -> Path:
    return get_app_root() / "resources" / SEED_FILENAME


def partial_download_path() -> Path:
    return get_persistent_root() / PARTIAL_DOWNLOAD_FILENAME


def partial_meta_path() -> Path:
    return get_persistent_root() / PARTIAL_META_FILENAME


def _default_seed_packages() -> list[str]:
    return [
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "seaborn",
        "scikit-learn",
        "requests",
        "flask",
        "django",
        "fastapi",
        "pytest",
        "pydantic",
        "sqlalchemy",
        "jupyter",
        "ipython",
        "black",
        "ruff",
        "mypy",
        "torch",
        "tensorflow",
    ]


def _normalize_index_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        text = PYPI_OFFICIAL_INDEX
    if "://" not in text:
        text = f"https://{text.lstrip('/')}"
    text = text.rstrip("/")
    return f"{text}/"


def _build_source_label(index_url: str, mode: str) -> str:
    parsed = urllib.parse.urlparse(index_url)
    host = parsed.netloc or "unknown-host"
    mode_text = str(mode or "unknown")
    return f"{host} ({mode_text})"


def resolve_refresh_source(
    *,
    pip_settings: Optional[dict] = None,
    system_index_url: Optional[str] = None,
) -> dict:
    settings = pip_settings or {}
    mode = str(settings.get("source_mode", "system")).strip().lower()
    custom_url = str(settings.get("index_url", "")).strip()
    detected_system_url = str(system_index_url or "").strip()
    if mode not in {"system", "official", "custom"}:
        mode = "system"

    if mode == "official":
        index_url = PYPI_OFFICIAL_INDEX
    elif mode == "custom":
        index_url = custom_url or PYPI_OFFICIAL_INDEX
    else:
        if not detected_system_url:
            detected_system_url = detect_system_pip_index_url()
        index_url = detected_system_url or PYPI_OFFICIAL_INDEX

    simple_url = _normalize_index_url(index_url)
    return {
        "mode": mode,
        "simple_url": simple_url,
        "source_label": _build_source_label(simple_url, mode),
    }


def _normalize_payload(payload: dict) -> dict:
    raw_packages = payload.get("packages", [])
    if not isinstance(raw_packages, list):
        raw_packages = []

    dedup = set()
    packages = []
    for item in raw_packages:
        name = str(item or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in dedup:
            continue
        dedup.add(lowered)
        packages.append(name)

    packages.sort(key=lambda item: item.lower())
    return {
        "version": int(payload.get("version", 1)),
        "updated_at": str(payload.get("updated_at") or _utc_now_iso()),
        "source": str(payload.get("source") or "unknown"),
        "package_count": len(packages),
        "packages": packages,
    }


def _default_payload(source: str) -> dict:
    return _normalize_payload(
        {
            "version": 1,
            "updated_at": _utc_now_iso(),
            "source": source,
            "packages": _default_seed_packages(),
        }
    )


def _read_payload(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return _normalize_payload(raw)


def _write_payload(path: Path, payload: dict):
    normalized = _normalize_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(normalized, fp, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _set_in_memory(payload: dict):
    global _in_memory_payload, _in_memory_index
    with _cache_lock:
        _in_memory_payload = payload
    with _index_lock:
        _in_memory_index = None


def ensure_cache_exists() -> dict:
    path = cache_file_path()
    payload = _read_payload(path)
    if payload is not None:
        _set_in_memory(payload)
        return payload

    seed_payload = _read_payload(seed_file_path())
    if seed_payload is None:
        seed_payload = _default_payload("built-in-seed")
    else:
        seed_payload["source"] = "bundled-seed"

    _write_payload(path, seed_payload)
    _set_in_memory(seed_payload)
    return seed_payload


def load_cache_payload() -> dict:
    global _in_memory_payload
    if _in_memory_payload is not None:
        return _in_memory_payload

    payload = _read_payload(cache_file_path())
    if payload is None:
        payload = ensure_cache_exists()
    _set_in_memory(payload)
    return payload


def get_cache_status(stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS) -> dict:
    payload = load_cache_payload()
    source = str(payload.get("source", "unknown"))
    updated = _parse_iso_utc(payload.get("updated_at", ""))
    age_seconds = None
    stale = True
    if updated is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
        stale = age_seconds >= max(1, int(stale_after_hours)) * 3600
    if source in {"built-in-seed", "bundled-seed"}:
        stale = True

    return {
        "cache_path": str(cache_file_path()),
        "exists": cache_file_path().exists(),
        "package_count": int(payload.get("package_count", len(payload.get("packages", [])))),
        "updated_at": str(payload.get("updated_at", "")),
        "source": source,
        "age_seconds": age_seconds,
        "stale": stale,
    }


def _build_index(payload: dict) -> list[tuple[str, str]]:
    with _index_lock:
        global _in_memory_index
        if _in_memory_index is not None:
            return _in_memory_index
        rows = [(name.lower(), name) for name in payload.get("packages", [])]
        _in_memory_index = rows
        return rows


def search_cached_packages(query: str, limit: int = 30) -> list[dict]:
    text = str(query or "").strip().lower()
    if not text:
        return []

    payload = load_cache_payload()
    index = _build_index(payload)

    ranked = []
    for lowered, name in index:
        if text not in lowered:
            continue
        if lowered == text:
            score = 0
        elif lowered.startswith(text):
            score = 1
        else:
            score = 2
        ranked.append((score, len(name), name))

    ranked.sort()
    results = []
    for _, _, name in ranked[: max(1, int(limit))]:
        results.append({"name": name, "version": "cached", "description": "local cache"})
    return results


def _format_bytes(count: int) -> str:
    value = float(max(0, int(count)))
    units = ["B", "KB", "MB", "GB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)}{units[idx]}"
    return f"{value:.1f}{units[idx]}"


def _load_partial_meta() -> dict:
    path = partial_meta_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def _write_partial_meta(meta: dict):
    path = partial_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _clear_partial_download():
    for p in (partial_download_path(), partial_meta_path()):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def _should_force_pypi_proxy(proxy_settings: Optional[dict]) -> bool:
    settings = normalize_proxy_settings(proxy_settings)
    targets = settings.get("targets", {})
    return bool(settings.get("enabled", False) and targets.get("pypi", False))


def _set_active_response(response):
    with _active_download_lock:
        global _active_download_response
        _active_download_response = response


def _clear_active_response(response=None):
    with _active_download_lock:
        global _active_download_response
        if response is None or _active_download_response is response:
            _active_download_response = None


def _close_active_response():
    with _active_download_lock:
        response = _active_download_response
    if response is not None:
        try:
            response.close()
        except Exception:
            pass


class RefreshCancelledError(Exception):
    pass


class _SimpleIndexHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._inside_anchor = False
        self._parts = []
        self.names = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "a":
            self._inside_anchor = True
            self._parts = []

    def handle_data(self, data: str):
        if self._inside_anchor and data:
            self._parts.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() != "a":
            return
        if self._inside_anchor:
            name = "".join(self._parts).strip()
            if name:
                self.names.append(name)
        self._inside_anchor = False
        self._parts = []


def _extract_names_from_content(raw_bytes: bytes) -> list[str]:
    text = raw_bytes.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        payload = json.loads(text)
        projects = payload.get("projects", []) if isinstance(payload, dict) else []
        names = []
        for item in projects:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
        if names:
            return names

    parser = _SimpleIndexHTMLParser()
    parser.feed(text)
    parser.close()
    names = [str(name).strip() for name in parser.names if str(name).strip()]
    if names:
        return names

    raise ValueError("Unable to parse package names from index response")


def _parse_total_from_content_range(value: str) -> Optional[int]:
    text = str(value or "").strip()
    match = re.match(r"bytes\s+\d+-\d+/(\d+)", text)
    if not match:
        return None
    try:
        total = int(match.group(1))
        if total > 0:
            return total
    except Exception:
        return None
    return None


def refresh_cache_from_pypi(
    proxy_settings: Optional[dict] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
    progress_detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    timeout: Optional[int] = None,
    source_info: Optional[dict] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    source = source_info or resolve_refresh_source()
    source_url = str(source.get("simple_url", ""))
    source_label = str(source.get("source_label", "unknown source"))
    cancel = cancel_event or threading.Event()

    def _emit(
        message: str,
        *,
        stage: Optional[str] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        percent: Optional[float] = None,
        resume_from_bytes: Optional[int] = None,
        log: bool = False,
    ):
        if progress_cb:
            progress_cb(message)
        if progress_detail_cb:
            progress_detail_cb(
                {
                    "message": message,
                    "stage": stage,
                    "downloaded_bytes": downloaded_bytes,
                    "total_bytes": total_bytes,
                    "percent": percent,
                    "resume_from_bytes": resume_from_bytes,
                    "log": log,
                }
            )

    if cancel.is_set():
        raise RefreshCancelledError("Cancelled by user")

    download_path = partial_download_path()
    download_path.parent.mkdir(parents=True, exist_ok=True)
    meta = _load_partial_meta()
    if str(meta.get("source_url", "")) != source_url:
        _clear_partial_download()
        meta = {}

    resume_from = 0
    if download_path.exists():
        try:
            resume_from = max(0, int(download_path.stat().st_size))
        except Exception:
            resume_from = 0
    if resume_from < 0:
        resume_from = 0

    headers = {
        "User-Agent": "OmniPack/1.0",
        "Accept": "application/vnd.pypi.simple.v1+json, text/html;q=0.9, */*;q=0.8",
    }
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
    _write_partial_meta({"source_url": source_url, "updated_at": _utc_now_iso()})

    _emit(
        f"Connecting to package index: {source_label}",
        stage="connecting",
        downloaded_bytes=resume_from,
        total_bytes=None,
        resume_from_bytes=resume_from,
        log=True,
    )

    response = proxy_urlopen(
        source_url,
        timeout=timeout,
        headers=headers,
        proxy_settings=proxy_settings,
        force_proxy=_should_force_pypi_proxy(proxy_settings),
    )
    _set_active_response(response)
    try:
        if cancel.is_set():
            raise RefreshCancelledError("Cancelled by user")

        status_code = response.getcode() or 0
        if status_code == 416 and resume_from > 0:
            _append_refresh_log("Server rejected resume range, restarting full download.")
            _clear_partial_download()
            raise ValueError("Server rejected resume range")
        is_resumed_stream = status_code == 206 and resume_from > 0
        if resume_from > 0 and not is_resumed_stream:
            resume_from = 0

        total_bytes = None
        content_range = response.headers.get("Content-Range")
        if is_resumed_stream and content_range:
            total_bytes = _parse_total_from_content_range(content_range)

        if total_bytes is None:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    current_length = int(content_length)
                    if current_length > 0:
                        total_bytes = current_length + resume_from
                except (TypeError, ValueError):
                    total_bytes = None

        if is_resumed_stream:
            _emit(
                f"Resuming download from {_format_bytes(resume_from)}...",
                stage="downloading",
                downloaded_bytes=resume_from,
                total_bytes=total_bytes,
                percent=(resume_from * 100.0 / total_bytes) if total_bytes else None,
                resume_from_bytes=resume_from,
                log=True,
            )
        else:
            _emit(
                "Downloading package index...",
                stage="downloading",
                downloaded_bytes=0,
                total_bytes=total_bytes,
                percent=0.0 if total_bytes else None,
                resume_from_bytes=resume_from,
                log=True,
            )

        mode = "ab" if is_resumed_stream else "wb"
        downloaded = resume_from if is_resumed_stream else 0
        chunk_size = 256 * 1024
        last_percent_int = -1
        last_reported_bytes = downloaded

        with open(download_path, mode) as cache_stream:
            while True:
                if cancel.is_set():
                    raise RefreshCancelledError("Cancelled by user")
                try:
                    chunk = response.read(chunk_size)
                except Exception as e:
                    if cancel.is_set():
                        raise RefreshCancelledError("Cancelled by user") from e
                    raise
                if not chunk:
                    break
                cache_stream.write(chunk)
                downloaded += len(chunk)

                report = False
                percent = None
                if total_bytes:
                    percent = min(100.0, (downloaded * 100.0) / total_bytes)
                    percent_int = int(percent)
                    if percent_int != last_percent_int:
                        last_percent_int = percent_int
                        report = True
                else:
                    if downloaded - last_reported_bytes >= 1024 * 1024:
                        last_reported_bytes = downloaded
                        report = True

                if report:
                    if total_bytes and percent is not None:
                        text = (
                            f"Downloading package index... {percent:.1f}% "
                            f"({_format_bytes(downloaded)}/{_format_bytes(total_bytes)})"
                        )
                    else:
                        text = f"Downloading package index... {_format_bytes(downloaded)}"
                    _emit(
                        text,
                        stage="downloading",
                        downloaded_bytes=downloaded,
                        total_bytes=total_bytes,
                        percent=percent,
                        resume_from_bytes=resume_from,
                    )
    finally:
        _clear_active_response(response)
        try:
            response.close()
        except Exception:
            pass

    if cancel.is_set():
        raise RefreshCancelledError("Cancelled by user")

    _emit("Download complete, parsing index...", stage="parsing", log=True)
    with open(download_path, "rb") as fp:
        raw_content = fp.read()

    _emit("Parsing package names...", stage="parsing", log=True)
    names = _extract_names_from_content(raw_content)

    cache_payload = _normalize_payload(
        {
            "version": 1,
            "updated_at": _utc_now_iso(),
            "source": source_label,
            "packages": names,
        }
    )
    _emit("Saving local cache...", stage="saving", log=True)
    _write_payload(cache_file_path(), cache_payload)
    _set_in_memory(cache_payload)
    _clear_partial_download()
    _emit(
        f"Cache updated: {cache_payload.get('package_count', 0)} packages",
        stage="completed",
        percent=100.0,
        log=True,
    )
    return cache_payload


def _run_refresh_task(
    proxy_settings: Optional[dict],
    timeout: Optional[int],
    source_info: dict,
):
    _refresh_cancel_event.clear()
    _update_refresh_state(
        running=True,
        can_cancel=True,
        stage="starting",
        message="Starting cache refresh...",
        started_at=_utc_now_iso(),
        finished_at="",
        source_mode=str(source_info.get("mode", "")),
        source_url=str(source_info.get("simple_url", "")),
        source_label=str(source_info.get("source_label", "")),
        downloaded_bytes=0,
        total_bytes=None,
        percent=0.0,
        resume_from_bytes=0,
        error="",
        logs=[],
    )
    _append_refresh_log(
        f"Starting cache refresh from {source_info.get('source_label', 'unknown source')}..."
    )

    def _on_detail(event: Dict[str, Any]):
        message = str(event.get("message", "")).strip()
        updates: Dict[str, Any] = {"message": message}
        stage = event.get("stage")
        if stage:
            updates["stage"] = stage
        if "downloaded_bytes" in event:
            updates["downloaded_bytes"] = int(event.get("downloaded_bytes") or 0)
        if "total_bytes" in event:
            total_raw = event.get("total_bytes")
            updates["total_bytes"] = int(total_raw) if total_raw else None
        if "percent" in event:
            percent_raw = event.get("percent")
            updates["percent"] = float(percent_raw) if percent_raw is not None else None
        if "resume_from_bytes" in event:
            updates["resume_from_bytes"] = int(event.get("resume_from_bytes") or 0)
        _update_refresh_state(**updates)
        if event.get("log", False) and message:
            _append_refresh_log(message)

    try:
        try:
            payload = refresh_cache_from_pypi(
                proxy_settings=proxy_settings,
                timeout=timeout,
                source_info=source_info,
                cancel_event=_refresh_cancel_event,
                progress_detail_cb=_on_detail,
            )
        except ValueError as e:
            if "resume range" not in str(e).lower():
                raise
            payload = refresh_cache_from_pypi(
                proxy_settings=proxy_settings,
                timeout=timeout,
                source_info=source_info,
                cancel_event=_refresh_cancel_event,
                progress_detail_cb=_on_detail,
            )
        done_message = f"Cache refresh completed: {payload.get('package_count', 0)} packages"
        _update_refresh_state(
            running=False,
            can_cancel=False,
            stage="success",
            message=done_message,
            finished_at=_utc_now_iso(),
            percent=100.0,
            error="",
        )
        _append_refresh_log(done_message)
    except RefreshCancelledError:
        _update_refresh_state(
            running=False,
            can_cancel=False,
            stage="cancelled",
            message="Cache refresh cancelled by user",
            finished_at=_utc_now_iso(),
            error="cancelled",
        )
        _append_refresh_log("Cache refresh cancelled by user.")
    except Exception as e:
        err_text = str(e)
        _update_refresh_state(
            running=False,
            can_cancel=False,
            stage="error",
            message=f"Cache refresh failed: {err_text}",
            finished_at=_utc_now_iso(),
            error=err_text,
        )
        _append_refresh_log(f"Cache refresh failed: {err_text}")
    finally:
        _refresh_cancel_event.clear()
        _clear_active_response()
        with _background_refresh_lock:
            global _background_refresh_thread
            _background_refresh_thread = None


def start_refresh_task(
    proxy_settings: Optional[dict] = None,
    timeout: Optional[int] = None,
    pip_settings: Optional[dict] = None,
    system_index_url: Optional[str] = None,
) -> bool:
    with _background_refresh_lock:
        global _background_refresh_thread
        if _background_refresh_thread and _background_refresh_thread.is_alive():
            return False
        source_info = resolve_refresh_source(
            pip_settings=pip_settings,
            system_index_url=system_index_url,
        )
        thread = threading.Thread(
            target=_run_refresh_task,
            args=(proxy_settings, timeout, source_info),
            daemon=True,
            name="pypi-cache-refresh",
        )
        _background_refresh_thread = thread
        thread.start()
        return True


def cancel_refresh_task() -> bool:
    with _background_refresh_lock:
        thread = _background_refresh_thread
    if not thread or not thread.is_alive():
        return False
    _refresh_cancel_event.set()
    _update_refresh_state(stage="canceling", message="Cancelling cache refresh...")
    _append_refresh_log("Cancelling cache refresh...")
    _close_active_response()
    return True


def start_background_refresh_if_needed(
    proxy_settings: Optional[dict] = None,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
    force: bool = False,
    timeout: Optional[int] = None,
    pip_settings: Optional[dict] = None,
    system_index_url: Optional[str] = None,
) -> bool:
    status = get_cache_status(stale_after_hours=stale_after_hours)
    should_refresh = force or status.get("stale", True)
    if not should_refresh:
        return False
    return start_refresh_task(
        proxy_settings=proxy_settings,
        timeout=timeout,
        pip_settings=pip_settings,
        system_index_url=system_index_url,
    )
