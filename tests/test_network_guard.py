"""The network socket guard (W2.1; the window's spec 07 §7.3; tests/network_guard.py).

What a wrong answer would cost: a guard that lets an address through means a test quietly spends the developer's
network (the update check once spent the anonymous GitHub quota from every dashboard test); one that blocks loopback
breaks every AnkiConnect fake, Koe's helper and asyncio's socket pair.
"""
import os
import socket
import subprocess
import sys
import threading

import pytest

from tests.network_guard import Guard, NetworkRefused, _is_loopback


def test_loopback_connections_go_through(network_guard):
    # A tiny server on 127.0.0.1, reached by address and by "localhost" (the AnkiConnect fakes' way).
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(2)
    port = server.getsockname()[1]
    accepted = []
    t = threading.Thread(target=lambda: [accepted.append(server.accept()[0]) for _ in range(2)], daemon=True)
    t.start()
    try:
        socket.create_connection(("127.0.0.1", port), timeout=5).close()
        socket.create_connection(("localhost", port), timeout=5).close()
        t.join(5)
    finally:
        for s in accepted:
            s.close()
        server.close()
    assert len(accepted) == 2
    assert network_guard.attempts == []


def test_an_outside_address_is_refused_as_the_app_meets_it_offline(network_guard):
    # The refusal is an OSError (the app's own offline path catches it), and it is remembered for the test's end.
    with pytest.raises(OSError) as caught:
        socket.create_connection(("93.184.215.14", 80), timeout=5)
    assert isinstance(caught.value, NetworkRefused)
    assert "93.184.215.14" in str(caught.value)
    assert network_guard.attempts == [("a connection to", ("93.184.215.14", 80))]
    network_guard.forgive()


def test_a_name_lookup_past_this_machine_is_refused(network_guard):
    with pytest.raises(OSError):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(OSError):
        socket.gethostbyname("api.github.com")
    assert [what for what, _ in network_guard.attempts] == ["a name lookup of", "a name lookup of"]
    network_guard.forgive()


def test_an_ipv6_outside_address_is_refused_and_ipv6_loopback_is_not(network_guard):
    assert _is_loopback("::1") and _is_loopback("[::1]") and _is_loopback("127.0.0.53")
    assert not _is_loopback("2606:4700:4700::1111") and not _is_loopback("0.0.0.0")
    assert not _is_loopback("example.com") and _is_loopback("LOCALHOST")
    if not socket.has_ipv6:
        pytest.skip("no IPv6 on this machine")
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkRefused):
            sock.connect(("2606:4700:4700::1111", 443, 0, 0))
    finally:
        sock.close()
    network_guard.forgive()


def test_every_test_runs_under_the_guard(request):
    # This test names no guard fixture: the suite's autouse guard is on anyway (a lookup past the machine is refused).
    assert "connect" in socket.socket.__dict__
    with pytest.raises(OSError):
        socket.getaddrinfo("example.net", 80)
    request.getfixturevalue("network_guard").forgive()       # the same, already-running guard


@pytest.fixture
def forgiving(network_guard):
    yield
    network_guard.forgive()


def test_the_guard_comes_off_cleanly(forgiving):
    # A guard installed over the suite's and removed leaves the suite's exactly in place (guards nest), and a guard
    # removed from a bare socket module leaves nothing of itself on the class or the module.
    outer = (socket.socket.__dict__["connect"], socket.getaddrinfo, socket.gethostbyname)
    g = Guard().install()
    assert socket.socket.__dict__["connect"] is not outer[0]
    g.uninstall()
    assert (socket.socket.__dict__["connect"], socket.getaddrinfo, socket.gethostbyname) == outer


def test_a_refusal_left_unforgiven_fails_the_test(tmp_path):
    # The end-of-test check is what catches a test that went quiet offline: run one such test in a child pytest,
    # under the suite's own fixture body (tests/network_guard.around_a_test, which tests/conftest.py yields from).
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conftest = ["import pytest", "from tests.network_guard import around_a_test", "@pytest.fixture(autouse=True)",
                "def network_guard():", "    yield from around_a_test()"]
    offline = ["import socket", "def test_quietly_offline():", "    try:",
               "        socket.getaddrinfo('telemetry.example.org', 443)", "    except OSError:", "        pass"]
    (tmp_path / "conftest.py").write_text("\n".join(conftest) + "\n", encoding="utf-8")
    (tmp_path / "test_offline.py").write_text("\n".join(offline) + "\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=root)
    proc = subprocess.run([sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:cacheprovider",
                           "--rootdir", str(tmp_path)], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode != 0
    assert "1 passed, 1 error" in proc.stdout
    assert "a test tried to reach past this machine" in proc.stdout and "telemetry.example.org" in proc.stdout
