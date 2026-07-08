import urllib.request
import urllib.error
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Simple logger setup
logger = logging.getLogger(__name__)

_USER_AGENT = "Surasura-Readability-Analyzer"
_LATEST_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
_RELEASES_PAGE = "https://github.com/{repo}/releases/latest"


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Robust semantic version parser.
    Extracts the first run of dotted (or bare) integers from a string.
    e.g., 'v1.0.0' -> (1, 0, 0)
          'Beta-Production-1.1' -> (1, 1)
          'v2' -> (2,)
    Returns (0, 0, 0) when no number is present, so comparisons stay well-defined.
    """
    try:
        match = re.search(r'(\d+(?:\.\d+)*)', version_str or '')
        if match:
            return tuple(map(int, match.group(1).split('.')))
    except Exception:
        pass
    return (0, 0, 0)


def version_string(s: str) -> str:
    """Return the normalized numeric version substring of ``s`` (e.g. 'v2.1' -> '2.1'), or ''."""
    match = re.search(r'(\d+(?:\.\d+)*)', s or '')
    return match.group(1) if match else ""


@dataclass
class UpdateInfo:
    """Everything the app needs to decide about, and act on, a GitHub release.

    ``update_type`` is authored by the release (in update.json), NOT inferred from the
    version number: "app" means the small app-code package may be applied in place; "full"
    means a manual full download is required. Anything missing/ambiguous stays "full".
    """
    version: str
    update_type: str = "full"          # "app" | "full"
    runtime_baseline: str = "0.0"      # earliest version whose _internal runtime is compatible
    critical: bool = False
    sha256: str = ""
    app_package_url: Optional[str] = None
    full_url: Optional[str] = None
    notes_url: str = ""


# ---------------------------------------------------------------------------
# Low-level HTTP (stdlib only; every call is bounded by a timeout and fails soft)
# ---------------------------------------------------------------------------
def _http_json(url: str, timeout: int = 10):
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.getcode() == 200:
            return json.loads(response.read().decode())
    return None


def _http_text(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.getcode() == 200:
            return response.read().decode("utf-8")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check_for_updates(current_version: str, repo: str = "SonicSandbox/surasura") -> Optional[Tuple[str, str]]:
    """
    Backward-compatible lightweight check.
    Returns (new_version_tag, html_url) if a newer release exists, else None.
    Prefer get_update_info() + classify_update() for the full-featured path.
    """
    try:
        data = _http_json(_LATEST_RELEASE_API.format(repo=repo))
        if not data:
            return None
        latest_tag = data.get("tag_name")
        html_url = data.get("html_url")
        if not latest_tag or not html_url:
            return None
        if parse_version(latest_tag) > parse_version(current_version):
            return latest_tag, html_url
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 == no releases yet, which is expected/quiet
            logger.error(f"HTTP Error checking for updates: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking for updates: {e}")
    return None


def get_update_info(repo: str = "SonicSandbox/surasura", timeout: int = 10) -> Optional[UpdateInfo]:
    """
    Fetch the latest release and resolve it into an UpdateInfo.

    Reads the release's ``update.json`` asset for update_type / runtime_baseline / sha256 /
    critical, and locates the app-package and full-zip assets by name. If the manifest is
    absent or unparseable, the update is reported as "full" (fail closed) so the user is
    still notified but nothing is ever auto-applied on bad metadata. Returns None on no
    release / network error.
    """
    try:
        data = _http_json(_LATEST_RELEASE_API.format(repo=repo), timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.error(f"HTTP Error fetching release: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching release: {e}")
        return None

    if not data:
        return None

    tag = data.get("tag_name") or ""
    version = version_string(tag)
    if not version:
        return None

    html_url = data.get("html_url") or _RELEASES_PAGE.format(repo=repo)
    assets = data.get("assets") or []

    app_url = None
    full_url = None
    manifest_url = None
    for asset in assets:
        name = (asset.get("name") or "").lower()
        url = asset.get("browser_download_url")
        if not url:
            continue
        if name == "update.json":
            manifest_url = url
        elif name.startswith("surasura_app_v") and name.endswith(".zip"):
            app_url = url
        elif name.startswith("surasura_v") and name.endswith(".zip"):
            full_url = url

    info = UpdateInfo(
        version=version,
        update_type="full",
        runtime_baseline=version,   # conservative default until the manifest says otherwise
        notes_url=html_url,
        full_url=full_url or html_url,
        app_package_url=app_url,
    )

    if manifest_url:
        try:
            raw = _http_text(manifest_url, timeout=timeout)
            manifest = json.loads(raw) if raw else {}
            if isinstance(manifest, dict):
                info.update_type = str(manifest.get("update_type", "full")).lower()
                info.critical = bool(manifest.get("critical", False))
                info.sha256 = str(manifest.get("sha256", "") or "")
                baseline = version_string(str(manifest.get("runtime_baseline", version)))
                info.runtime_baseline = baseline or version
                manifest_version = version_string(str(manifest.get("version", "")))
                if manifest_version:
                    info.version = manifest_version
        except Exception as e:
            # Fail closed: unreadable manifest => manual full update only.
            logger.error(f"Could not parse update manifest: {e}")
            info.update_type = "full"

    return info


def classify_update(current_version: str, info: Optional[UpdateInfo]) -> str:
    """
    Decide what kind of update (if any) applies.

    Returns:
      "NONE" — up to date (or no release / info).
      "APP"  — an in-place app-code update is available AND safe to auto-apply
               (declared "app", has a package + checksum, and the current runtime is at or
               past the release's runtime_baseline).
      "FULL" — a newer release exists but must be downloaded manually (major/runtime change,
               or any missing/ambiguous metadata — fail closed).
    """
    if not info:
        return "NONE"

    if parse_version(info.version) <= parse_version(current_version):
        return "NONE"

    if (
        info.update_type == "app"
        and info.app_package_url
        and info.sha256
        and parse_version(current_version) >= parse_version(info.runtime_baseline)
    ):
        return "APP"

    return "FULL"
