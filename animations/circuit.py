"""Circuit board: printed-circuit traces around the text, from the top to the
bottom of every screen, with vias, a few chips, and glowing signal packets
racing along the traces in the travel direction.

Everything is laid out in setup() in "u" coordinates: px along the travel
direction, measured from the back edge of the text. draw() turns u into x
for the current direction and works out each packet from wave.t alone.
"""
from types import SimpleNamespace

from kit import clamp, math, mix, pulse

NAME = "Circuit board"
DESCRIPTION = "PCB traces with vias and chips; glowing signals race along them."
REACH = 800

PITCH = 38                              # gap between neighbouring traces
STAGGER = PITCH * (math.sqrt(2) - 1)    # keeps a bus parallel through 45-degree bends
TAIL = 220                              # packet tail length, px
PAD = 40                                # cull margin: covers the packet glow (r 36)
LABELS = ("AI", "NPU", "MCU", "DSP", "LLM", "ROS")
LABEL_SIZE = 30
BOARD = (0.035, 0.055, 0.075)           # chip body


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def _place_chips(wave, top, bottom, u0, u1, clear0, clear1):
    rng = wave.rng
    chips = []
    for _ in range(300):
        if len(chips) == 6:
            break
        cw = rng.choice((140, 170, 200))
        ch = rng.choice((120, 150, 180))
        cu = rng.uniform(u0 + 80, u1 - 80 - cw)
        cy = rng.uniform(top + 40, bottom - 40 - ch)
        # beside the text is fine, over it is not
        if _overlap(cy, cy + ch, clear0 - 30, clear1 + 30) and \
                _overlap(cu, cu + cw, -260, wave.w + 260):
            continue
        if any(_overlap(cu - 160, cu + cw + 160, c.u0, c.u1) and
               _overlap(cy - 120, cy + ch + 120, c.y0, c.y1) for c in chips):
            continue
        color = wave.color(1 + len(chips) % 2)
        chips.append(SimpleNamespace(u0=cu, u1=cu + cw, y0=cy, y1=cy + ch,
                                     label=LABELS[len(chips) % len(LABELS)],
                                     color=color, ink=mix(color, (1, 1, 1), 0.3),
                                     beat=rng.uniform(0, 3)))
    return chips


def _jogs(rng, lo, hi, n, home):
    """[(u, new offset)] for a bus: sideways steps of at most one pitch either
    way of its lane, so neighbouring buses (3+ pitches apart) never touch.
    `home`: end back on the lane (the run ends at chip pins)."""
    span = (n - 1) * STAGGER + 2 * PITCH + 50
    room = hi - lo
    count = min(rng.choice((1, 2, 2, 3, 4)), int(room // (span + 60)))
    if count < 1:
        return []
    cuts = sorted(rng.uniform(0, room - count * span) for _ in range(count))
    out, prev = [], 0
    for j, c in enumerate(cuts):
        target = 0 if home and j == count - 1 else \
            rng.choice([o for o in (-PITCH, 0, PITCH) if o != prev])
        if target != prev:
            out.append((lo + c + j * span, target))
            prev = target
    return out


def _trace(us, ue, y, i, n, jogs):
    pts = [(us, y)]
    off = 0
    for u, target in jogs:
        d = target - off
        b = u + (i * STAGGER if d < 0 else (n - 1 - i) * STAGGER)
        pts.append((b, y + off))
        pts.append((b + abs(d), y + target))
        off = target
    pts.append((ue, y + off))
    cum = [0.0]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
    return pts, cum


def _segment(wave, a, b, left, right, ys, ci, alpha):
    """One run of a bus between u=a and u=b. `left` / `right` is a chip the
    run ends at (traces level with it become pins) or None (vias)."""
    rng = wave.rng
    n = len(ys)
    ends = []
    for y in ys:
        if left and left.y0 + 12 <= y <= left.y1 - 12:
            us, sk = a, "pin"
        else:
            us, sk = a + (40 if left else 0) + rng.uniform(0, 80), "via"
        if right and right.y0 + 12 <= y <= right.y1 - 12:
            ue, ek = b, "pin"
        else:
            ue, ek = b - (40 if right else 0) - rng.uniform(0, 80), "via"
        ends.append((us, ue, sk, ek))
    lo = max(e[0] for e in ends) + 40
    hi = min(e[1] for e in ends) - 40
    home = any(e[3] == "pin" for e in ends)
    jogs = _jogs(rng, lo, hi, n, home) if hi > lo else []
    traces = []
    v = wave.data.v
    for i, (y, (us, ue, sk, ek)) in enumerate(zip(ys, ends)):
        pts, cum = _trace(us, ue, y, i, n, jogs)
        packet = None
        if rng.random() < 0.45:
            period = cum[-1] + TAIL + rng.uniform(300, 1500)
            packet = (rng.uniform(0, period), period)
        tu = [p[0] for p in pts]
        ty = [p[1] for p in pts]
        traces.append(SimpleNamespace(pts=pts, cum=cum, length=cum[-1], start=sk, end=ek,
                                      packet=packet, flash=v * 0.3,
                                      box=(min(tu) - PAD, max(tu) + PAD,
                                           min(ty) - PAD, max(ty) + PAD)))
    us = [p[0] for tr in traces for p in tr.pts]
    color = wave.color(ci)
    via = mix(mix(wave.color(0), (0, 0, 0), 0.5), color, 0.4)
    return SimpleNamespace(box=(min(us) - PAD, max(us) + PAD, ys[0] - PITCH - PAD,
                                ys[-1] + PITCH + PAD),
                           traces=traces, color=color, alpha=alpha,
                           via=via, head=mix(color, (1, 1, 1), 0.6))


def setup(wave):
    rng = wave.rng
    world = wave.world
    w = wave.w
    wave.data.v = wave.speed * 1.4          # packets, relative to the board
    top, bottom = world.y0 + 30, world.y1 - 30
    u0, u1 = -REACH + 20, w + REACH - 20
    clear0 = wave.y - wave.h * 0.5 - 55     # keep the text's own height clear
    clear1 = wave.y + wave.h * 0.5 + 55
    chips = _place_chips(wave, top, bottom, u0, u1, clear0, clear1)

    buses = []
    y = top + rng.uniform(0, PITCH * 2)
    while True:
        n = rng.choice((3, 3, 4, 5))
        ys = [y + i * PITCH for i in range(n)]
        if ys[-1] > bottom:
            break
        y = ys[-1] + PITCH * rng.choice((3, 4, 5))
        lo, hi = ys[0] - PITCH - 8, ys[-1] + PITCH + 8
        blocks = []                                  # (u0, u1, chip or None)
        if _overlap(lo, hi, clear0, clear1):
            blocks.append((-90, w + 90, None))
        for c in chips:
            if _overlap(lo, hi, c.y0 - 10, c.y1 + 10):
                blocks.append((c.u0, c.u1, c))
        blocks.sort(key=lambda b: b[0])
        runs, a, left = [], u0, None
        for b0, b1, chip in blocks:
            if b0 > a:
                runs.append((a, b0, left, chip))
            a, left = max(a, b1), chip
        runs.append((a, u1, left, None))
        ci = rng.choice((0, 0, 1, 2))
        for a, b, left, right in runs:
            # long runs sometimes break in two
            pieces = [(a, b, left, right)]
            if b - a > 1100 and rng.random() < 0.6:
                m = rng.uniform(a + 450, b - 450)
                g = rng.uniform(70, 200)
                pieces = [(a, m - g / 2, left, None), (m + g / 2, b, None, right)]
            for pa, pb, pl, pr in pieces:
                if pb - pa < 240:
                    continue
                mid = (pa + pb) / 2
                dist = max(0.0, -mid, mid - w)
                alpha = 1 - 0.5 * clamp(dist / REACH)
                buses.append(_segment(wave, pa, pb, pl, pr, ys, ci, alpha))
    wave.data.buses = buses
    wave.data.chips = chips
    wave.data.trace = mix(wave.color(0), (0, 0, 0), 0.5)


def _at(tr, s):
    pts, cum = tr.pts, tr.cum
    for j in range(1, len(cum)):
        if s <= cum[j]:
            seg = cum[j] - cum[j - 1]
            k = (s - cum[j - 1]) / seg if seg else 0.0
            (ax, ay), (bx, by) = pts[j - 1], pts[j]
            return ax + (bx - ax) * k, ay + (by - ay) * k
    return pts[-1]


def _between(tr, a, b):
    out = [_at(tr, a)]
    out.extend(p for p, c in zip(tr.pts, tr.cum) if a < c < b)
    out.append(_at(tr, b))
    return out


def draw(pen, wave):
    d = wave.data
    sgn = wave.dir
    ox = wave.x if sgn > 0 else wave.x + wave.w
    t = wave.t
    v = d.v

    def to_x(points):
        return [(ox + sgn * u, y) for u, y in points]

    for c in d.chips:
        xa, xb = ox + sgn * c.u0, ox + sgn * c.u1
        x0, x1 = min(xa, xb), max(xa, xb)
        cx, cy = (x0 + x1) / 2, (c.y0 + c.y1) / 2
        r = (x1 - x0) * 0.95                # the glow; it covers the chip and pins
        if not pen.visible(cx - r, cy - r, cx + r, cy + r):
            continue
        beat = pulse(t + c.beat, 3.0, 0.5)
        pen.glow(cx, cy, r, c.color, 0.10 + 0.12 * beat)
        pen.rect(x0, c.y0, x1 - x0, c.y1 - c.y0, BOARD)
        for px in range(int(x0) + 18, int(x1) - 12, 30):
            pen.rect(px, c.y0 - 9, 7, 9, c.color, 0.55)
            pen.rect(px, c.y1, 7, 9, c.color, 0.55)
        pen.lines([(x0, c.y0), (x1, c.y0), (x1, c.y1), (x0, c.y1)], 2.5, c.color, 0.85,
                  closed=True)
        pen.ring(x0 + 14, c.y0 + 14, 4, 2, c.color, 0.7)
        pen.text(cx, cy, c.label, LABEL_SIZE, c.ink, 0.75 + 0.25 * beat)

    for bus in d.buses:
        u0, u1, y0, y1 = bus.box
        xa, xb = ox + sgn * u0, ox + sgn * u1
        if not pen.visible(min(xa, xb), y0, max(xa, xb), y1):
            continue
        col, a = bus.color, bus.alpha
        for tr in bus.traces:
            u0, u1, y0, y1 = tr.box
            xa, xb = ox + sgn * u0, ox + sgn * u1
            if not pen.visible(min(xa, xb), y0, max(xa, xb), y1):
                continue
            pts = to_x(tr.pts)
            pen.lines(pts, 2.4, d.trace, 0.9 * a)
            flash = 0.0
            s = None
            if tr.packet:
                s = (tr.packet[0] + v * t) % tr.packet[1]
                if tr.length <= s < tr.length + tr.flash:
                    flash = 1 - (s - tr.length) / tr.flash
            # a run starts at a square pad and ends at a round via, or at chip pins
            x, y = pts[0]
            if tr.start == "pin":
                pen.rect(x - 6, y - 3.5, 12, 7, col, 0.5)
            else:
                pen.rect(x - 4.5, y - 4.5, 9, 9, bus.via, a)
            x, y = pts[-1]
            if tr.end == "pin":
                pen.rect(x - 6, y - 3.5, 12, 7, col, 0.5 + 0.5 * flash)
            elif flash:
                pen.glow(x, y, 30, col, 0.7 * flash)
                pen.ring(x, y, 5.5, 2.4, mix(bus.via, bus.head, flash), a)
            else:
                pen.ring(x, y, 5.5, 2.4, bus.via, a)
            if s is None or s - TAIL >= tr.length:
                continue
            for k, alpha in ((1.0, 0.25), (0.45, 0.75)):      # tail, fading behind
                lo = max(0.0, s - TAIL * k)
                hi = min(tr.length, s - TAIL * (k - 0.55))
                if hi > lo:
                    pen.lines(to_x(_between(tr, lo, hi)), 3.8, col, alpha * a)
            if s <= tr.length:
                hx, hy = to_x([_at(tr, s)])[0]
                pen.glow(hx, hy, 36, col, 0.8)
                pen.circle(hx, hy, 4.2, bus.head)
