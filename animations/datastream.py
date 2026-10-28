"""Data stream: twisting ribbons of bits flowing past the text.

Each ribbon is a sine wave in its own lane, opening out to the full height
of the tall screens and closing in around the text. Dots and 0/1 digits sit
on a slow helix around the ribbon's spine and drift forward faster than the
text; now and then a bright packet races along a ribbon.
"""
from kit import clamp, math, mix

NAME = "Data stream"
DESCRIPTION = "Ribbons of binary data flowing as sine waves around the text."
REACH = 900

STEP = 16            # px between samples of the screen-height table
GRID = 40            # px between spine samples while drawing
PIECE = 9            # grid steps per strand piece where the strands fade
EDGE = 70            # keep ribbons this far inside a screen's top/bottom
SMALL, BIG = 16, 23  # the only two digit sizes, so layouts stay cached
WHITE = (1, 1, 1)
TAU = 2 * math.pi

# lane (-1 top .. 1 bottom, 0 = the text line), sine amplitude, wavelength
LANES = ((-0.74, 0.12, 1500), (-0.38, 0.14, 1150), (0.04, 0.48, 1300),
         (0.40, 0.13, 1600), (0.76, 0.11, 1100))


def _heights(world):
    """[(top, bottom)] every STEP px across the world: the screen at that x,
    narrowed near a screen edge and smoothed, so ribbons open and close
    gently instead of jumping at a bezel and never leave a screen."""
    n = int(world.w / STEP) + 2
    raw = []
    for i in range(n):
        s = world.screen_at(world.x0 + i * STEP)
        raw.append((s.y + EDGE, s.y1 - EDGE))
    r = int(170 / STEP)
    # narrow by 2r, then two box blurs of r: a smooth S-shaped change that
    # still never reaches past the shorter screen
    tops = [max(raw[j][0] for j in range(max(0, i - 2 * r), min(n, i + 2 * r + 1)))
            for i in range(n)]
    bots = [min(raw[j][1] for j in range(max(0, i - 2 * r), min(n, i + 2 * r + 1)))
            for i in range(n)]
    for _ in range(2):
        tops = [sum(tops[max(0, i - r):i + r + 1]) / len(tops[max(0, i - r):i + r + 1])
                for i in range(n)]
        bots = [sum(bots[max(0, i - r):i + r + 1]) / len(bots[max(0, i - r):i + r + 1])
                for i in range(n)]
    return list(zip(tops, bots))


def setup(wave):
    rng = wave.rng
    d = wave.data
    d.heights = _heights(wave.world)
    d.span = wave.w + 2 * REACH
    d.ribbons = []
    for i, (lane, amp, length) in enumerate(LANES):
        n = int(d.span / rng.uniform(60, 70))
        color = wave.color(i)
        d.ribbons.append(dict(
            lane=lane + rng.uniform(-0.04, 0.04),
            amp=amp * rng.uniform(0.85, 1.15),
            length=length * rng.uniform(0.9, 1.1),
            phase=rng.uniform(0, TAU),
            omega=rng.uniform(0.5, 0.9),            # sine roll, rad/s
            width=rng.uniform(30, 48),              # helix radius, px
            twist=rng.uniform(650, 950),            # px per helix turn
            spin=rng.uniform(0.8, 1.4),             # helix turn, rad/s
            drift=rng.uniform(110, 190),            # px/s ahead of the text
            color=color,
            bright=mix(color, WHITE, 0.5),
            n=n,
            sp=d.span / n,
            # per element: digit?, helix angle, two bits, flip rate, flip phase
            items=[(rng.random() < 0.35, rng.uniform(0, TAU), rng.randrange(2),
                    rng.randrange(2), rng.uniform(0.4, 1.4), rng.uniform(0, 2))
                   for _ in range(n)],
            packet=(rng.uniform(2.6, 4.8), rng.uniform(0, 5),
                    rng.uniform(1300, 1900)),       # period, offset, px/s
        ))


def _envelope(wave, u):
    """1 over the text, falling to 0 at REACH beyond either end
    (u = layout x minus the text's left edge)."""
    dist = -u if u < 0 else (u - wave.w if u > wave.w else 0.0)
    k = 1 - dist / REACH
    return k * k if k > 0 else 0.0


def draw(pen, wave):
    d = wave.data
    world = wave.world
    if not pen.visible(wave.x - REACH, world.y0, wave.x + wave.w + REACH, world.y1):
        return
    t = wave.t
    dirn = wave.dir
    scr = pen.screen
    # flow position f runs -REACH .. w + REACH in the travel direction;
    # x = ox + dirn * f
    ox = wave.x if dirn > 0 else wave.x + wave.w
    fa, fb = sorted(((scr.x - 60 - ox) * dirn, (scr.x1 + 60 - ox) * dirn))
    fa, fb = max(fa, -REACH), min(fb, wave.w + REACH)
    if fa >= fb:
        return
    # spine grid, aligned to multiples of GRID so every screen agrees
    g0 = math.floor(fa / GRID)
    g1 = math.ceil(fb / GRID)
    gf = [g * GRID for g in range(g0, g1 + 1)]
    gx = [ox + dirn * f for f in gf]
    sin, cos = math.sin, math.cos
    heights = d.heights
    hmax = len(heights) - 1.001
    yc = wave.y
    # lane v (-1..1) maps to y = yc + m*v + c*v*v: the top at -1, the bottom
    # at 1, with no kink at the text line where the two halves differ
    gmap = []
    for x in gx:
        k = clamp((x - world.x0) / STEP, 0, hmax)
        i = int(k)
        f = k - i
        (t0, b0), (t1, b1) = heights[i], heights[i + 1]
        top, bot = t0 + (t1 - t0) * f, b0 + (b1 - b0) * f
        m = (bot - top) / 2
        c = clamp((bot + top) / 2 - yc, -m / 2.2, m / 2.2)
        gmap.append((m, c, top, bot))
    genv = [_envelope(wave, x - wave.x) for x in gx]
    sy0, sy1 = scr.y - 20, scr.y1 + 20
    tx0, tx1 = wave.x - 12, wave.x + wave.w + 12
    ty0, ty1 = wave.y - wave.h * 0.62, wave.y + wave.h * 0.62
    last = len(gx) - 1
    # strand pieces: blocks of PIECE grid steps, each with one alpha taken
    # from its ends; neighbours with the same alpha are joined. Blocks are
    # counted from flow 0, so screens either side of a bezel agree.
    runs = []
    for j in range(last):
        b = (g0 + j) // PIECE
        if not runs or runs[-1][2] != b:
            ea = _envelope(wave, ox + dirn * b * PIECE * GRID - wave.x)
            eb = _envelope(wave, ox + dirn * (b + 1) * PIECE * GRID - wave.x)
            a = round(0.15 * (ea + eb), 3)
            if runs and runs[-1][3] == a:
                runs[-1][1:3] = [j + 1, b]
            else:
                runs.append([j, j + 1, b, a])
        else:
            runs[-1][1] = j + 1

    for rb in d.ribbons:
        color, bright = rb["color"], rb["bright"]
        lane, amp, ph = rb["lane"], rb["amp"], rb["phase"] - rb["omega"] * t
        kl = TAU / rb["length"]
        width, kt, spin = rb["width"], TAU / rb["twist"], rb["spin"] * t
        gy, up, down = [], [], []
        for x, (m, c, top, bot), fg in zip(gx, gmap, gf):
            v = lane + amp * sin(kl * fg + ph)          # LANES keep |v| < 1
            y = yc + m * v + c * v * v
            y = top if y < top else bot if y > bot else y
            s = width * cos(kt * fg - spin)
            gy.append(y)
            up.append((x, y - s))
            down.append((x, y + s))

        # the two helix strands, in pieces so they fade toward the ends
        for i, j1, _b, a in runs:
            if a > 0.01:
                pen.lines(up[i:j1 + 1], 1.5, color, a)
                if a > 0.05:
                    pen.lines(down[i:j1 + 1], 1.5, color, a * 0.6)

        # dots and digits: element k sits at flow (k*sp + drift*t) mod span
        n, sp = rb["n"], rb["sp"]
        off = (rb["drift"] * t) % d.span
        base = off % sp
        shift = int(off // sp)
        j0 = max(0, math.ceil((fa + REACH - base) / sp))
        j1 = min(n - 1, int((fb + REACH - base) // sp))
        items = rb["items"]
        for j in range(j0, j1 + 1):
            k = (j - shift) % n
            f = base + j * sp - REACH
            q = f / GRID - g0
            i = min(int(q), last - 1)
            q -= i
            env = genv[i] + (genv[i + 1] - genv[i]) * q
            if env < 0.08:
                continue
            digit, angle, b0, b1, rate, fph = items[k]
            th = angle + kt * f - spin
            depth = sin(th)                            # -1 back .. 1 front
            y = gy[i] + (gy[i + 1] - gy[i]) * q + width * cos(th)
            if y < sy0 or y > sy1:
                continue
            x = ox + dirn * f
            a = env * (0.55 + 0.45 * depth)
            if tx0 < x < tx1 and ty0 < y < ty1:
                a *= 0.3                               # keep the text clear
            a = int(a * 32) / 32                       # few alphas: colours cache
            if digit and depth > 0:
                bit = b1 if int(t * rate + fph) & 1 else b0
                pen.text(x, y, "01"[bit], BIG if depth > 0.45 else SMALL,
                         bright if depth > 0.7 else color, a)
            else:
                s = 3 + 1.75 * (depth + 1)
                pen.rect(x - s / 2, y - s / 2, s, s, color, a * 0.85)

        # a packet racing along the spine now and then
        period, poff, speed = rb["packet"]
        f = -REACH + ((t + poff) % period) * speed
        if f < wave.w + REACH and fa - 260 < f < fb + 260:
            for n_ in range(8):
                ft = f - n_ * 30
                q = ft / GRID - g0
                if q < 0 or q >= last:
                    continue
                i = int(q)
                q -= i
                env = genv[i] + (genv[i + 1] - genv[i]) * q
                x = ox + dirn * ft
                y = gy[i] + (gy[i + 1] - gy[i]) * q
                if n_ == 0:
                    clear = 0.35 if tx0 < x < tx1 and ty0 < y < ty1 else 1.0
                    pen.glow(x, y, 50, color, 0.6 * env)
                    pen.circle(x, y, 5.5, bright, clear * env)
                else:
                    pen.rect(x - 2, y - 2, 4, 4, bright, 0.75 * env * (1 - n_ / 8))
