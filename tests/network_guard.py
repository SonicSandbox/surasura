"""The network socket guard (W2.1; the window's spec 07 §7.3): a test reaches nothing but this machine.

Surasura is local and offline by default (CLAUDE.md §1); its tests must be too. Every core test runs with this guard
(tests/conftest.py installs it around each test): a connection to an address that isn't loopback, or a name lookup of a
host that isn't this machine, is refused and remembered, and the test fails at its end naming the address. Loopback
stays open — the AnkiConnect fakes, Koe's helper, a test's own little HTTP server, asyncio's socket pair.

Why refuse AND fail: the refusal is an `OSError`, the error the app already meets offline, so the code under test
degrades exactly as it would without a network (an update check gives up, telemetry drops its beat); the failure at
the end is what tells the developer a test tried to leave the machine — a quiet offline path would hide it forever.

A test that must see the refusal itself (the guard's own tests) reads `guard.attempts` and calls `guard.forgive()`.
"""
import ipaddress
import socket

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_ABSENT = object()


class NetworkRefused(ConnectionRefusedError):
    """A test tried to reach past this machine (refused by the test suite's network guard)."""


def _is_loopback(host):
    if host is None or host == "":
        return True                          # a passive lookup (bind to any interface): nothing leaves the machine
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").split("%", 1)[0]
    if host.lower() in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False                         # a name: only the local names above are this machine


def _is_numeric(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        ipaddress.ip_address(str(host).strip("[]").split("%", 1)[0])
        return True
    except ValueError:
        return False


class Guard:
    def __init__(self):
        self.attempts = []                   # (what, address) refused during the test
        self._saved = None

    def install(self):
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_getaddrinfo = socket.getaddrinfo
        real_gethostbyname = socket.gethostbyname
        guard = self

        def refused(what, address):
            guard.attempts.append((what, address))
            return NetworkRefused(f"the test suite's network guard refused {what} {address!r}: tests stay on "
                                  f"this machine (loopback only)")

        def check_address(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
                if not _is_loopback(address[0]):
                    raise refused("a connection to", address)

        def connect(sock, address):
            check_address(sock, address)
            return real_connect(sock, address)

        def connect_ex(sock, address):
            check_address(sock, address)
            return real_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            # A numeric address asks nothing of the network (the connection that follows is what the guard refuses).
            if not _is_loopback(host) and not _is_numeric(host):
                raise refused("a name lookup of", host)
            return real_getaddrinfo(host, *args, **kwargs)

        def gethostbyname(host):
            if not _is_loopback(host):
                raise refused("a name lookup of", host)
            return real_gethostbyname(host)

        # socket.socket inherits connect / connect_ex from the C type; the guard's own go on the Python class (where
        # ssl.SSLSocket's super().connect finds them too). What was on the class before (nothing, or an outer guard's)
        # is put back exactly, so guards nest.
        self._saved = ({n: socket.socket.__dict__.get(n, _ABSENT) for n in ("connect", "connect_ex")},
                       real_getaddrinfo, real_gethostbyname)
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname
        return self

    def uninstall(self):
        if self._saved is None:
            return
        on_class, socket.getaddrinfo, socket.gethostbyname = self._saved
        for name, before in on_class.items():
            if before is _ABSENT:
                if name in socket.socket.__dict__:
                    delattr(socket.socket, name)
            else:
                setattr(socket.socket, name, before)
        self._saved = None

    def forgive(self):
        """Forget the refusals so far (a test that provoked them on purpose)."""
        self.attempts.clear()


def around_a_test():
    """The fixture's body (tests/conftest.py `network_guard`): the guard on for one test, and the test failed at its
    end if it tried to leave the machine and nobody forgave it."""
    guard = Guard().install()
    try:
        yield guard
    finally:
        guard.uninstall()
    assert not guard.attempts, f"a test tried to reach past this machine: {guard.attempts}"
