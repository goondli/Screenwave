"""Robot march: friendly robots walking along with the text.

A row of small robots marches on a floor line under the text, a bigger one
walks on the lower floor of the tall portrait screens, and an industrial arm
leads the way, waving. Their step length matches the marquee speed, so feet
stay planted on the floor instead of sliding.
"""
from kit import clamp, math, mix, pulse, smooth

NAME = "Robot march"
DESCRIPTION = "Friendly robots marching with the text, an industrial arm waving them on."
REACH = 800

DARK = (0.035, 0.05, 0.08)
EYE = (0.88, 0.98, 1.0)
TICK = 120          # spacing of the floor marks, fixed in the world


def _q(k):
    """Round a 0..1 level to 1/24 steps, so colours repeat and kit can reuse them."""
    return round(k * 24) / 24


def _bot(rng, off, floor, h, color):
    leg = h * 0.19                                  # thigh = shin length
    stride = leg * 0.36                             # foot travel each side of the hip
    return dict(off=off, floor=floor, h=h, color=color, leg=leg, stride=stride,
                phase=rng.random(), blink=rng.uniform(2.6, 4.6),
                blink_at=rng.uniform(0, 3), beat=rng.uniform(0.9, 1.5),
                fill=mix(color, DARK, 0.86), shade=mix(color, DARK, 0.55),
                light=mix(color, EYE, 0.25))


def setup(wave):
    w, rng, d = wave.world, wave.rng, wave.data
    band = w.band_bottom - w.band_top
    d.floor = w.band_bottom - max(18.0, band * 0.025)
    room = d.floor - (wave.y + wave.h * 0.5 + 45)  # under the text and its ripple
    h = clamp(room * 0.95, 90, 340)

    # marchers, by distance from the text's rear edge along the travel
    rear, front, n = -REACH * 0.72, wave.w * 0.86, 4
    d.bots = []
    for i in range(n):
        off = rear + (front - rear) * i / (n - 1) + rng.uniform(-30, 30)
        d.bots.append(_bot(rng, off, d.floor, h * rng.uniform(0.84, 1.0), wave.color(i)))
    d.row = (rear - h * 0.6, front + h * 0.6)

    # a big one on the lower floor that only tall screens have
    tall = [s for s in w.screens if s.y1 > w.band_bottom + band * 0.3]
    d.big = None
    if tall:
        floor2 = min(s.y1 for s in tall) - max(30.0, band * 0.035)
        big_h = clamp(floor2 - w.band_bottom - 40, 0, 720)
        if big_h >= 160:
            d.big = _bot(rng, wave.w * 0.5, floor2, big_h, wave.color(4))
            half = min(big_h * 1.4, wave.w * 0.5 + REACH - 40)   # stay inside REACH
            d.big_row = (wave.w * 0.5 - half, wave.w * 0.5 + half)

    # industrial arm in front of the text
    d.arm_off = wave.w + REACH * 0.45
    d.arm_len = clamp((d.floor - w.band_top) * 0.36, 120, 520)
    d.arm_color = wave.color(3)
    d.arm_beat = rng.uniform(0.75, 0.95)


def _at(wave, off):
    """x that is `off` px from the text's rear edge, along the travel."""
    return wave.behind(0) + wave.dir * off


def _chamfer(x0, y0, x1, y1, c):
    return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c),
            (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]


def _foot(q, stride, lift):
    """Foot offset from the hip for walk phase q: on the ground for the first
    half (moving back at exactly the marquee speed), then lifted forward."""
    if q < 0.5:
        return stride * (1 - 4 * q), 0.0
    s = (q - 0.5) * 2
    return stride * (2 * smooth(s) - 1), -lift * math.sin(math.pi * s)


def _knee(hx, hy, fx, fy, leg, d):
    dx, dy = fx - hx, fy - hy
    dist = max(1e-3, math.hypot(dx, dy))
    bend = math.sqrt(max(0.0, leg * leg - dist * dist / 4))
    px, py = -dy / dist, dx / dist
    if px * d < 0:                                  # knees bend forward
        px, py = -px, -py
    return hx + dx / 2 + px * bend, hy + dy / 2 + py * bend


def _limb(pen, pts, width, color, core):
    pen.lines(pts, width, color)
    if core:                                        # a tube: dark core, bright edge
        pen.lines(pts, width * 0.42, core)


def _leg(pen, hx, hy, q, b, d, color, width, core=None):
    fx, fy = _foot(q, b["stride"], b["h"] * 0.05)
    fx, fy = hx + fx * d, b["floor"] + fy
    kx, ky = _knee(hx, hy, fx, fy - width * 0.5, b["leg"], d)
    _limb(pen, [(hx, hy), (kx, ky), (fx, fy - width * 0.5)], width, color, core)
    pen.circle(kx, ky, width * 0.62, color)
    toe, heel = fx + d * b["h"] * 0.075, fx - d * b["h"] * 0.04
    pen.rect(min(toe, heel), fy - b["h"] * 0.04, abs(toe - heel), b["h"] * 0.04, color)


def _arm(pen, sx, sy, swing, b, d, color, width, core=None):
    h = b["h"]
    ex = sx + math.sin(swing) * d * h * 0.14
    ey = sy + math.cos(swing) * h * 0.14
    fore = swing + 0.55                             # elbow always bent forward
    hx = ex + math.sin(fore) * d * h * 0.12
    hy = ey + math.cos(fore) * h * 0.12
    _limb(pen, [(sx, sy), (ex, ey), (hx, hy)], width, color, core)
    pen.circle(sx, sy, width * 0.75, color)
    pen.ring(hx, hy, h * 0.03, width * 0.45, color)


def _draw_bot(pen, wave, b):
    h, floor, d = b["h"], b["floor"], wave.dir
    x = _at(wave, b["off"])
    if not pen.visible(x - h * 0.45, floor - h * 1.08, x + h * 0.45, floor + 4):
        return
    t, c = wave.t, b["color"]
    # one stride per 4 * stride px; capped so very fast marquees don't strobe
    freq = min(wave.speed / (4 * b["stride"]), 7.0)
    q = (t * freq + b["phase"]) % 1.0
    hip_y = floor - b["leg"] * 1.93 + h * 0.014 * math.cos(4 * math.pi * q)
    lw = h * 0.062
    swing = 0.6 * math.cos(2 * math.pi * q)

    pen.glow(x, floor, h * 0.42, c, 0.10)

    # far side, behind the body
    _leg(pen, x - d * h * 0.025, hip_y, (q + 0.5) % 1.0, b, d, b["shade"], lw)
    top = hip_y - h * 0.34
    _arm(pen, x - d * h * 0.03, top + h * 0.06, swing, b, d, b["shade"], lw * 0.85)

    # body
    body = _chamfer(x - h * 0.17, top, x + h * 0.17, hip_y + h * 0.02, h * 0.045)
    pen.polygon(body, b["fill"])
    pen.lines(body, max(2.0, h * 0.011), c, 0.95, closed=True)
    chest_x, chest_y = x + d * h * 0.065, top + h * 0.12
    beat = _q(pulse(t + b["phase"], b["beat"], 0.45))
    pen.glow(chest_x, chest_y, h * 0.09, c, 0.25 + 0.4 * beat)
    pen.circle(chest_x, chest_y, h * 0.026, mix(c, EYE, 0.4 * beat), 0.6 + 0.4 * beat)
    for i in range(3):                              # vent slots
        vy = top + h * (0.2 + 0.035 * i)
        pen.line(x - d * h * 0.12, vy, x - d * h * 0.02, vy, max(1.5, h * 0.008), c, 0.45)

    # near side, in front of the body
    _leg(pen, x + d * h * 0.025, hip_y, q, b, d, b["light"], lw, b["fill"])
    _arm(pen, x + d * h * 0.01, top + h * 0.06, -swing, b, d, b["light"], lw * 0.95,
         b["fill"])

    # head
    hb = top - h * 0.035
    hx = x + d * h * 0.015
    pen.rect(x - h * 0.04, hb, h * 0.08, h * 0.04, b["shade"])
    head = _chamfer(hx - h * 0.15, hb - h * 0.21, hx + h * 0.15, hb, h * 0.04)
    pen.polygon(head, b["fill"])
    pen.lines(head, max(2.0, h * 0.011), c, 0.95, closed=True)
    pen.ring(hx - d * h * 0.1, hb - h * 0.105, h * 0.022, max(1.5, h * 0.008), c, 0.7)

    # eyes on the visor, toward the front; a quick blink now and then
    ph = (t + b["blink_at"]) % b["blink"]
    open_ = _q(clamp(abs(ph / 0.09 - 1), 0.12, 1.0)) if ph < 0.18 else 1.0
    vy = hb - h * 0.12
    pen.rect(min(hx + d * h * 0.005, hx + d * h * 0.14), vy - h * 0.045,
             h * 0.135, h * 0.09, DARK)
    pen.glow(hx + d * h * 0.07, vy, h * 0.14, c, 0.35 * open_)
    for ex, er in ((hx + d * h * 0.04, 1.0), (hx + d * h * 0.11, 0.8)):
        ew, eh = h * 0.032 * er, h * 0.055 * er * open_
        pen.rect(ex - ew / 2, vy - eh / 2, ew, eh, mix(EYE, c, 0.25))
    pen.line(hx + d * h * 0.04, hb - h * 0.045, hx + d * h * 0.11, hb - h * 0.045,
             max(1.5, h * 0.009), c, 0.6)

    # antenna, swaying with the step, tip blinking
    ax, ay = hx - d * h * 0.03, hb - h * 0.21
    tx = ax - d * h * 0.025 * math.sin(4 * math.pi * q)
    ty = ay - h * 0.085
    pen.line(ax, ay, tx, ty, max(1.5, h * 0.01), c, 0.85)
    lit = _q(pulse(t * 1.3 + b["phase"] * 3, 1.0, 0.35))
    pen.glow(tx, ty, h * 0.07, c, 0.15 + 0.5 * lit)
    pen.circle(tx, ty, h * 0.02, mix(c, EYE, 0.5 * lit), 0.55 + 0.45 * lit)


def _draw_floor(pen, wave, floor, a, b, color):
    """A floor line between offsets a..b, fading out at both ends, with marks
    fixed in the world so the robots visibly walk over them."""
    x0, x1 = sorted((_at(wave, a), _at(wave, b)))
    if not pen.visible(x0, floor - 4, x1, floor + 30):
        return
    fade = min(260.0, (x1 - x0) * 0.25)
    for i in range(4):
        k = (i + 0.5) / 4
        pen.line(x0 + fade * i / 4, floor, x0 + fade * (i + 1) / 4, floor, 2, color, 0.4 * k)
        pen.line(x1 - fade * (i + 1) / 4, floor, x1 - fade * i / 4, floor, 2, color, 0.4 * k)
    pen.line(x0 + fade, floor, x1 - fade, floor, 2, color, 0.4)
    lo = max(x0, pen.screen.x - 30)
    hi = min(x1, pen.screen.x1 + 30)
    mx = math.ceil(lo / TICK) * TICK
    while mx <= hi:
        edge = min(mx - x0, x1 - mx) / fade
        if edge > 0:
            pen.line(mx, floor + 6, mx - 12, floor + 20, 2, color, 0.3 * _q(min(1.0, edge)))
        mx += TICK


def _draw_arm(pen, wave):
    dt = wave.data
    d, floor, L, c = wave.dir, dt.floor, dt.arm_len, dt.arm_color
    bx = _at(wave, dt.arm_off)
    if not pen.visible(bx - L * 1.3, floor - L * 2.6, bx + L * 1.3, floor + 4):
        return
    t = wave.t * dt.arm_beat
    fill, shade = mix(c, DARK, 0.82), mix(c, DARK, 0.5)

    # pedestal and turret
    base = [(bx - L * 0.26, floor), (bx + L * 0.26, floor),
            (bx + L * 0.17, floor - L * 0.12), (bx - L * 0.17, floor - L * 0.12)]
    pen.glow(bx, floor, L * 0.6, c, 0.12)
    pen.polygon(base, fill)
    pen.lines(base, 3, c, 0.9, closed=True)
    for i in range(4):                              # hazard stripes
        sx = bx - L * 0.15 + L * 0.085 * i
        pen.line(sx, floor - L * 0.02, sx + L * 0.05, floor - L * 0.1, 4, c, 0.5)
    sx, sy = bx, floor - L * 0.22
    pen.rect(bx - L * 0.09, sy, L * 0.18, L * 0.1, shade)

    # shoulder leans the arm forward, the forearm waves overhead
    a1 = (0.55 + 0.12 * math.sin(t * 1.4)) * d
    ex, ey = sx + math.sin(a1) * L, sy - math.cos(a1) * L
    a2 = (-0.45 + 0.5 * math.sin(t * 2.6)) * d
    wx, wy = ex + math.sin(a2) * L * 0.8, ey - math.cos(a2) * L * 0.8
    a3 = a2 + 0.45 * math.sin(t * 2.6 - 0.9) * d
    for (x0, y0, x1, y1, w) in ((sx, sy, ex, ey, L * 0.13), (ex, ey, wx, wy, L * 0.1)):
        pen.line(x0, y0, x1, y1, w, fill)
        pen.line(x0, y0, x1, y1, max(2.5, L * 0.012), c, 0.85)
    pen.lines([(sx - L * 0.06 * d, sy), (ex - L * 0.08 * d, ey + L * 0.06),
               (wx - L * 0.05 * d, wy + L * 0.05)], 2, c, 0.35)   # cable

    # gripper: two fingers opening and closing around the wrist
    gap = 0.25 + 0.2 * math.sin(t * 5.2)
    ux, uy = math.sin(a3), -math.cos(a3)            # along the hand
    for side in (-1, 1):
        ang = a3 + side * gap
        k1x, k1y = wx + math.sin(ang) * L * 0.16, wy - math.cos(ang) * L * 0.16
        k2x, k2y = k1x + ux * L * 0.1, k1y + uy * L * 0.1
        pen.lines([(wx, wy), (k1x, k1y), (k2x, k2y)], L * 0.035, c, 0.9)

    for jx, jy, r in ((sx, sy, L * 0.1), (ex, ey, L * 0.08), (wx, wy, L * 0.06)):
        pen.circle(jx, jy, r, fill)
        pen.ring(jx, jy, r, 3, c, 0.95)
    lit = _q(pulse(wave.t, 1.4, 0.4))
    pen.glow(wx, wy, L * 0.18, c, 0.2 + 0.5 * lit)
    pen.circle(wx, wy, L * 0.025, mix(c, EYE, lit), 0.7 + 0.3 * lit)
    pen.circle(ex, ey, L * 0.022, c, 0.8)


def draw(pen, wave):
    dt = wave.data
    a, b = dt.row
    _draw_floor(pen, wave, dt.floor, a, max(b, dt.arm_off + dt.arm_len * 0.6),
                wave.color(0))
    if dt.big:
        _draw_floor(pen, wave, dt.big["floor"], dt.big_row[0], dt.big_row[1],
                    dt.big["color"])
        _draw_bot(pen, wave, dt.big)
    _draw_arm(pen, wave)
    for bot in dt.bots:
        _draw_bot(pen, wave, bot)
