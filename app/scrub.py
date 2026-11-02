"""The scrub (Send report; `tracks/ship/work/send-report/SPEC.md` §2): who "you" are on this PC, and every text a report
takes off it — each zip entry and its name, the window's pictures — with them written as placeholders. Pure: the
standard library and Surasura's own Qt-free modules, never Qt.

**Who you are** (`identity()`, §2.1): the home folders (`USERPROFILE`, `~`, `HOMEDRIVE`+`HOMEPATH`, `HOME`, the
profile `APPDATA` / `LOCALAPPDATA` sit in, each one's 8.3 short form), the user names (`USERNAME`, `getuser()`, `USER`,
`LOGNAME`, each home's last part), the machine names (`COMPUTERNAME`, `gethostname()`, `platform.node()`, `USERDOMAIN`
when it is none of them and not `WORKGROUP`), the OneDrive organisations (`OneDrive - <org>`), the Anki profiles (every
folder in Anki's data folder holding a `collection.anki2`, Connect's own, Anki Miner's when it isn't `Surasura`; Anki's
default `User 1` stays), the four install keys (the local data folder's, each library database's, the window lock's and
each store bell's — every one asked of the code that makes it, never a copy of its hashing) and the telemetry id (read,
never made). Each is optional: one that can't be read is skipped. It lists folders and reads two small files, so the
window works it out on a worker as it opens (`prepare`); picture mode never waits for it (`shown`).

**What becomes what** (§2.2): a home folder → its own drive and parent with `<you>` (`C:\\Users\\<you>`), a user name →
`<you>`, a machine → `<pc>`, an organisation → `<org>`, an Anki profile → `<anki profile n>`, an install key →
`<install key>`, the telemetry id → `<telemetry id>`, an email → `<email>`, a Windows SID → `<sid>`. Every string is
also looked for in each form it can be written in: NFC and NFD, JSON's `\\u` (the command line's events are
`ensure_ascii`), Python's `\\x` / `\\u` / `\\U` and a bytes repr's `\\xNN`, percent-encoded UTF-8 (a space as `%20`
or `+`), and the window lock's (every character outside `[A-Za-z0-9_.-]` written `_`). A path's separators may be `\\`, any run
of them (JSON, a repr, JSON in JSON), `/`, `%5C`, `%2F`, `\\x5c` or `\\u005c`, and its drive `C:` or Git Bash's `/c`.
Case never matters but for an Anki profile's. A name made only of ASCII letters and digits is replaced only as a whole
word — no ASCII letter or digit beside it (an escape such as `%20`, `\\n` or `\\u00e9` counts as a gap) — so
`Michaelson` beside the user `Michael` stays; a name with any other letter (田中, Zoë) everywhere; a one-letter name only as a home
folder's last part. The price (⚖️, accepted): a user named like an everyday word (`user`, `anime`) is replaced wherever
the word stands alone.

**The guard** (`leaks`, §2.3): the written zip opened again, every entry's name and text — decoded as the zip decoded
it, and its raw bytes as UTF-16LE too — searched for every string in every form (a picture: its text chunks). The
placeholders themselves are never a hit.
"""
import codecs
import contextlib
import getpass
import json
import os
import platform
import re
import socket
import struct
import sys
import threading
import unicodedata
import zipfile
import zlib

YOU, PC, ORG, KEY, TELEMETRY, EMAIL, SID = ("<you>", "<pc>", "<org>", "<install key>", "<telemetry id>", "<email>",
                                            "<sid>")
PROFILE = "<anki profile {n}>"
ANKI_DEFAULT = "User 1"                     # Anki's own first profile: names no one
ANKI_MINER_DEFAULT = "Surasura"             # connect_anki_miner_profile's default (app/connect/anki_miner.py)
_PLACEHOLDER = re.compile(r"<(?:you|pc|org|install key|telemetry id|email|sid|anki profile \d+)>"
                          r"|\((?:you|pc|org|install key|telemetry id|email|sid|anki profile \d+)\)")
_EMAIL = r"[\w.+-]+(?:@|%40|\\u0040|\\x40)[\w-]+(?:\.[\w-]+)+"            # (and its escaped @)
_SID = r"S-1-(?:5-21|12-1)(?:-\d+){3,4}"                                   # a local / domain account, an Entra ID one
_SIDS = ("s-1-5-21", "s-1-12-1")
_ATS = ("@", "%40", "\\u0040", "\\x40")
# a gap before a whole word: no ASCII letter or digit, or the end of an escape (`%20`, `\n`, `\xe9`, `\u00e9`); a
# backslash-letter only in its own case (`\T` in `\Ted Lasso` is a folder's T, `\t` a tab)
_BEFORE = (r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2})|(?-i:(?<=\\[nrtbfav]))|(?<=\\x[0-9A-Fa-f]{2})"
           r"|(?<=\\u[0-9A-Fa-f]{4})|(?<=\\U[0-9A-Fa-f]{8}))")
# an Anki profile is never replaced against a deck's `::` (a profile named `Japanese` keeps `Japanese::Mining`)
_NOT_DECK = (r"(?<!::)", r"(?!::)")
_NOT_ORGS = {"personal"}            # `OneDrive - Personal`: the consumer folder beside a business one, no organisation
_AFTER = r"(?![A-Za-z0-9])"
_SEP = r"(?:\\x5c|\\u005c|%5c|%2f|\\+|/+)"
_WORD = re.compile(r"[A-Za-z0-9]+")
_LOCK_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_ESCAPE = re.compile(r"\\x[0-9a-fA-F]{2}|%[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}")
_NUL_RUN = re.compile(rb"\x00{4,}")
# the PNG chunks a picture may hold (what Qt writes, and the text ones the guard reads)
_PNG_KINDS = {b"IHDR", b"PLTE", b"IDAT", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"bKGD",
              b"tIME", b"tEXt", b"zTXt", b"iTXt"}


# --- every form a string can be written in ---------------------------------------------------------------------- #
def _hex_cases(forms):
    """Each escaped form in lower- and upper-case hex (a profile is matched case by case: its escapes must be too)."""
    def cased(case):
        def one(m):
            e = m.group(0)
            head = 1 if e[0] == "%" else 2                         # `%` / `\x` `\u` `\U` stay as written
            return e[:head] + case(e[head:])
        return one
    out = set()
    for f in forms:
        out.add(f)
        for case in (str.upper, str.lower):
            out.add(_ESCAPE.sub(cased(case), f))
    return out


def _percent(s, plus=False):
    out = []
    for b in s.encode("utf-8"):
        c = chr(b)
        if c.isascii() and (c.isalnum() or c in "-._~"):
            out.append(c)
        elif plus and c == " ":
            out.append("+")
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


def forms(s):
    """`s` and every escaped or altered form of it (§2.2), the empty string never."""
    out = set()
    for base in {unicodedata.normalize("NFC", s), unicodedata.normalize("NFD", s)}:
        if not base:
            continue
        out.add(base)
        if not base.isascii():
            out.add(json.dumps(base)[1:-1])                                 # \u00eb (a surrogate pair past U+FFFF)
            out.add(json.dumps(json.dumps(base)[1:-1])[1:-1])               # JSON in JSON: \\u00eb
            out.add(ascii(base)[1:-1])                                      # \xeb, \u7530, \U0001f600
            out.add(repr(base.encode("utf-8"))[2:-1])                       # b'\xc3\xab'
        out.add(_percent(base))
        out.add(_percent(base, plus=True))
        lock = _LOCK_UNSAFE.sub("_", base)
        if lock != base and len("".join(_WORD.findall(lock))) >= 2:          # (田中 → __ names no one: left out)
            out.add(lock)
    return {f for f in _hex_cases(out) if f}


# --- who you are ------------------------------------------------------------------------------------------------- #
class Identity:
    """The strings that name this PC's user (§2.1), as lists: `homes` (folders), `users`, `machines`, `orgs`,
    `profiles` (Anki's, in the order their placeholders count), `keys` (install keys), `telemetry`."""

    def __init__(self, homes=(), users=(), machines=(), orgs=(), profiles=(), keys=(), telemetry=()):
        def kept(values, least=1):
            seen, out = set(), []
            for v in values:
                v = unicodedata.normalize("NFC", str(v or "").strip())
                if len(v) >= least and v.casefold() not in seen:
                    seen.add(v.casefold())
                    out.append(v)
            return out
        self.homes = kept([h.rstrip("\\/") for h in homes if h], 3)
        self.users = kept(list(users) + [_last_part(h) for h in self.homes], 2)
        self.machines = kept(machines, 2)
        self.orgs = kept(orgs, 2)
        self.profiles = [p for p in dict.fromkeys(unicodedata.normalize("NFC", str(p or "").strip())
                                                  for p in profiles) if len(p) >= 2 and p != ANKI_DEFAULT]
        self.keys = kept(keys, 8)
        self.telemetry = kept(telemetry, 8)
        self._matcher = None
        self._lock = threading.Lock()

    def matcher(self):
        with self._lock:
            if self._matcher is None:
                self._matcher = _Matcher(self)
            return self._matcher

    def scrub(self, s):
        return self.matcher().scrub(s)

    def found(self, s):
        return self.matcher().found(s)


def _last_part(path):
    return re.split(r"[\\/]+", path.rstrip("\\/"))[-1] if path else ""


class _Matcher:
    """One regular expression over every form of every string, built per text from the forms the text may hold (a
    case-folded substring test first: most log lines hold none, and are given back as they are)."""

    def __init__(self, ident):
        self.literals = []                  # (form, placeholder, case_sensitive, whole_word)
        for values, place in ((ident.keys, KEY), (ident.telemetry, TELEMETRY), (ident.machines, PC),
                              (ident.orgs, ORG), (ident.users, YOU)):
            for v in values:
                whole = v.isascii()
                for f in forms(v):
                    self.literals.append((f, place, False, whole))
        for n, v in enumerate(ident.profiles, 1):
            for f in forms(v):
                self.literals.append((f, PROFILE.format(n=n), True, v.isascii()))
        self.literals.sort(key=lambda t: (-len(t[0]), t[0]))
        self.exact = {f: place for f, place, case, _w in self.literals if case}
        self.folded = {}
        for f, place, case, _w in self.literals:
            if not case:
                self.folded.setdefault(f.casefold(), place)
        self.homes = []                     # (regex source with groups h<i>, hp<i>, its last part's folded forms)
        for i, home in enumerate(sorted(ident.homes, key=len, reverse=True)):   # (a longer one first)
            self.homes.append((_home_source(home, i), {f.casefold() for f in forms(_last_part(home))}))
        self._cache = {}

    def _regex(self, s):
        low = s.casefold()
        homes = tuple(i for i, (_src, lasts) in enumerate(self.homes) if any(f in low for f in lasts))
        lits = tuple(i for i, (f, _p, _c, _w) in enumerate(self.literals) if f.casefold() in low)
        email = any(a in low for a in _ATS)
        sid = any(x in low for x in _SIDS)
        if not (homes or lits or email or sid):
            return None
        key = (homes, lits, email, sid)
        rx = self._cache.get(key)
        if rx is None:
            parts = [self.homes[i][0] for i in homes]
            if email:
                parts.append(f"(?P<email>{_EMAIL})")
            if sid:
                parts.append(f"(?P<sid>{_SID})")
            if lits:
                alts = []
                for i in lits:
                    f, _p, case, whole = self.literals[i]
                    one = re.escape(f)
                    if case:
                        one = f"{_NOT_DECK[0]}(?-i:{one}){_NOT_DECK[1]}"
                    alts.append(f"{_BEFORE}{one}{_AFTER}" if whole else one)
                parts.append("(?P<lit>" + "|".join(alts) + ")")
            rx = re.compile("|".join(parts), re.IGNORECASE)
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[key] = rx
        return rx

    def _place(self, m):
        group = m.lastgroup
        if group == "email":
            return EMAIL
        if group == "sid":
            return SID
        if group == "lit":
            t = m.group(0)
            return self.exact.get(t) or self.folded.get(t.casefold(), YOU)
        return self.scrub(m.group("hp" + group[1:])) + YOU          # a home: its parent kept, scrubbed in its turn

    def scrub(self, s):
        if not s:
            return s
        rx = self._regex(s)
        return s if rx is None else rx.sub(self._place, s)

    def found(self, s):
        """Does `s` hold any of the strings (the placeholders aside)?"""
        if not s:
            return False
        s = _PLACEHOLDER.sub("\x00", s)
        rx = self._regex(s)
        return rx is not None and rx.search(s) is not None


def _alt(strings):
    return "(?:" + "|".join(re.escape(f) for f in sorted(strings, key=lambda f: (-len(f), f))) + ")"


def _home_source(home, i):
    """A home folder as a pattern: each part of its parent in any of its forms, any separator between them, its drive
    as `C:` or `/c`; then its last part (the name) as a whole word. Groups: h<i> the whole, hp<i> what is kept."""
    parts = re.split(r"[\\/]+", home)
    pieces = []
    for part in parts[:-1]:
        if not part:
            pieces.append("")                                          # a POSIX root or a UNC path's \\
        elif re.fullmatch(r"[A-Za-z]:", part):
            d = re.escape(part[0])
            pieces.append(f"(?:{d}:|{d}%3a|/{d})")
        else:
            pieces.append(_alt(forms(part)))
    return f"(?P<h{i}>(?P<hp{i}>{_SEP.join(pieces)}{_SEP}){_alt(forms(parts[-1]))}{_AFTER})"


# --- reading this PC (each part optional) ----------------------------------------------------------------------- #
def _quiet(make, default=()):
    try:
        got = make()
        return [g for g in (got if isinstance(got, (list, tuple, set)) else [got]) if g]
    except Exception:
        return list(default)


def _short(path):
    """The 8.3 short form of a folder that exists (Windows), or None."""
    if sys.platform != "win32" or not path or not os.path.isdir(path):
        return None
    import ctypes
    from ctypes import wintypes
    f = ctypes.windll.kernel32.GetShortPathNameW
    f.argtypes, f.restype = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD), wintypes.DWORD
    buf = ctypes.create_unicode_buffer(1024)
    n = f(path, buf, 1024)
    return buf.value if 0 < n < 1024 else None


def _profile_of(path):
    """The home a per-user folder sits in: `…\\<name>\\AppData\\Roaming` → `…\\<name>`; `C:\\Users\\<name>\\…` →
    `C:\\Users\\<name>`; else None."""
    if not path:
        return None
    m = re.match(r"(?i)^(.*)[\\/]AppData(?:[\\/](?:Roaming|Local|LocalLow))?(?:[\\/]|$)", path)
    if m and m.group(1):
        return m.group(1)
    m = re.match(r"(?i)^((?:[A-Za-z]:)?[\\/](?:Users|home)[\\/][^\\/]+)", path)
    return m.group(1) if m else None


def _homes():
    env = os.environ
    found = [env.get("USERPROFILE"), env.get("HOME"), os.path.expanduser("~")]
    if env.get("HOMEDRIVE") and env.get("HOMEPATH"):
        found.append(env["HOMEDRIVE"] + env["HOMEPATH"])
    for name in ("APPDATA", "LOCALAPPDATA"):
        found.append(_profile_of(env.get(name)))

    def data_roots():
        from app import path_utils
        return [_profile_of(path_utils.persistent_root()), _profile_of(path_utils._local_data_root())]
    found += _quiet(data_roots)
    found = [h for h in found if h and h not in ("~", "/", "\\") and len(h.rstrip("\\/")) > 2]
    shorts = []
    for h in found:
        shorts += _quiet(lambda h=h: _short(h))
    return found + shorts


def _users():
    env = os.environ
    return [env.get("USERNAME"), env.get("USER"), env.get("LOGNAME")] + _quiet(getpass.getuser)


def _machines():
    env = os.environ
    names = [env.get("COMPUTERNAME")] + _quiet(socket.gethostname) + _quiet(platform.node)
    names += [n.split(".")[0] for n in names if n and "." in n]
    domain = env.get("USERDOMAIN")
    if domain and domain.casefold() != "workgroup" and domain.casefold() not in {(n or "").casefold() for n in names}:
        names.append(domain)
    return names


def _orgs(homes):
    org = re.compile(r"(?i)^OneDrive - (.+)$")
    seen = [os.environ.get(n) for n in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer")]
    for h in homes:
        seen += _quiet(lambda h=h: os.listdir(h)) if os.path.isdir(h) else []
    return [m.group(1) for m in (org.match(_last_part(s or "")) for s in seen)
            if m and m.group(1).strip().casefold() not in _NOT_ORGS]


def _anki_folder():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return os.path.join(base, "Anki2") if base else None
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Anki2")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Anki2")


def _profiles():
    out = []
    folder = _anki_folder()
    if folder and os.path.isdir(folder):
        out += sorted(d for d in os.listdir(folder) if os.path.isfile(os.path.join(folder, d, "collection.anki2")))

    def connects():
        from app.connect import setup
        return setup.read_record().get("anki_profile")
    out += _quiet(connects)

    def miners():
        from app import path_utils
        path = path_utils.get_settings_path()
        if not os.path.isfile(path):
            return None
        name = json.loads(path_utils.read_text(path)).get("connect_anki_miner_profile")
        return name if isinstance(name, str) and name.strip() != ANKI_MINER_DEFAULT else None
    out += _quiet(miners)
    return [p for p in out if isinstance(p, str)]


def _keys():
    """The four install keys, each asked of the code that makes it."""
    from app import path_utils
    keys = _quiet(path_utils.install_key)

    def instance():
        from app import instance_name
        return instance_name.install_part()
    keys += _quiet(instance)
    for language in ("ja", "zh"):
        def library(language=language):
            from app import library_store
            return library_store.library_key(path_utils.get_data_path(language))

        def bell(language=language):
            from app import library_store, library_watch
            return library_watch.bell_key(library_store.library_db_path(language, path_utils.get_data_path(language)))
        keys += _quiet(library) + _quiet(bell)
    return keys


def _telemetry():
    def read():
        from app import path_utils
        with open(os.path.join(path_utils.persistent_root(), "telemetry_id.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("uid")
    return _quiet(read)


def read_identity():
    """This PC's Identity, worked out now (a worker: it lists folders and reads two small files)."""
    homes = _homes()
    return Identity(homes=homes, users=_users(), machines=_machines(), orgs=_orgs(homes), profiles=_profiles(),
                    keys=_keys(), telemetry=_telemetry())


_CACHED = None
_CACHED_ROOT = None
_CACHING = threading.Lock()
_PICTURES = False


def identity(fresh=False):
    """This PC's Identity, kept for the window's pictures (`shown`). `fresh` (every zip, on its worker): read again
    now, so an Anki profile or Connect setup made since the window opened is known too."""
    global _CACHED, _CACHED_ROOT
    with _CACHING:
        root = os.environ.get("SURASURA_TEST_ROOT")                 # (a test's own folders: its own keys)
        if fresh or _CACHED is None or root != _CACHED_ROOT:
            _CACHED, _CACHED_ROOT = read_identity(), root
        return _CACHED


def _current():
    """The kept Identity when it is this test root's (else None): never read here."""
    got = _CACHED
    return got if got is not None and _CACHED_ROOT == os.environ.get("SURASURA_TEST_ROOT") else None


def prepare():
    """Work the Identity out on a worker (the report window, as it opens). -> the thread, or None when ready."""
    if _current() is not None:
        return None
    t = threading.Thread(target=lambda: identity().matcher(), name="scrub-identity", daemon=True)
    t.start()
    return t


def ready():
    return _current() is not None


def reset(ident=None):
    """Forget the Identity (a test: or set one)."""
    global _CACHED, _CACHED_ROOT
    with _CACHING:
        _CACHED, _CACHED_ROOT = ident, os.environ.get("SURASURA_TEST_ROOT")


def name(s, ident=None):
    """A zip entry's name scrubbed, its placeholders written `(you)`: a file name may not hold `<` or `>` (Windows
    can't extract it; open_report refuses it)."""
    return re.sub(r"<([a-z0-9 ]+)>", r"(\1)", (ident or identity()).scrub(s))


def text(s, ident=None):
    """`s` with every string that names you written as its placeholder."""
    return (ident or identity()).scrub(s)


def found(s, ident=None):
    return (ident or identity()).found(s)


@contextlib.contextmanager
def picture_mode():
    """While a picture is taken: `shown` scrubs. Only when the Identity is ready (else the picture is not marked
    scrubbed, and never sent)."""
    global _PICTURES
    was, _PICTURES = _PICTURES, True
    try:
        yield ready()
    finally:
        _PICTURES = was


def shown(s):
    """What a painted widget draws: `s` scrubbed while a picture is taken (never waiting for the Identity), else `s`."""
    ident = _current() if _PICTURES and isinstance(s, str) else None
    return s if ident is None else ident.scrub(s)


# --- reading an entry as text ----------------------------------------------------------------------------------- #
def decode(raw, language=None):
    """The bytes' text, or None when it can't be read whole as text: a BOM's encoding; bytes holding a NUL read only
    as UTF-16 (LE or BE by where the NULs sit; BOM-less UTF-16 is valid UTF-8 full of NULs), never a text with a NUL
    in it; else UTF-8, then CP932 (ja) / GB18030, cp950 (zh) — `path_utils`' order. Line ends are kept."""
    from app import path_utils
    if b"\x00\x00\x00\x00" in raw and not path_utils._bom_encoding(raw):
        padded = _NUL_RUN.sub(b"", raw)                              # a log a crash left NUL-padded: its text
        if b"\x00" not in padded:
            raw = padded
    if path_utils._bom_encoding(raw):
        text = path_utils._decoding(raw, language)[0]
    elif b"\x00" in raw:
        odd, even = raw[1::2].count(0), raw[0::2].count(0)
        if len(raw) % 2 or 2 * max(odd, even) <= len(raw) // 2:         # UTF-16 text: mostly NULs on one side
            return None
        try:
            text = raw.decode("utf-16-le" if odd > even else "utf-16-be")
        except UnicodeDecodeError:
            return None
    else:
        text = path_utils._decoding(raw, language)[0]
    if text is None or "\x00" in text:
        return None
    return text


def clean(raw, language=None, ident=None):
    """A text entry's bytes scrubbed -> UTF-8 bytes, or None when they aren't text (`decode`). Bytes that aren't
    UTF-8 whole are scrubbed as UTF-8 first (each undecodable byte kept as it is), then read in the language's
    encoding and scrubbed again: a log of mostly UTF-8 with one stray byte would otherwise be read whole as CP932 /
    GB18030, and a UTF-8 `Zoë` or `田中` in it would be garbled past the scrub (its garbling undone gives it back)."""
    from app import path_utils
    ident = ident or identity()
    if b"\x00" not in raw and not path_utils._bom_encoding(raw):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = ident.scrub(raw.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
    text = decode(raw, language)
    return None if text is None else ident.scrub(text).encode("utf-8")


def _views(text, language):
    """`text` and the UTF-8 its legacy-encoding reading garbled (for the guard: a garbled name read back)."""
    from app import path_utils
    out = [text]
    for encoding in path_utils.LEGACY_ENCODINGS.get(language) or sum(path_utils.LEGACY_ENCODINGS.values(), ()):
        back = text.encode(encoding, "replace").decode("utf-8", "replace")
        if back and back != text:
            out.append(back)
    return out


def _both(raw):
    """A PNG text chunk's bytes read as Latin-1 (the format's) and as UTF-8 (what some writers put there)."""
    return raw.decode("latin-1") + "\n" + raw.decode("utf-8", "replace")


def _png_text(data):
    """A PNG's text chunks (tEXt, zTXt, iTXt), or None when it isn't a whole PNG."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    out, at = [], 8
    try:
        while at + 8 <= len(data):
            n, kind = struct.unpack(">I4s", data[at:at + 8])
            body = data[at + 8:at + 8 + n]
            if kind == b"tEXt":
                out.append(_both(body))
            elif kind == b"zTXt":
                k, _, rest = body.partition(b"\x00")
                out.append(_both(k) + " " + _both(zlib.decompress(rest[1:])))
            elif kind == b"iTXt":
                k, _, rest = body.partition(b"\x00")
                flag, rest = rest[0], rest[2:]
                lang, _, rest = rest.partition(b"\x00")
                tkey, _, value = rest.partition(b"\x00")
                value = zlib.decompress(value) if flag else value
                out.append(" ".join(p.decode("utf-8", "replace") for p in (k, lang, tkey, value)))
            elif kind == b"IEND":
                return "\n".join(out) if at + 12 + n == len(data) else None      # (nothing after its end)
            elif kind not in _PNG_KINDS:
                return None                                               # a chunk it can't read: not checked
            at += 12 + n
    except (struct.error, zlib.error, IndexError):
        return None
    return None


def leaks(zip_path, ident=None, language=None):
    """The guard: the names of the zip's entries whose name or bytes hold any string of the Identity in any form
    (UTF-8 and the other encodings `decode` reads, and the raw bytes as UTF-16LE at both alignments); a picture is
    searched in its text chunks. An entry that can't be read as either is a hit (it couldn't be checked)."""
    ident = ident or identity()
    hits = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            data = z.read(info)
            if ident.found(name):
                hits.append(name)
                continue
            if name.lower().endswith(".png"):
                text = _png_text(data)
                if text is None or ident.found(text):
                    hits.append(name)
                continue
            text = decode(data, language)
            if text is None or any(ident.found(v) for v in _views(text, language)) or any(
                    ident.found(codecs.decode(data[i:len(data) - ((len(data) - i) % 2)], "utf-16-le", "ignore"))
                    for i in (0, 1)):
                hits.append(name)
    return hits
