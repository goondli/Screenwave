"""A feed-forward neural network travelling with the text.

Layers of nodes stand in columns from behind the text to in front of it,
stretching to the full height of whichever screen they are on. A forward
pass runs layer by layer in the travel direction: signals race along the
edges and each node flares as they arrive, then one output lights up.
"""
from kit import clamp, mix, smooth

NAME = "Neural network"
DESCRIPTION = "A neural network riding with the text, signals firing layer by layer."
REACH = 800

HOP = 0.62           # seconds for a signal to cross from one layer to the next
REST = 0.85          # pause after the output fires, before the next pass
BLEND = 640          # px over which the network stretches between screen heights
MARGIN = 70          # px kept clear at the top and bottom of a screen
ROOM = 240           # px of free height a node group needs beside the text
WHITE = (1.0, 1.0, 1.0)
CORE = (0.02, 0.035, 0.06)
LABELS = ("INPUT", "HIDDEN", "OUTPUT")
LABEL_SIZE = 22


def setup(wave):
    rng = wave.rng
    d = wave.data
    w = wave.w
    count = 5 if w < 2000 else 6
    s0, s1 = -REACH * 0.8, w + REACH * 0.8
    sizes = [4] + [rng.choice((5, 6, 6, 7)) for _ in range(count - 2)] + [3]

    layers, nodes = [], []
    for i, n in enumerate(sizes):
        s = s0 + (s1 - s0) * i / (count - 1)
        if 0 < i < count - 1:
            s += rng.uniform(-50, 50)
        over_text = -80 < s < w + 80
        ids = []
        for k in range(n):
            # r is the node's place top to bottom, 0..1
            r = (k + 0.5 + rng.uniform(-0.18, 0.18)) / n
            if over_text:
                # keep clear of the text: split into an upper and a lower group
                seg, f = (0, r / 0.5) if r < 0.5 else (2, (r - 0.5) / 0.5)
            else:
                seg, f = 1, r
            ids.append(len(nodes))
            nodes.append((i, s + rng.uniform(-30, 30), seg, clamp(f, 0.04, 0.96), r))
        layers.append((s, ids))

    # each node feeds the 2-3 nearest nodes (by height) in the next layer
    edges = []
    for i in range(count - 1):
        src, dst = layers[i][1], layers[i + 1][1]
        fed = set()
        for a in src:
            near = sorted(dst, key=lambda b: abs(nodes[b][4] - nodes[a][4]))
            for b in near[:rng.choice((2, 3, 3))]:
                edges.append((a, b))
                fed.add(b)
        for b in dst:
            if b not in fed:
                a = min(src, key=lambda a: abs(nodes[b][4] - nodes[a][4]))
                edges.append((a, b))
    incoming = [[] for _ in nodes]
    for a, b in edges:
        incoming[b].append(a)

    d.count = count
    d.layers = layers
    d.nodes = nodes
    # wires grouped by the layer they leave; each keeps a weight (its brightness)
    d.wires = [[(a, b, rng.uniform(0.07, 0.2)) for a, b in edges if nodes[a][0] == i]
               for i in range(count - 1)]
    # a dozen forward passes decided now: which nodes light (a node needs a
    # lit input and its own chance) and which output wins; draw() cycles them
    passes = []
    for _ in range(12):
        lit = []
        for n, node in enumerate(nodes):
            lit.append(node[0] == 0 or (rng.random() > 0.3 and any(lit[a] for a in incoming[n])))
        outs = layers[-1][1]
        passes.append((lit, rng.choice([n for n in outs if lit[n]] or outs)))
    d.passes = passes
    d.colors = [mix(wave.color(0), wave.color(1), i / (count - 1)) for i in range(count)]
    d.sparks = [mix(c, WHITE, 0.55) for c in d.colors]
    # node centres, from cool (resting) to white-hot (flaring), in 9 steps
    d.hot = [[mix(c, WHITE, 0.6 * k / 8) for k in range(9)] for c in d.colors]
    d.screens = [(s.x, s.x1, s.y, s.y1) for s in wave.world.screens]
    d.gap = wave.h / 2 + 75


def _extent(screens, x):
    """Top and bottom of the screen at x. Within BLEND/2 of an edge they ease
    to the height both neighbours share, so a node crossing the edge is
    whole on both screens and never sits where a monitor is missing."""
    for i, (x0, x1, y0, y1) in enumerate(screens):
        if x < x1 or i == len(screens) - 1:
            break
    top, bot = y0, y1
    if i > 0 and x - x0 < BLEND / 2:
        p = screens[i - 1]
        k = 1 - smooth((x - x0) / (BLEND / 2))
        top += (max(y0, p[2]) - y0) * k
        bot += (min(y1, p[3]) - y1) * k
    elif i < len(screens) - 1 and x1 - x < BLEND / 2:
        q = screens[i + 1]
        k = 1 - smooth((x1 - x) / (BLEND / 2))
        top += (max(y0, q[2]) - y0) * k
        bot += (min(y1, q[3]) - y1) * k
    return top + MARGIN, bot - MARGIN


def draw(pen, wave):
    d = wave.data
    count = d.count
    span = (count - 1) * HOP + REST
    lit, winner = d.passes[int(wave.t // span) % len(d.passes)]
    front = (wave.t % span) / HOP            # 0 .. count-1 (+ rest): where the signal is

    def at(s):
        return wave.x + s if wave.dir > 0 else wave.x + wave.w - s

    # where every node is this frame
    up_bot, dn_top = wave.y - d.gap, wave.y + d.gap
    pos = []
    for layer, s, seg, f, r in d.nodes:
        x = at(s)
        top, bot = _extent(d.screens, x)
        if seg == 1:
            y = top + (bot - top) * f
        else:
            # over the text: a group above it and one below; when the text
            # sits near a screen edge the column eases to the side with room
            if seg == 0:
                y = top + (min(up_bot, bot) - top) * f
            else:
                y = max(dn_top, top) + (bot - max(dn_top, top)) * f
            r = clamp(r, 0.04, 0.96)
            below, above = dn_top + (bot - dn_top) * r, top + (up_bot - top) * r
            y = below + (y - below) * smooth((up_bot - top) / ROOM)
            y = above + (y - above) * smooth((bot - dn_top) / ROOM)
        pos.append((x, y))

    hop_layer = int(front)
    u = smooth(front - hop_layer)
    world = pen.world
    tx0, tx1 = wave.x, wave.x + wave.w
    ty0, ty1 = wave.y - wave.h / 2, wave.y + wave.h / 2
    # wires: faint, brighter while the signal crosses them
    for i, wires in enumerate(d.wires):
        xa, xb = at(d.layers[i][0]), at(d.layers[i + 1][0])
        if not pen.visible(min(xa, xb) - 80, world.y0, max(xa, xb) + 80, world.y1):
            continue
        color, spark = d.colors[i], d.sparks[i]
        live_layer = i == hop_layer
        for a, b, weight in wires:
            (xa, ya), (xb, yb) = pos[a], pos[b]
            live = live_layer and lit[a]
            pen.line(xa, ya, xb, yb, 1.8, color, weight + 0.25 if live else weight)
            if live:
                k0 = max(0.0, u - 0.16)
                px, py = xa + (xb - xa) * u, ya + (yb - ya) * u
                # keep the text readable: sparks crossing it glow less
                dim = 0.35 if tx0 < px < tx1 and ty0 - 40 < py < ty1 + 40 else 1.0
                pen.line(xa + (xb - xa) * k0, ya + (yb - ya) * k0, px, py, 4, spark, 0.6 * dim)
                pen.glow(px, py, 40, color, 0.65 * dim)
                pen.circle(px, py, 6, spark, dim)

    # nodes: flare as the signal arrives, then cool down
    last = count - 1
    ring_life = REST / HOP + 0.5
    for layer, (s, ids) in enumerate(d.layers):
        x = at(s)
        if not pen.visible(x - 130, world.y0, x + 130, world.y1):
            continue
        color, hot = d.colors[layer], d.hot[layer]
        since = front - layer
        for n in ids:
            x, y = pos[n]
            flare = 0.0
            if lit[n] and 0 <= since < 1.42:
                flare = clamp(since / 0.12) * clamp(1 - (since - 0.12) / 1.3)
            if layer == last and n == winner and since >= 0:
                flare = max(flare, 0.75 * smooth(clamp(1 - (since - 0.3) / (REST / HOP + 0.3))))
            if flare > 0.01:
                pen.glow(x, y, 56 + 50 * flare, color, 0.55 * flare)
            pen.circle(x, y, 16, CORE)
            pen.ring(x, y, 16, 3, color, 0.5 + 0.5 * flare)
            pen.circle(x, y, 5 + 4 * flare, hot[round(flare * 8)], 0.4 + 0.6 * flare)
            if layer == last and n == winner and 0 <= since < ring_life:
                k = since / ring_life
                pen.ring(x, y, 20 + 50 * k, 2.5, d.sparks[layer], 0.8 * (1 - k))

    # layer names above each column
    for i, (s, ids) in enumerate(d.layers):
        x = at(s)
        top, _bot = _extent(d.screens, x)
        if not pen.visible(x - 80, top - 60, x + 80, top):
            continue
        label = LABELS[0] if i == 0 else LABELS[2] if i == last else LABELS[1]
        room = 1.0 if d.nodes[ids[0]][2] == 1 else smooth((up_bot - top) / ROOM)
        pen.text(x, top - 32, label, LABEL_SIZE, d.colors[i], 0.6 * room)
