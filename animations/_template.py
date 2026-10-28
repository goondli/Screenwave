"""Starting point for your own animation.

Copy this file to a new name in this folder (no leading underscore), e.g.
animations/ai_chip.py, change NAME, and it appears in the ScreenWave
window under Animations. See kit.py for everything `pen` can
draw and what `wave` tells you.

This example: an "AI chip" that travels in front of the text, with pins
that light up in turn and signals flying off it.
"""
from kit import math, pulse

NAME = "AI chip (example)"
DESCRIPTION = "A glowing chip leading the text, pins lighting in turn."
REACH = 500          # how far in front of / behind the text you draw, in px


def setup(wave):
    # Runs once when the wave starts: decide anything random here.
    wave.data.pins = 8
    wave.data.spin = wave.rng.choice((-1, 1))


def draw(pen, wave):
    # Runs every frame for every screen. Use only wave.t for movement.
    size = wave.h * 0.9                      # chip as tall as the text
    cx = wave.ahead(REACH / 2)               # half-way into the space in front
    cy = wave.y
    color = wave.color(0)

    pen.glow(cx, cy, size * 1.6, color, 0.35)
    pen.rect(cx - size / 2, cy - size / 2, size, size, (0.05, 0.08, 0.12))
    pen.lines([(cx - size / 2, cy - size / 2), (cx + size / 2, cy - size / 2),
               (cx + size / 2, cy + size / 2), (cx - size / 2, cy + size / 2)],
              4, color, 0.9, closed=True)
    pen.text(cx, cy, "AI", size * 0.42, color)

    n = wave.data.pins
    for side in range(4):
        for i in range(n):
            k = (i + 0.5) / n - 0.5                     # -0.5 .. 0.5 along the side
            lit = pulse(wave.t * 2 + (side * n + i) / (4 * n), 1.0, 0.3)
            ang = side * math.pi / 2
            ox, oy = math.cos(ang), math.sin(ang)       # outward direction
            px = cx + ox * size / 2 - oy * k * size
            py = cy + oy * size / 2 + ox * k * size
            pen.line(px, py, px + ox * size * 0.22, py + oy * size * 0.22,
                     5, color, 0.35 + 0.65 * lit)
