import urllib.request
import urllib.error
import urllib.parse
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from app import build_info
from app import ed25519

# Simple logger setup
logger = logging.getLogger(__name__)

_USER_AGENT = "Surasura-Readability-Analyzer"
_LATEST_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
_RELEASES_PAGE = "https://github.com/{repo}/releases/latest"

# A test release's rehearsal points the check at a LOCAL folder holding update.json and the release's assets, read
# only by a build that is not a release build (`build_info.RELEASE_BUILD`): no test release is ever published.
UPDATE_SOURCE_ENV = "SURASURA_UPDATE_SOURCE"

# The 3.x format (S3.1 D4-D6): update.json's `format: 2` block, `package`, is read only with update.json.sig, Ed25519
# over the manifest's exact bytes by one of PUBLIC_KEYS (a tuple: a key can be rotated; the private half lives outside
# every repository, in Sonic's keystore). A rehearsal through UPDATE_SOURCE_ENV (a build that is not a release build)
# also trusts the hex public keys in TEST_PUBKEY_ENV (comma-separated).
PUBLIC_KEYS = (
    bytes.fromhex("c3a26bfe345033b3ccf0f25009826f694a9319d7fcb80bdbbc716928e4664bdb"),   # 2026-10-12
)
TEST_PUBKEY_ENV = "SURASURA_UPDATE_TEST_PUBKEY"
SIGNATURE_ASSET = "update.json.sig"
_SIGNATURE_LIMIT = 1024

# The telemetry receiver's address (2026-10-30): update.json's `telemetry_url`, kept by the telemetry for its next
# heartbeat, so the receiver can move without a release; the build's .env TELEMETRY_URL is the fallback. Read only
# from a signed manifest (3.x's: the release kit writes it there, nowhere else) fetched from GitHub, never from a
# rehearsal's local folder (UPDATE_SOURCE_ENV).
TELEMETRY_URL_KEY = "telemetry_url"
_TELEMETRY_URL_LIMIT = 300


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
    files: Optional[list] = None       # the release's file list (K99): {name, dest, kind, sha256} each; None = 2.4.0's
    installer: Optional[dict] = None   # update_type "installer" (S1.3-6): {asset, sha256, args, min_from}; 3.0+ only
    installer_url: Optional[str] = None
    app_package_url: Optional[str] = None
    full_url: Optional[str] = None
    notes_url: str = ""
    format: int = 1                    # 2: a 3.x release (S3.1 D5); its `package` is read only when `signed`
    package: Optional[dict] = None     # {parts[{name, asset, sha256, size}], files[{path, sha256, size, part}], ...}
    signed: bool = False               # update.json.sig verified against a trusted key
    assets: Optional[dict] = None      # every asset of the release: lower-cased name -> download URL (3.x's parts)


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


def _read_bytes(url: str, timeout: int = 10, limit: int = _SIGNATURE_LIMIT):
    """A small asset's bytes (https, or a rehearsal's file://), or None when it is larger than `limit`."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(limit + 1)
    return data if len(data) <= limit else None


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
    local = _local_source()
    try:
        data = _local_release(local) if local else _http_json(_LATEST_RELEASE_API.format(repo=repo), timeout=timeout)
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
    urls = {}
    for asset in assets:
        name = (asset.get("name") or "").lower()
        url = asset.get("browser_download_url")
        if not url:
            continue
        urls[name] = url
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
            raw = _read_local(manifest_url) if local else _http_text(manifest_url, timeout=timeout)
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
                installer = manifest.get("installer")
                if info.update_type == "installer" and isinstance(installer, dict):
                    info.installer = installer
                    info.installer_url = urls.get(str(installer.get("asset") or "").lower())
                if "files" in manifest:
                    files = manifest.get("files")
                    if isinstance(files, list) and files and all(isinstance(f, dict) for f in files):
                        info.files = files
                    else:
                        info.update_type = "full"     # a list we can't read: manual (fail closed)
                if manifest.get("format") == 2 and not isinstance(manifest.get("format"), bool):
                    # 3.x (S3.1 D5): the signature over the bytes as published (decoding UTF-8 and encoding it back
                    # gives the same bytes), then the package, read only when signed.
                    info.format = 2
                    info.assets = urls
                    info.signed = _signature_ok(raw.encode("utf-8"), urls.get(SIGNATURE_ASSET), local, timeout)
                    info.package = _read_package(manifest.get("package"), urls) if info.signed else None
                if info.signed and not local:
                    _keep_telemetry_url(manifest.get(TELEMETRY_URL_KEY))
        except Exception as e:
            # Fail closed: unreadable manifest => manual full update only.
            logger.error(f"Could not parse update manifest: {e}")
            info.update_type = "full"

    return info


def valid_telemetry_url(value):
    """`value` when it is a receiver's address the heartbeat may use: an https URL with a host, no user or password,
    no spaces, at most 300 characters -> the str, else None."""
    if not isinstance(value, str) or not value or len(value) > _TELEMETRY_URL_LIMIT \
            or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        parts = urllib.parse.urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        parts.port                                      # a port that isn't a number raises
    except ValueError:
        return None
    return value


def _keep_telemetry_url(value):
    """Hand update.json's `telemetry_url` to the telemetry's cache when it is a valid one (none, or a bad one, leaves
    the cache as it is). Never raises: the update check never fails for it."""
    url = valid_telemetry_url(value)
    if not url:
        return
    try:
        from app import telemetry
        telemetry.remember_url(url)
    except Exception as e:
        logger.error(f"Could not keep the telemetry address: {e}")


def _local_source():
    """The rehearsal's local folder, or None: never in a release build, never when it isn't a folder."""
    folder = os.environ.get(UPDATE_SOURCE_ENV)
    if not folder or getattr(build_info, "RELEASE_BUILD", True):
        return None
    return folder if os.path.isdir(folder) else None


def _local_release(folder):
    """The local folder as GitHub's latest-release answer: its update.json names the version; every file in it is
    an asset, reached by a file:// URL (urllib reads those as it reads https)."""
    with open(os.path.join(folder, "update.json"), "r", encoding="utf-8") as f:
        version = str(json.load(f).get("version", ""))
    assets = [{"name": name, "browser_download_url": Path(os.path.abspath(os.path.join(folder, name))).as_uri()}
              for name in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, name))]
    return {"tag_name": f"v{version}", "html_url": Path(os.path.abspath(folder)).as_uri(), "assets": assets}


def _read_local(url):
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def _trusted_keys(local):
    """PUBLIC_KEYS, and in a rehearsal (a local folder, which a release build never reads) TEST_PUBKEY_ENV's keys."""
    keys = [bytes(k) for k in PUBLIC_KEYS]
    if local:
        for item in (os.environ.get(TEST_PUBKEY_ENV) or "").replace(";", ",").split(","):
            try:
                key = bytes.fromhex(item.strip())
            except ValueError:
                continue
            if len(key) == 32:
                keys.append(key)
    return keys


def _signature_ok(data, sig_url, local, timeout=10):
    """Is update.json.sig a valid signature of `data` (the manifest's bytes) by a trusted key? Never raises: a
    missing, oversized or unreadable signature, or no trusted key at all, is False."""
    if not sig_url:
        return False
    try:
        signature = _read_bytes(sig_url, timeout=timeout)
    except Exception as e:
        logger.error(f"Could not read the update signature: {e}")
        return False
    if not signature or len(signature) != 64:
        return False
    return any(ed25519.verify(key, data, signature) for key in _trusted_keys(local))


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _is_size(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_shape(value):
    return isinstance(value, str) and len(value) == 16 and all(c in "0123456789abcdef" for c in value)


def _read_package(package, urls):
    """update.json's `package` when its shape is whole -> the dict, else None: parts each {name, asset, sha256, size}
    with its asset among the release's; files each {path, sha256, size, part} naming one of those parts;
    needs_installer a bool; min_from a version; install_shape, when given, 16 hex. (Each path's safety is the
    assembler's check, S3.1 3.1.3.)"""
    if not isinstance(package, dict):
        return None
    parts, files = package.get("parts"), package.get("files")
    if not isinstance(parts, list) or not parts or not isinstance(files, list) or not files:
        return None
    names = set()
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("name"), str) or part["name"] in names \
                or not _is_sha256(part.get("sha256")) or not _is_size(part.get("size")) \
                or str(part.get("asset") or "").lower() not in urls:
            return None
        names.add(part["name"])
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"] \
                or not _is_sha256(entry.get("sha256")) or not _is_size(entry.get("size")) \
                or entry.get("part") not in names:
            return None
    if not isinstance(package.get("needs_installer", False), bool):
        return None
    if package.get("min_from") is not None and not version_string(str(package.get("min_from"))):
        return None
    if package.get("install_shape") is not None and not _is_shape(package["install_shape"]):
        return None
    return package


def installed_shape():
    """This program's install shape (S3.1 D7): its `_internal/build_stamp.json`'s "install_shape", or None — from
    source, with no stamp, or a stamp an earlier 3.x wrote without one."""
    from app import path_utils
    if not path_utils.is_frozen():
        return None
    try:
        with open(os.path.join(path_utils.get_base_path(), path_utils.BUILD_STAMP), "r", encoding="utf-8-sig") as f:
            shape = json.load(f).get("install_shape")
    except (OSError, ValueError, AttributeError):
        return None
    return shape if _is_shape(shape) else None


INSTALLER_FROM_VERSION = (3, 0)


def installer_ready(current_version: str, info: "UpdateInfo") -> bool:
    """Is this an installer release 2.x may hand over to: version 3.0 or later, its installer named by an asset the
    release carries, a sha256, args a list of strings, and `min_from` (when given) no newer than this version?"""
    inst = info.installer if isinstance(info.installer, dict) else None
    if not inst or parse_version(info.version) < INSTALLER_FROM_VERSION or not info.installer_url:
        return False
    sha = str(inst.get("sha256") or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return False
    args = inst.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return False
    min_from = inst.get("min_from")
    if min_from and parse_version(current_version) < parse_version(str(min_from)):
        return False
    return True


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
      "INSTALLER" — 3.0 or later, declared "installer": its own installer takes over (S1.3-6).
    """
    if not info:
        return "NONE"

    if parse_version(info.version) <= parse_version(current_version):
        return "NONE"

    if getattr(info, "format", 1) == 2:
        return _classify_3x(current_version, info)

    if info.update_type == "installer":
        # The 2.x -> 3.0 hand-off (S1.3-6), shipped in 2.5 switched off: only a release of 3.0 or later that names
        # its installer completely, for a version it accepts updating from. Anything else: a manual download.
        return "INSTALLER" if installer_ready(current_version, info) else "FULL"

    if (
        info.update_type == "app"
        and info.app_package_url
        and info.sha256
        and parse_version(current_version) >= parse_version(info.runtime_baseline)
    ):
        return "APP"

    return "FULL"


def _classify_3x(current_version: str, info: UpdateInfo) -> str:
    """A 3.x release (format 2), for a 3.x install. Unsigned, or a bad signature -> FULL (told only, nothing
    installed). APP: its package read, this version at or past `min_from`, and nothing only the installer may change.
    INSTALLER: the installer must run — `needs_installer`, this program's install shape and the release's both known
    and different (a stamp without one, an earlier 3.x's, compares as the same), or this version below `min_from` —
    and the release names a complete one. Anything else: FULL."""
    if not info.signed:
        return "FULL"
    package = info.package if isinstance(info.package, dict) else None
    if package is None:
        return "FULL"
    min_from = package.get("min_from")
    too_old = bool(min_from) and parse_version(current_version) < parse_version(str(min_from))
    shape, own = package.get("install_shape"), installed_shape()
    needs_installer = package.get("needs_installer") is True or bool(shape and own and shape != own)
    if not too_old and not needs_installer:
        return "APP"
    if installer_ready(current_version, info):
        return "INSTALLER"
    return "FULL"
