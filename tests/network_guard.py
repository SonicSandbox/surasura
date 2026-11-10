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

_LOCAL_NAMES = {"localhost"}         # the one name Windows answers itself; any other goes to DNS (review A8)
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


# What the guard replaces: on socket.socket (inherited from the C type, so the guard's own sit on the Python class, where
# ssl.SSLSocket's super() finds them) and in the socket module; asyncio's Windows loop connects through its proactor,
# never socket.connect, so its door is guarded too (W2.1 review A8).
_ON_CLASS = tuple(n for n in ("connect", "connect_ex", "sendto", "sendmsg") if hasattr(socket.socket, n))
_IN_MODULE = tuple(n for n in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo")
                   if hasattr(socket, n))


def _proactor():
    try:
        import asyncio.windows_events as we
        return we.IocpProactor
    except ImportError:                      # not Windows
        return None


class Guard:
    def __init__(self):
        self.attempts = []                   # (what, address) refused during the test
        self._saved = None

    def install(self):
        real = {n: getattr(socket.socket, n) for n in _ON_CLASS}
        real_mod = {n: getattr(socket, n) for n in _IN_MODULE}
        proactor = _proactor()
        real_proactor_connect = proactor.connect if proactor is not None else None
        guard = self

        def refused(what, address):
            guard.attempts.append((what, address))
            return NetworkRefused(f"the test suite's network guard refused {what} {address!r}: tests stay on "
                                  f"this machine (loopback only)")

        def check_address(family, address, what="a connection to"):
            if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
                if not _is_loopback(address[0]):
                    raise refused(what, address)

        def connect(sock, address):
            check_address(sock.family, address)
            return real["connect"](sock, address)

        def connect_ex(sock, address):
            check_address(sock.family, address)
            return real["connect_ex"](sock, address)

        def sendto(sock, data, *rest):
            check_address(sock.family, rest[-1] if rest else None, "a datagram to")
            return real["sendto"](sock, data, *rest)

        def sendmsg(sock, buffers, *rest):
            if len(rest) >= 3:
                check_address(sock.family, rest[2], "a datagram to")
            return real["sendmsg"](sock, buffers, *rest)

        def lookup(name, numeric_ok):
            fn = real_mod[name]

            def guarded(host, *args, **kwargs):
                # A numeric address asks nothing of the network (the connection that follows is what is refused).
                if not _is_loopback(host) and not (numeric_ok and _is_numeric(host)):
                    raise refused("a name lookup of", host)
                return fn(host, *args, **kwargs)
            return guarded

        def getnameinfo(sockaddr, flags):
            if isinstance(sockaddr, tuple) and not _is_loopback(sockaddr[0]):
                raise refused("a name lookup of", sockaddr)
            return real_mod["getnameinfo"](sockaddr, flags)

        def proactor_connect(self_, conn, address):
            check_address(conn.family, address)
            return real_proactor_connect(self_, conn, address)

        self._saved = ({n: socket.socket.__dict__.get(n, _ABSENT) for n in _ON_CLASS}, real_mod,
                       (proactor, proactor.__dict__.get("connect", _ABSENT)) if proactor is not None else None)
        for name, fn in (("connect", connect), ("connect_ex", connect_ex), ("sendto", sendto),
                         ("sendmsg", sendmsg)):
            if name in _ON_CLASS:                    # (Windows has no sendmsg)
                setattr(socket.socket, name, fn)
        socket.getaddrinfo = lookup("getaddrinfo", True)
        socket.gethostbyname = lookup("gethostbyname", False)
        socket.gethostbyname_ex = lookup("gethostbyname_ex", False)
        socket.gethostbyaddr = lookup("gethostbyaddr", False)
        socket.getnameinfo = getnameinfo
        if proactor is not None:
            proactor.connect = proactor_connect
        return self

    def uninstall(self):
        if self._saved is None:
            return
        on_class, module, proactor = self._saved
        for name, before in on_class.items():
            if before is _ABSENT:
                if name in socket.socket.__dict__:
                    delattr(socket.socket, name)
            else:
                setattr(socket.socket, name, before)
        for name, fn in module.items():
            setattr(socket, name, fn)
        if proactor is not None:
            cls, before = proactor
            if before is _ABSENT:
                delattr(cls, "connect")
            else:
                cls.connect = before
        self._saved = None

    def forgive(self, address=None):
        """Forget the refusals a test provoked on purpose: those of `address` (a host or an address tuple), or all."""
        if address is None:
            self.attempts.clear()
        else:
            self.attempts[:] = [(w, a) for w, a in self.attempts
                                if a != address and not (isinstance(a, tuple) and a and a[0] == address)]


def around_a_test():
    """The fixture's body (tests/conftest.py `network_guard`): the guard on for one test, and the test failed at its
    end if it tried to leave the machine and nobody forgave it."""
    guard = Guard().install()
    try:
        yield guard
    finally:
        guard.uninstall()
    assert not guard.attempts, f"a test tried to reach past this machine: {guard.attempts}"
