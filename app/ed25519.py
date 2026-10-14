"""Ed25519 signatures (RFC 8032 §5.1), standard library only: the update check verifies a release's update.json with
it, and `package_app.py --release` signs one (S3.1 D6). Built from the RFC's own reference code (§6), with its test
vectors as tests (tests/test_ed25519.py). Not constant-time: it signs on the release machine only, and verifying needs
no secret.

    sign(seed, message)            -> the 64-byte signature (seed: the 32-byte private key)
    public_key(seed)               -> the 32-byte public key
    verify(public, message, sig)   -> True / False; never raises on a malformed key or signature
"""
import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493       # the group order (the RFC's q)
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512_int(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


# Points in extended homogeneous coordinates (X, Y, Z, T), x = X/Z, y = Y/Z, x*y = T/Z (RFC 8032 §5.1.4).
def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)                                          # the neutral element
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(p):
    zinv = pow(p[2], _P - 2, _P)
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(seed):
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes")
    h = hashlib.sha512(bytes(seed)).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """The 32-byte public key of a 32-byte private key (seed)."""
    a, _prefix = _expand(seed)
    return _compress(_mul(a, _G))


def sign(seed, message):
    """The 64-byte Ed25519 signature of `message` (bytes) by the 32-byte private key `seed`."""
    a, prefix = _expand(seed)
    message = bytes(message)
    pub = _compress(_mul(a, _G))
    r = _sha512_int(prefix + message) % _L
    rs = _compress(_mul(r, _G))
    h = _sha512_int(rs + pub + message) % _L
    s = (r + h * a) % _L
    return rs + s.to_bytes(32, "little")


def verify(public, message, signature):
    """Is `signature` a valid Ed25519 signature of `message` by `public`? Any malformed input is False, never an
    exception: a 32-byte key and a 64-byte signature whose R decodes and whose S is below the group order."""
    try:
        public, message, signature = bytes(public), bytes(message), bytes(signature)
    except (TypeError, ValueError):
        return False
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = _sha512_int(signature[:32] + public + message) % _L
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))
