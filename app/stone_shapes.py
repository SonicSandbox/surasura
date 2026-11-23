"""The string's stones as geometry: Qt-free (journey v3 SPEC §2.4, *decided*; Charter S17), so the window's sheet
(`app/qt/stones.py`, which paints these display lists into its QImage atlas) and the journey's headless render (its
SVG pictures, `app/journey_render.py`) draw one stone from one recipe, and the render never imports PyQt6.

The redesign's gem kit (Design Doctrine `trials/surasura-2026-10-09/worlds/gem-kit.js`, and the trillion ▶ of
`list-r14m.html` L2735–2760) as flat facets: one colour per facet as the kit's recipe works it out, **no filter,
turbulence, gradient shade, bezel, glow or blur**. Its randomness is the kit's own — FNV-1a over the seed's text, then
mulberry32, bit-exact, with the kit's salts (1 structure, 2 character, 3 the ore's cut points) — so a stone here is the
stone the reference page draws for the same seed. `pictures()` lists every picture a sheet holds, in the kit's units.

**Pre-studied, added** (J-STONES; SPEC §2.4, the mock's round 9): never a state of its own — a cool sheen over the
stone's top, clipped to its own outline (the mock's gradient as a few flat bands), and a small four-point sparkle at its
shoulder, drawn outside the stone's box so the string never moves. A cut group and the ore carry the sparkle alone, at
their shoulder; a row with no stone of its own, the sparkle alone (`("pre", "spark")`).
"""
import math

from app import theme

# --- Colours the recipe fixes: theme.STONE ----------------------------------------------------------------------- #
def _fixed(name):
    r, g, b, _a = theme.parse(theme.STONE[name])
    return (int(r), int(g), int(b))


# The string keeps the reference's own size at every text size (list-r14m draws it in plain px: the twelve then fits
# one line at 1024 Medium; the text around it still follows the text size). One sheet per device-pixel ratio.
FOLLOWS_TEXT_SIZE = False


def _rgb(hex_colour):
    r, g, b, _a = theme.parse(hex_colour)
    return (int(r), int(g), int(b))


def _mix(a, b, t):
    """gem-kit's `mix`: a per-channel RGB lerp, rounded as JavaScript's Math.round (half up)."""
    return tuple(int(math.floor(x + (y - x) * t + 0.5)) for x, y in zip(a, b))


def _gem(gem):
    return tuple(_rgb(h) for h in theme.GEM[gem])            # base, light, edge


# --- The kit's randomness (bit-exact) ------------------------------------------------------------------------------ #
_U32 = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & _U32


def _seed_text(seed):
    """JavaScript's String(seed) for the seeds used here (whole numbers and text)."""
    if isinstance(seed, float) and seed.is_integer():
        return str(int(seed))
    return str(seed)


def hash_seed(seed, salt):
    """gem-kit's `hash`: FNV-1a over the seed's UTF-16 code units, salted, then an avalanche."""
    h = (2166136261 ^ _imul(salt + 1, 0x9E3779B1)) & _U32
    data = _seed_text(seed).encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = _imul(h, 16777619)
    h ^= h >> 16
    h = _imul(h, 0x85EBCA6B)
    h ^= h >> 13
    h = _imul(h, 0xC2B2AE35)
    h ^= h >> 16
    return h


def _mulberry(a):
    state = [a & _U32]

    def nxt():
        a = state[0] = (state[0] + 0x6D2B79F5) & _U32
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _U32) ^ t
        return ((t ^ (t >> 14)) & _U32) / 4294967296

    return nxt


def prng(seed, salt):
    """gem-kit's `prng`: a function giving the seed's numbers in 0…1, in the kit's order."""
    return _mulberry(hash_seed(seed, salt))


def seed_of(text):
    """list-r14m's `seedOf` (the trillion's seed): 1…9973 from a text's characters."""
    h = 7
    for ch in str(text):
        code = ord(ch)
        if code > 0xFFFF:                                     # charCodeAt(0) of a code point: its high surrogate
            code = 0xD800 + ((code - 0x10000) >> 10)
        h = (h * 31 + code) % 9973
    return h + 1


def character(seed):
    """gem-kit's `character`: rot, sx, sy, side, taper, shear and v[56], each −1…1."""
    r = prng(seed, 2)
    g = [r() * 2 - 1 for _ in range(62)]
    return {"rot": g[0], "sx": g[1], "sy": g[2], "side": g[3], "taper": g[4], "shear": g[5], "v": g[6:]}


def warp(c, A, H):
    """gem-kit's whole-stone warp: one side wider, a taper, a lean, width-to-height, a few degrees of tilt."""
    a = c["rot"] * 8 * A * math.pi / 180
    cs, sn = math.cos(a), math.sin(a)
    sx, sy = 1 + c["sx"] * .16 * A, 1 + c["sy"] * .1 * A
    side, taper, shear = c["side"] * .22 * A, c["taper"] * .22 * A, c["shear"] * .14 * A

    def w(p):
        x, y = p[0], p[1]
        x *= 1 + side if x > 0 else 1 - side
        x *= 1 + taper * y / H
        x += shear * y
        x *= sx
        y *= sy
        q = [x * cs - y * sn, x * sn + y * cs]
        if len(p) > 2:
            q.append(p[2])
        return q

    return w


def _centroid(P):
    A = x = y = 0.0
    for i, p in enumerate(P):
        q = P[(i + 1) % len(P)]
        k = p[0] * q[1] - q[0] * p[1]
        A += k
        x += (p[0] + q[0]) * k
        y += (p[1] + q[1]) * k
    return [x / (3 * A), y / (3 * A)] if A else [0.0, 0.0]


# --- The shapes ------------------------------------------------------------------------------------------------------ #
def _point_pts(w, h):
    return [[0, -h / 2], [w / 2, -h / 2 + w * .5], [w / 2, h / 2 - w * .35], [0, h / 2], [-w / 2, h / 2 - w * .35],
            [-w / 2, -h / 2 + w * .5]]


def _hex_pts(w, h):
    return [[0, -h / 2], [w / 2, -h / 4], [w / 2, h / 4], [0, h / 2], [-w / 2, h / 4], [-w / 2, -h / 4]]


def _jit(P, amt, r):
    out = []
    for p in P:
        x = p[0] + (r() - .5) * 2 * amt
        out.append([x, p[1] + (r() - .5) * 2 * amt])
    return out


def _point_shape(w, h, c, A):
    v, P = c["v"], _point_pts(w, h)
    P[0][0] += v[0] * w * .18 * A
    P[1][1] += v[1] * h * .1 * A
    P[5][1] += v[2] * h * .1 * A
    P[2][1] += v[3] * h * .08 * A
    P[4][1] += v[4] * h * .08 * A
    P[3][0] += v[5] * w * .14 * A
    M1 = [v[6] * w * .2 * A, -h / 2 + w * .62 + v[7] * h * .06 * A]
    M2 = [v[8] * w * .2 * A, h / 2 - w * .45 + v[9] * h * .06 * A]
    W = warp(c, A, h / 2)
    return {"P": [W(p) for p in P], "M1": W(M1), "M2": W(M2)}


def _hex_shape(w, h, c, A):
    v = c["v"]
    P = []
    for i, p in enumerate(_hex_pts(w, h)):
        k = 1 + v[10 + i] * .08 * A
        P.append([p[0] * k, p[1] * k])
    P[0][0] += v[16] * w * .1 * A
    P[3][0] += v[17] * w * .1 * A
    P[1][1] += v[18] * h * .08 * A
    P[5][1] += v[19] * h * .08 * A
    P[2][1] += v[20] * h * .08 * A
    P[4][1] += v[21] * h * .08 * A
    W = warp(c, A, h / 2)
    C = W([v[22] * w * .16 * A, v[23] * h * .12 * A])
    return {"P": [W(p) for p in P], "M1": C, "M2": C}


def _oct_shape(D, c, A):
    a, v = D / 2, c["v"]
    R = a / math.cos(math.pi / 8)

    def ang(k):
        return math.pi / 8 + k * math.pi / 4

    tc = [v[24] * a * .22 * A, v[25] * a * .18 * A]
    ts, tw = 1 + v[26] * .14 * A, v[27] * .2 * A
    O, I, S = [], [], []
    for k in range(8):
        t = ang(k) + v[28 + k] * .12 * A
        ro = R * (1 + v[36 + k] * .07 * A)
        u = ang(k) + math.pi / 8 + v[44 + k] * .1 * A
        O.append([math.cos(t) * ro, math.sin(t) * ro, 0])
        I.append([tc[0] + math.cos(ang(k) + tw) * R * .56 * ts, tc[1] + math.sin(ang(k) + tw) * R * .56 * ts, a * .3])
        S.append([tc[0] * .5 + math.cos(u) * a * .8, tc[1] * .5 + math.sin(u) * a * .8, a * .13])
    W = warp(c, A, a)
    return {"O": [W(p) for p in O], "I": [W(p) for p in I], "S": [W(p) for p in S]}


# --- Light: flat planes lit from the top-left, a little in front ---------------------------------------------------- #
_L3 = tuple(x / math.hypot(-.55, -.75, .85) for x in (-.55, -.75, .85))


def _normal(P):
    n = [0.0, 0.0, 0.0]
    for i, a in enumerate(P):
        b = P[(i + 1) % len(P)]
        az, bz = (a[2] if len(a) > 2 else 0), (b[2] if len(b) > 2 else 0)
        n[0] += (a[1] - b[1]) * (az + bz)
        n[1] += (az - bz) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    if n[2] < 0:
        n = [-x for x in n]
    l_ = math.hypot(*n) or 1
    return [x / l_ for x in n]


def _tone(P):
    n = _normal(P)
    return (n[0] * _L3[0] + n[1] * _L3[1] + n[2] * _L3[2] + .1) / 1.1


def _ramp(stops, t):
    t = min(1, max(0, t)) * (len(stops) - 1)
    i = min(len(stops) - 2, int(math.floor(t)))
    return _mix(stops[i], stops[i + 1], t - i)


# --- The display list: what a picture draws, in the kit's own units -------------------------------------------------- #
# ("fill", pts, rgb, alpha) · ("plane", pts, rgb, stroke width) — filled and stroked in one colour, round joins ·
# ("line", pts, rgb, alpha, width, closed, join, cap) · ("clip", [pts, …]) · ("unclip",) · ("text", x, baseline, size,
# text, fill rgb, stroke rgb, stroke alpha, stroke width) · ("circle", cx, cy, r, rgb, width)
MITER, ROUND, BEVEL = "miter", "round", "bevel"


def _line(pts, rgb, alpha, width, closed=True, join=MITER, cap="butt"):
    return ("line", pts, rgb, alpha, width, closed, join, cap)


def _point_faces(S, base, light, edge):
    T, UR, LR, B, LL, UL = S["P"]
    M1, M2 = S["M1"], S["M2"]
    dark = _mix(base, _fixed("black"), .35)
    return [("fill", [T, UL, M1], edge, .95), ("fill", [T, UR, M1], light, 1.0), ("fill", [UL, LL, M2, M1], light, 1.0),
            ("fill", [UR, LR, M2, M1], base, 1.0), ("fill", [LL, B, M2], base, 1.0), ("fill", [LR, B, M2], dark, 1.0),
            _line(S["P"], edge, .5, .6, join=ROUND), _line([T, UL], _fixed("white"), .7, .6, closed=False)]


def _oct_faces(G, base, light, edge):
    O, I, S = G["O"], G["I"], G["S"]
    stops = [_mix(base, _fixed("black"), .35), base, light, edge]
    ops = []

    def face(F):
        ops.append(("plane", F, _ramp(stops, _tone(F)), .3))

    for k in range(8):
        k1, k0 = (k + 1) % 8, (k + 7) % 8
        face([I[k], I[k1], S[k]])
        face([I[k], S[k], O[k], S[k0]])
        face([S[k], O[k1], O[k]])
    face(I)
    ops.append(_line(O, edge, .5, .6, join=ROUND))
    ops.append(_line([O[4], O[5]], _fixed("white"), .7, .6, closed=False))
    return ops


def _rock_pts(w, h, r):
    out = []
    for i in range(7):
        t = -math.pi / 2 + 2 * math.pi * i / 7
        k = .82 + r() * .32
        out.append([math.cos(t) * w * .6 * k, math.sin(t) * h * .5 * k])
    return out


def _rock_faces(P, c):
    L = (-.55, -.83)
    dark, lit = _fixed("rock-dark"), _fixed("rock-lit")
    ops = []
    for i, v in enumerate(P):
        w = P[(i + 1) % len(P)]
        m = [(v[0] + w[0]) / 2 - c[0], (v[1] + w[1]) / 2 - c[1]]
        n = math.hypot(m[0], m[1]) or 1
        ops.append(("fill", [c, v, w], _mix(dark, lit, .5 + .5 * (m[0] / n * L[0] + m[1] / n * L[1])), 1.0))
    ops.append(_line(P, _fixed("rock-rim"), 1.0, .6))
    return ops


def _raw_faces(P, base, light):
    return [("fill", [P[0], P[3], P[4], P[5]], _mix(light, _fixed("raw-pale"), .45), .32),
            ("fill", [P[0], P[1], P[2], P[3]], _mix(base, _fixed("raw-shade"), .45), .5),
            _line(P, light, .45, .7), _line([P[0], P[3]], light, .3, .5, closed=False)]


def _label(base, fs, x, y, text):
    return ("text", x, y, fs, str(text), _fixed("white"), _mix(base, _fixed("black"), .6), .8, 2.2)


def _on_line(P):
    xs, ys = [p[0] for p in P], [p[1] for p in P]
    d = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    return [[p[0] - d[0], p[1] - d[1]] for p in P], d


SINGLE = 1.25          # a single stone's imperfection runs stronger (gem-kit `SINGLE`)
IMP = .7               # the reference page's imperfection (`IMP`, his "strong"): A = .875 for a single, .7 otherwise
BLOCK = 12


def stone_ops(state, gem, seed):
    """One episode (gem-kit `stone`, finish a): 'rock' (not in Anki) · 'raw' (in Anki) · 'cut' (watched)."""
    base, light, edge = _gem(gem)
    A, c, r = IMP * SINGLE, character(seed), prng(seed, 1)
    if state == "rock":
        W = warp(c, A, 7.5)
        P, d = _on_line([W(p) for p in _rock_pts(13, 15, r)])
        f = W([-1, -1.4])
        return _rock_faces(P, [f[0] - d[0], f[1] - d[1]])
    if state == "raw":
        W = warp(c, A, 8.5)
        return _raw_faces(_on_line([W(p) for p in _jit(_point_pts(11, 17), .7, r)])[0], base, light)
    return _point_faces(_point_shape(11, 17, c, A), base, light, edge)


def group_scale(n):
    return 1 if n >= BLOCK else .6 + .4 * math.sqrt(max(0, n - 1) / (BLOCK - 1))


def _tier_scale(n, T):
    if T == 12:
        return group_scale(n)
    return 1 if n >= T else .8 + .2 * math.sqrt(max(1, n) / T)


def group_ops(gem, tier, seed, n=None):
    """Watched episodes fused into one cut gem (gem-kit `cut`), its count in the centre (bare when not whole)."""
    base, light, edge = _gem(gem)
    A, c = IMP, character(seed)
    tier = tier if tier in (60, 120) else 12
    n = tier if n is None else n
    sc = _tier_scale(n, tier)
    if tier == 12:
        w, h = 24 * sc, 36 * sc
        S = _point_shape(w, h, c, A)
        ops, fs = _point_faces(S, base, light, edge), 10.4 * max(.8, sc)
        c0, c1 = _centroid(_point_pts(w, h)), _centroid(S["P"])
        at = [c1[0] - c0[0], 2 * sc + c1[1] - c0[1]]
    elif tier == 60:
        S = _hex_shape(40 * sc, 46 * sc, c, A)
        ops, fs, at = _point_faces(S, base, light, edge), 12.6 * max(.85, sc), _centroid(S["P"])
    else:
        G = _oct_shape(46 * sc, c, A)
        ops, fs, at = _oct_faces(G, base, light, edge), 12.6 * max(.85, sc), _centroid([p[:2] for p in G["O"]])
    if n in (12, 60, 120):
        ops.append(_label(base, fs, at[0], at[1] + fs * .36, n))
    return ops


# --- The ore: the still-to-come stone (gem-kit `ore`, the page's variation 3: size × .78) --------------------------- #
ORE_CAP = 300
ORE_V_SIZE = .78


def _ore_t(n):
    return 0 if n < BLOCK else min(1, math.log(n / BLOCK) / math.log(ORE_CAP / BLOCK))


def ore_size(n):
    n = max(1, n)
    if n < BLOCK:
        s = group_scale(n)
        return 28 * s, 34 * s
    t = _ore_t(n)
    return 28 + 12 * t, 34 + 12 * t


def _ore_geom(w, h, r, N=7, lean=.2):
    P = []
    for i in range(N):
        t = -math.pi / 2 + 2 * math.pi * (i + (r() - .5) * .5) / N
        k = .8 + r() * .24
        y = math.sin(t) * k
        P.append([math.cos(t) * k + y * lean, y])
    xs, ys = [p[0] for p in P], [p[1] for p in P]
    x0, x1, y0, y1, d = min(xs), max(xs), min(ys), max(ys), min(w, h)
    P = [[((p[0] - x0) / (x1 - x0) - .5) * w, ((p[1] - y0) / (y1 - y0) - .5) * h, r() * d * .1] for p in P]
    ay = -h * (.17 + r() * .08)
    by = h * (.13 + r() * .08)
    A = [w * (.06 + (r() - .5) * .14) + ay * lean * w / h, ay, d * .5]
    B = [-w * (.08 + (r() - .5) * .14) + by * lean * w / h, by, d * .36]
    return {"P": P, "A": A, "B": B}


def _ore_faces(geo):
    P, A, B = geo["P"], geo["A"], geo["B"]
    N, F = len(P), []

    def d2(p, q):
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2

    own = []
    for i, p in enumerate(P):
        q = P[(i + 1) % N]
        m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]
        own.append(0 if d2(m, A) < d2(m, B) else 1)
    for i, p in enumerate(P):
        q = P[(i + 1) % N]
        if own[(i + N - 1) % N] != own[i]:
            F.append([A, B, p])
        F.append([A if own[i] == 0 else B, p, q])
    return F


def _graphite():
    return [_fixed(f"graphite-{i}") for i in range(4)]


def _planes(F):
    stops = _graphite()
    return [("plane", f, _ramp(stops, _tone(f)), .35) for f in F]


def _rim(P):
    return _line(P, _fixed("ore-rim"), 1.0, .7, join=ROUND)


def _crystal_planes(F, base, light):
    stops = [_mix(base, _fixed("crystal-0"), .75), _mix(base, _fixed("crystal-1"), .6),
             _mix(light, _fixed("crystal-2"), .55), _mix(light, _fixed("raw-pale"), .5)]
    ops = []
    for f in F:
        ops.append(("fill", f, _ramp(stops, _tone(f)), 1.0))
        ops.append(_line(f, light, .45, .45, join=ROUND))
    return ops


def _veins(w, h, r, col, count):
    s = 1 if r() > .5 else -1
    y0 = (r() - .5) * h * .3
    p0 = [-w * .7, y0 + h * .22 * s]
    p1x = (r() - .5) * w * .3
    p1 = [p1x, y0 + (r() - .5) * h * .1]
    p2 = [w * .7, y0 - h * .2 * s]
    q0 = [p1[0] + (p2[0] - p1[0]) * .3, p1[1] + (p2[1] - p1[1]) * .3]
    qx = q0[0] + w * (.18 + r() * .1)
    qh = h * (.3 + r() * .1)
    q1 = [qx, q0[1] + qh * (1 if r() > .4 else -1)]
    ops = [_line([p0, p1, p2], col, .75, .7, closed=False, join=BEVEL, cap="round"),
           _line([q0, [(q0[0] + q1[0]) / 2 + w * .05, (q0[1] + q1[1]) / 2], q1], col, .55, .5, closed=False, join=BEVEL,
                 cap="round")]
    if count > 2:
        t0 = [-w * (.35 + r() * .1), -y0 - h * .28 * s]
        t1 = [t0[0] + w * .3, t0[1] + h * .08 * s]
        ops.append(_line([t0, t1], col, .45, .45, closed=False, join=BEVEL, cap="round"))
    return ops


def _rotate(deg):
    a = deg * math.pi / 180
    cs, sn = math.cos(a), math.sin(a)
    return lambda p: [p[0] * cs - p[1] * sn, p[0] * sn + p[1] * cs]


def _moved(ops, fn):
    """The ops with every point mapped by `fn` (the kit's `<g transform>`)."""
    out = []
    for op in ops:
        if op[0] in ("fill", "plane", "line"):
            out.append((op[0], [fn(p) for p in op[1]]) + op[2:])
        elif op[0] == "clip":
            out.append(("clip", [[fn(p) for p in poly] for poly in op[1]]))
        else:
            out.append(op)
    return out


def _raw_point(x, y, cw, ch, rot, base, light, r, bg):
    P = _jit(_point_pts(cw, ch), .45, r)
    R = _rotate(rot)

    def fn(p):
        q = R([p[0], p[1] - ch / 2])
        return [q[0] + x, q[1] + y]

    return _moved([("fill", P, bg, 1.0)] + _raw_faces(P, base, light), fn)


def ore_ops(gem, seed, n, mined, cut=0):
    """The still-to-come stone for `n` files, `mined` of them in Anki, `cut` of them already watched."""
    base, light, edge = _gem(gem)
    A, c, r, bg = IMP, character(seed), prng(seed, 1), _rgb(theme.colours()["surface"])
    n = max(1, int(round(n)) or 1)
    m = min(n, max(0, int(round(mined))))
    f, t = m / n, _ore_t(n)
    w0, h0 = (x * ORE_V_SIZE for x in ore_size(n))
    w, h = w0 * (1 + c["sx"] * .14 * A), h0 * (1 + c["sy"] * .1 * A)
    lean, rot, nv = .2 + c["shear"] * .3 * A, c["rot"] * 10 * A, 3 if t > .3 else 2
    TOP = -31
    if m >= n:                     # all in Anki: a raw crystal cluster growing out of a thin rock base
        bh = max(7, h * .24)
        slab = _ore_geom(w * 1.1, bh, r, 6, .1)
        K = int(math.floor(3 + 3 * t + .5))
        by = h / 2 - bh * .55
        C = []
        for j in range(K):
            u = j / (K - 1) * 2 - 1
            a = abs(u)
            ch = min(by - TOP, h * (1 - .42 * a ** 1.2) * (.9 + .14 * r()))
            C.append({"a": a, "x": u * w * .32, "ch": ch, "cw": w * (.34 - .08 * a) * (.8 if K > 4 else 1),
                      "rot": u * 24 + (r() - .5) * 6})
        C.sort(key=lambda p: -p["a"])
        ops = []
        for p in C:
            ops += _raw_point(p["x"], by, p["cw"], p["ch"], p["rot"], base, light, r, bg)
        dy = h / 2 - bh / 2
        ops += _moved(_planes(_ore_faces(slab)) + [_rim(slab["P"])], lambda p: [p[0], p[1] + dy] + list(p[2:]))
    else:
        geo = _ore_geom(w, h, r, 7, lean)
        F = _ore_faces(geo)
        if not m:
            ops = _planes(F) + [("clip", [geo["P"]])] + _veins(w, h, r, light, nv) + [("unclip",), _rim(geo["P"])]
        else:                      # part in Anki: the top planes turn to raw crystal, and points break out of them
            order = sorted(range(len(F)), key=lambda i: sum(p[1] for p in F[i]) / len(F[i]))
            k = max(1, int(math.floor(f * (len(F) - 3) + .5)))
            glass = set(order[:k])
            rock = [f3 for i, f3 in enumerate(F) if i not in glass]
            K = 3 if f > 2 / 3 else 2 if f > 1 / 3 else 1
            spot = ((.02, -6), (.22, 22), (-.2, -26))
            top = min(p[1] for p in geo["P"])
            lx = top * .2 * w / h
            ops = []
            for j in range(K):
                y = top + h * (.22 + .04 * j)
                ch = min(y - TOP, h * (.42 + .3 * f) * (.75 if j else 1))
                ops += _raw_point(lx + spot[j][0] * w, y, w * (.24 + .1 * f) * (.8 if j else 1), ch, spot[j][1], base,
                                  light, r, bg)
            ops += _planes(rock) + _crystal_planes([f3 for i, f3 in enumerate(F) if i in glass], base, light)
            ops += [("clip", rock)] + _veins(w, h, r, light, nv) + [("unclip",), _rim(geo["P"])]
    cn = min(n, max(0, int(round(cut))))
    if cn:                         # watched out of order: one to three polished points on its lower flank
        fc = cn / n
        K = 3 if fc > 2 / 3 else 2 if fc > 1 / 3 else 1
        rc = prng(seed, 3)
        spot = ((.3, .16, 26), (.08, .3, -6), (-.26, .22, -28))
        for j in range(K):
            cw, ch = w * (.3 - .04 * j), h * (.52 - .06 * j)
            S = _point_shape(cw, ch, character(_seed_text(seed) + ":c" + str(j)), A)
            R = _rotate(spot[j][2] + (rc() - .5) * 8)
            tx, ty = spot[j][0] * w, spot[j][1] * h

            def fn(p, R=R, tx=tx, ty=ty):
                q = R(p)
                return [q[0] + tx, q[1] + ty]

            ops += _moved([("fill", S["P"], bg, 1.0)] + _point_faces(S, base, light, edge), fn)
    if abs(rot) > .01:
        ops = _moved(ops, _rotate(rot))
    return ops


# --- The trillion ▶ (list-r14m L2735–2760: Up Next's Play) ---------------------------------------------------------- #
UNLINKED = "unlinked"


def _tri_rand(seed):
    return _mulberry((seed_of("tri:" + _seed_text(seed)) * 2654435761) & _U32)


def trillion_ops(gem, seed, S=34):
    """The play stone, cut for the one file it plays, in its gem's colours (`UNLINKED`: the greys of no file)."""
    s, A, r = S / 2, IMP / .7, _tri_rand(seed)

    def j():
        return r() * 2 - 1

    sx, sy, shear = 1 + j() * .1 * A, 1 + j() * .08 * A, j() * .14 * A
    O = []
    for x, y in ((-.42, -.64), (.68, 0), (-.42, .64)):
        x += j() * .09 * A
        y += j() * .09 * A
        x += shear * y
        O.append([x * sx * s, y * sy * s])
    ctr = [(O[0][0] + O[1][0] + O[2][0]) / 3, (O[0][1] + O[1][1] + O[2][1]) / 3]
    ts, tw = .44 + j() * .06 * A, j() * .16 * A
    cs, sn = math.cos(tw), math.sin(tw)
    tcx = ctr[0] + j() * .08 * s * A
    tc = [tcx, ctr[1] + j() * .08 * s * A]
    T = [[tc[0] + ((p[0] - ctr[0]) * cs - (p[1] - ctr[1]) * sn) * ts,
          tc[1] + ((p[0] - ctr[0]) * sn + (p[1] - ctr[1]) * cs) * ts] for p in O]
    if gem == UNLINKED:
        base, light, edge = _fixed("unlinked-base"), _fixed("unlinked-light"), _fixed("unlinked-edge")
    else:
        base, light, edge = _gem(gem)
    L = (-.6, -.8)
    black = _fixed("black")

    def shade(F, k0=0):
        c = [sum(p[0] for p in F) / len(F), sum(p[1] for p in F) / len(F)]
        d = [c[0] - tc[0], c[1] - tc[1]]
        n = math.hypot(d[0], d[1]) or 1
        k = .5 + .5 * (d[0] / n * L[0] + d[1] / n * L[1]) - k0 + j() * .05 * A
        if k > .7:
            return _mix(light, edge, min(.32, (k - .7) * 1.1))
        if k > .38:
            return _mix(base, light, (k - .38) / .32)
        return _mix(_mix(base, black, .5), base, max(0, k) / .38)

    M = []
    for i, p in enumerate(O):
        q2 = O[(i + 1) % 3]
        t = .5 + j() * .12 * A
        m = [p[0] + (q2[0] - p[0]) * t, p[1] + (q2[1] - p[1]) * t]
        nx, ny = q2[1] - p[1], -(q2[0] - p[0])
        l_ = math.hypot(nx, ny) or 1
        o = [m[0] - ctr[0], m[1] - ctr[1]]
        sg = 1 if nx * o[0] + ny * o[1] > 0 else -1
        b = (.035 + r() * .06 * A) * s
        M.append([m[0] + sg * nx / l_ * b, m[1] + sg * ny / l_ * b])
    ops = []
    for i in range(3):
        k = (i + 1) % 3
        a, b, c = [O[i], M[i], T[i]], [M[i], O[k], T[k]], [M[i], T[k], T[i]]
        ops.append(("fill", a, shade(a), 1.0))
        ops.append(("fill", b, shade(b, .06), 1.0))
        ops.append(("fill", c, shade(c, .14), 1.0))
    OL = [O[0], M[0], O[1], M[1], O[2], M[2]]

    def at(t):
        if t < .5:
            return [O[0][0] + (M[0][0] - O[0][0]) * t * 2, O[0][1] + (M[0][1] - O[0][1]) * t * 2]
        return [M[0][0] + (O[1][0] - M[0][0]) * (t - .5) * 2, M[0][1] + (O[1][1] - M[0][1]) * (t - .5) * 2]

    g0 = at(.14 + r() * .1)
    g1 = at(.36 + r() * .1)
    ops.append(("fill", T, _mix(base, light, .4 + j() * .06), 1.0))
    ops.append(_line(OL, edge, .2, .7, join=ROUND))
    ops.append(_line([g0, g1], _mix(light, edge, .55), .5, 1, closed=False, cap="round"))
    return _moved(ops, _rotate(j() * 6 * A))


def ring_ops():
    """The cyan ring round the next stone (gem-kit `RING`: r 12, 1.2 wide, in the stone's units)."""
    return [("circle", 0.0, 0.0, 12.0, _rgb(theme.ROOM["ring"]), 1.2)]


# --- The fixed set of variants --------------------------------------------------------------------------------------- #
VARIANTS = 8
SEEDS = tuple(range(1, VARIANTS + 1))          # the seed each variant draws with
STATES = ("rock", "raw", "cut")
GEMS = tuple(theme.GEM)                        # sapphire, emerald, ruby
SIZES = {"watched": 1.0, "next": 1.22, "waiting": .84}   # list-r14m: s 1, BIG, SMALL
TIERS = (12, 60, 120)
ORE_N = (6, 20, 64, 200)                       # a size bucket's ore is drawn for this many files
ORE_SEEDS = (1, 2, 3, 4)
MINED_SHARE = (0.0, .25, .75, 1.0)             # none · some · most · all
ORE_CUT_SHARE = .15                            # "some watched": one cut point (the kit's 1 of 3 below a third)
TRILLION_SEED = 1
GROUP_SEED = 1
ROW_SCALE = 1.15                               # list-r14m :677, `.gstr .gm .gem-svg { scale: 1.15 }`


def variant_of(key, index):
    """A stable variant (0…VARIANTS−1) for a work's or piece's key and a file's place: the string plan's one hash
    (`stone_plan.variant`), so a stone looks the same wherever it is drawn."""
    from app.services import stone_plan
    return stone_plan.variant(key, index) % VARIANTS


def size_bucket(n):
    return 0 if n < 12 else 1 if n < 36 else 2 if n < 120 else 3


def mined_step(mined, n):
    """0 none · 1 some (up to half) · 2 most · 3 all."""
    if mined <= 0:
        return 0
    if mined >= n:
        return 3
    return 1 if mined / n <= .5 else 2


def _ore_counts(bucket, step, cut):
    n = ORE_N[bucket]
    m = n if step == 3 else 0 if step == 0 else min(n - 1, max(1, int(math.floor(n * MINED_SHARE[step] + .5))))
    return n, m, (max(1, int(math.floor(n * ORE_CUT_SHARE + .5))) if cut else 0)


def pictures():
    """(what, ops, logical px per unit, anchor in units) of every picture on a sheet, at text size S and dpr 1."""
    out = []
    for state in STATES:
        for gem in GEMS:
            for v, seed in enumerate(SEEDS):
                ops = stone_ops(state, gem, seed)
                ys = [p[1] for op in ops if op[0] == "fill" for p in op[1]]
                anchor = (0.0, (min(ys) + max(ys)) / 2)           # its own box's vertical centre: one line for all
                for size, s in SIZES.items():
                    out.append((("stone", state, gem, v, size), ops, ROW_SCALE * s, anchor))
    for gem in GEMS:
        for tier in TIERS:
            out.append((("group", gem, tier), group_ops(gem, tier, GROUP_SEED), ROW_SCALE, (0.0, 0.0)))
    for gem in GEMS:
        for bucket in range(4):
            for step in range(4):
                for cut in (0, 1):
                    n, m, cn = _ore_counts(bucket, step, cut)
                    out.append((("ore", gem, bucket, step, cut), ore_ops(gem, ORE_SEEDS[bucket], n, m, cn), ROW_SCALE,
                                (0.0, 0.0)))
    for gem in GEMS + (UNLINKED,):
        out.append((("trillion", gem), trillion_ops(gem, TRILLION_SEED), 1.0, (0.0, 0.0)))
    for size, s in SIZES.items():
        out.append((("ring", size), ring_ops(), ROW_SCALE * s, (0.0, 0.0)))
    return out + pre_pictures()


def _bounds(ops):
    """(x0, y0, x1, y1, half the widest stroke) of a display list, in units."""
    xs, ys, pad = [], [], 0.0
    for op in ops:
        kind = op[0]
        if kind in ("fill", "plane", "line"):
            xs += [q[0] for q in op[1]]
            ys += [q[1] for q in op[1]]
            if kind != "fill":
                pad = max(pad, op[3] / 2 if kind == "plane" else op[4] / 2)
        elif kind == "text":
            _k, x, y, size, text = op[:5]
            half = size * .36 * len(text)
            xs += [x - half, x + half]
            ys += [y - size * .8, y + size * .25]
            pad = max(pad, op[8] / 2)
        elif kind == "circle":
            _k, cx, cy, r, _rgb_, width = op
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
            pad = max(pad, width / 2)
    return min(xs), min(ys), max(xs), max(ys), pad


# --- Pre-studied, added (J-STONES; journey v3 SPEC §2.4: the mock's round 9, `preAdd` / `SPARK` / `SPK_AT`) ---------- #
PRE_SHEEN_ALPHA = .9                           # the sheen at the box's top-right corner (the mock's stop 0) …
PRE_SHEEN_END = .62                            # … gone this share of the way to the bottom left (its stop .62) …
PRE_SHEEN_BANDS = 4                            # … in this many flat bands (no gradient shade: the sheet's rule)
SPARK = ((0, -3.4), (.8, -.8), (3.4, 0), (.8, .8), (0, 3.4), (-.8, .8), (-3.4, 0), (-.8, -.8))
SPARK_AT = (-.2, 1.0)                          # the sparkle's centre from its picture's top-right corner (units)
SPARK_LINE = (.7, .4)                          # its rim: alpha, width


def _box(ops):
    """(x0, y0, x1, y1) of a display list's own shape, its strokes left out."""
    return _bounds(ops)[:4]


def sheen_ops(ops):
    """The sheen over a stone's top: flat bands of the cool colour, each a quad across the stone's box along the mock's
    gradient (x1 1, y1 0 → x2 .1, y2 .9 of the box), clipped to the stone's own outline (its facets)."""
    x0, y0, x1, y1 = _box(ops)
    w, h = x1 - x0, y1 - y0
    pre = _fixed("pre")
    dx, dy = -.9, .9                           # the gradient's way, in the box's own units

    def at(t, s):                              # t along the gradient, s across it (box units), as a point
        return (x0 + (1 + t * dx + s) * w, y0 + (t * dy + s) * h)
    out = [("clip", [op[1] for op in ops if op[0] in ("fill", "plane")])]
    for i in range(PRE_SHEEN_BANDS):
        a, b = PRE_SHEEN_END * i / PRE_SHEEN_BANDS, PRE_SHEEN_END * (i + 1) / PRE_SHEEN_BANDS
        alpha = PRE_SHEEN_ALPHA * (1 - (i + .5) / PRE_SHEEN_BANDS)
        band = _in_box([at(a, -2), at(a, 2), at(b, 2), at(b, -2)], x0, y0, x1, y1)
        if len(band) >= 3:
            out.append(("fill", band, pre, alpha))
    out.append(("unclip",))
    return out


def _in_box(pts, x0, y0, x1, y1):
    """A convex polygon cut to the box (Sutherland–Hodgman, one edge at a time): a band's picture is never bigger
    than its stone (the sheet packs each picture's own bounds)."""
    def cut(poly, inside, cross):
        out = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(x):
        return lambda p, q: (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))

    def at_y(y):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)
    for inside, cross in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                          (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        pts = cut(pts, inside, cross)
        if not pts:
            break
    return pts


def sparkle_ops(cx, cy):
    """The four-point sparkle centred on (cx, cy): its pale fill, then the cool rim."""
    pts = [(cx + x, cy + y) for x, y in SPARK]
    return [("fill", pts, _fixed("pre-spark"), 1.0), _line(pts, _fixed("pre"), SPARK_LINE[0], SPARK_LINE[1])]


def shoulder(ops):
    """Where a picture's sparkle sits: at its top-right corner (`SPARK_AT`), so it hangs outside its box."""
    _x0, y0, x1, _y1 = _box(ops)
    return x1 + SPARK_AT[0], y0 + SPARK_AT[1]


def pre_ops(state, seed):
    """A single stone's add — the sheen on its outline and the sparkle at its shoulder; its shape is the state's and
    the seed's (`stone_ops`: a gem colours a stone, never shapes it)."""
    stone = stone_ops(state, GEMS[0], seed)
    return sheen_ops(stone) + sparkle_ops(*shoulder(stone))


def pre_pictures():
    """The add's pictures, as `pictures()` lists them: one per single (state × variant × size, on the stone's own
    anchor, so a blit on the stone's point lands on it), one per cut group and per ore picture (the sparkle at its
    shoulder, on its anchor), and the sparkle alone (centred on its point)."""
    out = []
    for state in STATES:
        for v, seed in enumerate(SEEDS):
            stone = stone_ops(state, GEMS[0], seed)
            ys = [p[1] for op in stone if op[0] == "fill" for p in op[1]]
            anchor = (0.0, (min(ys) + max(ys)) / 2)
            ops = sheen_ops(stone) + sparkle_ops(*shoulder(stone))
            for size, s in SIZES.items():
                out.append((("pre", state, v, size), ops, ROW_SCALE * s, anchor))
    for tier in TIERS:
        out.append((("pre", "group", tier), sparkle_ops(*shoulder(group_ops(GEMS[0], tier, GROUP_SEED))), ROW_SCALE,
                    (0.0, 0.0)))
    for bucket in range(4):
        for step in range(4):
            for cut in (0, 1):
                n, m, cn = _ore_counts(bucket, step, cut)
                ops = ore_ops(GEMS[0], ORE_SEEDS[bucket], n, m, cn)
                out.append((("pre", "ore", bucket, step, cut), sparkle_ops(*shoulder(ops)), ROW_SCALE, (0.0, 0.0)))
    out.append((("pre", "spark"), sparkle_ops(0.0, 0.0), ROW_SCALE, (0.0, 0.0)))
    return out
