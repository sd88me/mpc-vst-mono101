#!/usr/bin/env python3
"""Mono-101's native MPC skin: skins/TUI.json + skins/Q-Links.json + the PNGs they use.

The art is Lemus's own panel: tools/panel/panel.json (Lemus machines/sh101/docs/panel.json, the SH-101's top panel measured
in mm, AGPL-3.0 like the rest of the port) drawn the way Lemus's HardwareView draws it (plugin/HardwareView.cpp: the case,
grooves, slider channels, scales, legends, caps, knobs and switches), ported to Pillow, then lit as in SKIN_STUDIO's
"Realistic hardware skins" (Model-303): grain, a top-left light, soft shadows, wells, fixed knob highlights. Legends in
Univers 53 Extended (emboldened), the face of our Roland ports, fitted to Lemus's measured widths. The brand marks are left out, as Lemus leaves them out.

The panel is 6:1, too long for the screen at a size a finger can use, so each tab shows one slice of it at true proportions:
    MOD/VCO   TUNE, MODULATOR, VCO
    MIX/VCF   SOURCE MIXER, VCF
    VCA/ENV   the lower left panel (VOLUME, PORTAMENTO, the switches, the bender's sliders; QUALITY where the bender lever is)
              and VCA, ENV
Sliders and knobs are Knob film strips (sliders dragged vertically); the slide and rotary switches are film strips too
(Model-72's way), and their printed position legends are tap targets that pick that position.
Q-Links: blocks of up to four controls left to right per tab.
    python3 tools/make_tui.py [--preview]     # -> skins/ (build-sdk.sh runs it); --preview also writes build/skin-preview/*.png
"""
import colorsys, json, math, os, shutil, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "skins")
PREVIEW = os.path.join(ROOT, "build", "skin-preview")
LOCK = [l.strip() for l in open(os.path.join(ROOT, "params.lock")) if l.strip() and not l.startswith("#")]
PANEL = json.load(open(os.path.join(ROOT, "tools", "panel", "panel.json")))
FONT_FILE = os.path.join(ROOT, "tools", "fonts", "Univers_53_Extended_Regular.otf")   # our Roland ports' face
CAP_RATIO = 0.722           # Univers 53: cap height / em
BOLDEN = 0.07               # its one weight, emboldened by a stroke of this much of the cap height
GESTURE = "Instant"
W, H = 1280, 628            # content area
SS = 3                      # supersampling
MIN_ZONE = 40               # px, a tap target


def P(key):
    return "Parameter %d" % LOCK.index(key)


# ---- the panel data ------------------------------------------------------------------------------------------------------
def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


C = {k: hexrgb(v["hex"]) for k, v in PANEL["colours"].items()}
EL = {e["id"]: e for e in PANEL["elements"]}
ELEMENTS = PANEL["elements"]

# Lemus's parameter ids -> ours (params.lock)
PARAM = {"lfoRate": "lfo_rate", "lfoWave": "lfo_wave", "vcoMod": "vco_mod", "range": "range", "pulseWidth": "pulse_width",
         "pwmSource": "pwm_source", "pulseLevel": "pulse_level", "sawLevel": "saw_level", "subLevel": "sub_level",
         "noiseLevel": "noise_level", "subMode": "sub_mode", "vcfFreq": "vcf_freq", "vcfRes": "vcf_res", "vcfEnv": "vcf_env",
         "vcfMod": "vcf_mod", "vcfKybd": "vcf_kybd", "vcaMode": "vca_mode", "attack": "attack", "decay": "decay",
         "sustain": "sustain", "release": "release", "trigger": "env_trigger", "volume": "volume", "tune": "tune",
         "portamento": "portamento", "portaMode": "porta_mode", "bendVco": "bend_vco", "bendVcf": "bend_vcf",
         "lfoModDepth": "bend_lfo", "transpose": "transpose", "quality": "quality"}

# QUALITY (ours): a third slide switch in the bender lever's place, drawn like PORTAMENTO's.
QUALITY = {"id": "hs_quality", "type": "hswitch", "param": "quality", "bbox": [30.4, 288.0, 57.6, 295.2],
           "positions": [34.0, 44.0, 54.0], "order": [0, 1, 2], "lever_d": 4.2, "colour": "slot_black"}
QUALITY_PRINT = [
    {"id": "t_q_hq", "type": "text", "label": "HQ", "bbox": [32.1, 282.9, 35.9, 285.7], "cap_h": 2.76},
    {"id": "t_q_auto", "type": "text", "label": "AUTO", "bbox": [39.8, 282.9, 48.2, 285.7], "cap_h": 2.76},
    {"id": "t_q_eco", "type": "text", "label": "ECO", "bbox": [50.8, 282.9, 57.2, 285.7], "cap_h": 2.76},
    {"id": "t_quality", "type": "text", "label": "QUALITY", "bbox": [34.5, 298.4, 53.5, 301.8], "cap_h": 3.4},
]
for e in QUALITY_PRINT + [QUALITY]:
    EL[e["id"]] = e
# the bender lever and its arrows (pitch bend and CC1 come in over MIDI)
DROP = {"bender", "a_bend", "ah_bend_l", "ah_bend_r", "t_bender_lever", "a_push", "ah_push"}

# the printed legends of each switch position (tap targets), in choice order
LEGENDS = {
    "lfo_wave": [["g_tri"], ["g_sqr"], ["t_wave_random"], ["t_wave_noise"]],
    "range": [["t_range_16"], ["t_range_8"], ["t_range_4"], ["t_range_2"]],
    "pwm_source": [["t_pwm_lfo", "g_pwm_lfo"], ["t_pwm_man"], ["t_pwm_env", "g_pwm_env"]],
    "sub_mode": [["t_sub1_oct", "t_sub1_down", "g_sub1"], ["t_sub2_oct", "t_sub2_down", "g_sub2"], ["t_sub3_oct", "t_sub3_down", "g_sub3"]],
    "vca_mode": [["t_vca_env", "g_vca_env"], ["t_vca_gate", "g_vca_gate"]],
    "env_trigger": [["t_trig_gate", "t_trig_plus", "t_trig_trig"], ["t_trig_gate2"], ["t_trig_lfo"]],
    "porta_mode": [["t_on"], ["t_auto"], ["t_off"]],
    "transpose": [["t_l"], ["t_m"], ["t_h"]],
    "quality": [["t_q_hq"], ["t_q_auto"], ["t_q_eco"]],
}
UNPRINTED = ("region", "groove", "case", "key", "led", "button", "power", "jack", "logo")


def bbox_of(e):
    if "bbox" in e:
        return e["bbox"]
    if "points" in e:
        xs, ys = [p[0] for p in e["points"]], [p[1] for p in e["points"]]
        return [min(xs), min(ys), max(xs), max(ys)]
    if "r" in e:
        return [e["x"] - e["r"], e["y"] - e["r"], e["x"] + e["r"], e["y"] + e["r"]]
    if e["type"] == "arrowhead":
        return [e["x"] - e["size"], e["y"] - e["size"], e["x"] + e["size"], e["y"] + e["size"]]
    return None


def centre(e):
    b = bbox_of(e)
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


# ---- colour (JUCE's brighter / darker) -----------------------------------------------------------------------------------
def darker(c, a):
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in c[:3]])
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, v / (1 + a)))


def brighter(c, a):
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in c[:3]])
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, 1 - (1 - v) / (1 + a)))


def rgba(c, alpha=1.0):
    return tuple(c[:3]) + (int(round(255 * alpha)),)


BLACK, WHITE = (0, 0, 0), (255, 255, 255)


# ---- a painter in panel mm -----------------------------------------------------------------------------------------------
class Painter:
    """An RGBA picture w x h px showing the panel from mm (ox, oy) at `scale` px/mm, drawn SS times larger."""

    def __init__(self, w, h, ox, oy, scale):
        self.w, self.h, self.ox, self.oy, self.k = w, h, ox, oy, scale * SS
        self.im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        self.shift, self.ink = (0.0, 0.0), None   # print's shadow pass: everything moved and in one colour

    def copy(self):
        p = Painter.__new__(Painter)
        p.__dict__.update(self.__dict__)
        p.im = self.im.copy()
        return p

    def pt(self, x, y):
        return ((x + self.shift[0] - self.ox) * self.k, (y + self.shift[1] - self.oy) * self.k)

    def rect(self, b):
        x0, y0 = self.pt(b[0], b[1])
        x1, y1 = self.pt(b[2], b[3])
        return [x0, y0, x1, y1]

    def fill(self, shape, colour, alpha=1.0, grad=None):
        """shape(draw) draws the shape in 255 on a mask; fills it with colour, or grad = (c0, p0, c1, p1[, radial]) in mm."""
        if self.ink:
            colour, alpha, grad = self.ink[0], alpha * self.ink[1], None
        m = Image.new("L", self.im.size, 0)
        shape(ImageDraw.Draw(m))
        bb = m.getbbox()
        if not bb:
            return
        m = m.crop(bb)
        if alpha < 1:
            m = m.point(lambda v: int(v * alpha))
        layer = Image.new("RGBA", m.size, rgba(colour, 0)) if grad is None else self._gradient(bb, *grad)
        layer.putalpha(m)
        self.im.alpha_composite(layer, dest=bb[:2])

    def _gradient(self, bb, c0, p0, c1, p1, radial=False):
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        (ax, ay), (bx, by) = self.pt(*p0), self.pt(*p1)
        ax, ay, bx, by = ax - bb[0], ay - bb[1], bx - bb[0], by - bb[1]
        dx, dy = bx - ax, by - ay
        if radial:
            r = math.hypot(dx, dy) or 1
            t = Image.new("L", (w, h))
            t.putdata([int(255 * min(1.0, math.hypot(x - ax, y - ay) / r)) for y in range(h) for x in range(w)])
        elif abs(dx) < 1e-9:
            col = Image.new("L", (1, h))
            col.putdata([int(255 * min(1.0, max(0.0, (y - ay) / dy))) for y in range(h)])
            t = col.resize((w, h))
        else:
            n2 = dx * dx + dy * dy
            t = Image.new("L", (w, h))
            t.putdata([int(255 * min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / n2))) for y in range(h) for x in range(w)])
        return Image.composite(Image.new("RGBA", (w, h), rgba(c1)), Image.new("RGBA", (w, h), rgba(c0)), t)

    # shapes in mm
    def box(self, b, colour, alpha=1.0, r=0.0, grad=None):
        rr = self.rect(b)
        if r > 0:
            self.fill(lambda d: d.rounded_rectangle(rr, r * self.k, fill=255), colour, alpha, grad)
        else:
            self.fill(lambda d: d.rectangle(rr, fill=255), colour, alpha, grad)

    def outline(self, b, colour, alpha, width, r=0.0):
        rr = self.rect(b)
        wpx = max(1, int(round(width * self.k)))
        self.fill(lambda d: d.rounded_rectangle(rr, r * self.k, outline=255, width=wpx), colour, alpha)

    def ellipse(self, b, colour, alpha=1.0, grad=None, width=0.0):
        rr = self.rect(b)
        if width:
            wpx = max(1, int(round(width * self.k)))
            self.fill(lambda d: d.ellipse(rr, outline=255, width=wpx), colour, alpha)
        else:
            self.fill(lambda d: d.ellipse(rr, fill=255), colour, alpha, grad)

    def line(self, pts, width, colour, alpha=1.0):
        pp = [self.pt(*p) for p in pts]
        wpx = max(1, int(round(width * self.k)))
        self.fill(lambda d: d.line(pp, fill=255, width=wpx, joint="curve"), colour, alpha)

    def poly(self, pts, colour, alpha=1.0):
        pp = [self.pt(*p) for p in pts]
        self.fill(lambda d: d.polygon(pp, fill=255), colour, alpha)

    def arc(self, cx, cy, r, a0, a1, width, colour, alpha=1.0):
        rr = self.rect([cx - r, cy - r, cx + r, cy + r])
        wpx = max(1, int(round(width * self.k)))
        self.fill(lambda d: d.arc(rr, a0 - 90, a1 - 90, fill=255, width=wpx), colour, alpha)   # Pillow's 0 is 3 o'clock

    def text(self, label, b, cap_h, colour):
        """Lemus's drawLegend: cap height centred in the box, scaled across to the box's width (0.75-1.3), digits not."""
        px = cap_h * self.k / CAP_RATIO
        font = ImageFont.truetype(FONT_FILE, max(4, int(round(px))))
        sw = max(1, int(round(cap_h * self.k * BOLDEN)))
        x0, y0, x1, y1 = font.getbbox(label, anchor="ls", stroke_width=sw)
        if x1 <= x0:
            return
        pad = int(px * 0.3) + 2
        tw = x1 - x0
        m = Image.new("L", (tw + 2 * pad, y1 - y0 + 2 * pad), 0)
        ImageDraw.Draw(m).text((pad - x0, pad - y0), label, font=font, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
        bw = (b[2] - b[0]) * self.k
        # Univers runs wide: fit to the panel's measured widths (digits only ever narrowed)
        sx = min(1.0, max(0.7, bw / tw)) if label.isdigit() else min(1.3, max(0.7, bw / tw))
        m = m.resize((max(1, int(round(m.width * sx))), m.height), Image.LANCZOS)
        bx0, by0, bx1, by1 = self.rect(b)
        caps = any(ch.isupper() or ch.isdigit() for ch in label)
        baseline = (by0 + by1) / 2 + cap_h * self.k / 2 if caps else by1 - max(0, y1)
        dx = int(round((bx0 + bx1) / 2 - m.width / 2))
        dy = int(round(baseline - (pad - y0)))
        if self.ink:
            colour = self.ink[0]
            m = m.point(lambda v: int(v * self.ink[1]))
        layer = Image.new("RGBA", m.size, rgba(colour, 0))
        layer.putalpha(m)
        cx, cy = max(0, -dx), max(0, -dy)
        if cx < layer.width and cy < layer.height:
            self.im.alpha_composite(layer.crop((cx, cy, layer.width, layer.height)), dest=(dx + cx, dy + cy))

    # soft light and shade (SKIN_STUDIO "Realistic hardware skins"): worked on a local crop, blurred, composited
    def _local(self, b, r, kind, blur_px, extra=0.0):
        rr = self.rect(b)
        m = int(3 * blur_px + extra * self.k) + 2
        x0, y0, x1, y1 = int(rr[0]) - m, int(rr[1]) - m, int(rr[2]) + m + 1, int(rr[3]) + m + 1
        return x0, y0, (x1 - x0, y1 - y0), [rr[0] - x0, rr[1] - y0, rr[2] - x0, rr[3] - y0]

    @staticmethod
    def _shape(size, loc, kind, r_px, dx=0.0, dy=0.0):
        m = Image.new("L", size, 0)
        box = [loc[0] + dx, loc[1] + dy, loc[2] + dx, loc[3] + dy]
        d = ImageDraw.Draw(m)
        if kind == "ellipse":
            d.ellipse(box, fill=255)
        else:
            d.rounded_rectangle(box, r_px, fill=255)
        return m

    def _put(self, mask, colour, x0, y0, alpha=1.0):
        if alpha < 1:
            mask = mask.point(lambda v: int(v * alpha))
        layer = Image.new("RGBA", mask.size, rgba(colour, 0))
        layer.putalpha(mask)
        cx, cy = max(0, -x0), max(0, -y0)
        cw, ch = min(layer.width, self.im.width - x0), min(layer.height, self.im.height - y0)
        if cx < cw and cy < ch:
            self.im.alpha_composite(layer.crop((cx, cy, cw, ch)), dest=(x0 + cx, y0 + cy))

    def soft(self, kind, b, alpha, blur, off=(0.0, 0.0), r=0.0, colour=BLACK):
        """A blurred shape ("box" or "ellipse"), e.g. a cast shadow: blur and off in mm."""
        bl = blur * self.k
        x0, y0, size, loc = self._local(b, r, kind, bl, abs(off[0]) + abs(off[1]))
        m = self._shape(size, loc, kind, r * self.k, off[0] * self.k, off[1] * self.k).filter(ImageFilter.GaussianBlur(bl))
        self._put(m, colour, x0, y0, alpha)

    def well(self, b, r=0.0, depth=0.6, alpha=0.6, lip=0.3):
        """A recess lit from the top left: an inner shadow under its top and left edges, a light lip outside its
        bottom-right edge (mask - blur(offset(mask)))."""
        bl = depth * self.k
        x0, y0, size, loc = self._local(b, r, "box", bl, 2 * depth)
        M = self._shape(size, loc, "box", r * self.k)
        S = self._shape(size, loc, "box", r * self.k, depth * self.k, depth * 1.3 * self.k).filter(ImageFilter.GaussianBlur(bl * 0.7))
        self._put(ImageChops.subtract(M, S), BLACK, x0, y0, alpha)
        if lip:
            L = self._shape(size, loc, "box", r * self.k, 0.3 * self.k, 0.35 * self.k)
            self._put(ImageChops.subtract(L, M).filter(ImageFilter.GaussianBlur(0.08 * self.k)), WHITE, x0, y0, lip)

    def result(self):
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def diag(w, h, lo, hi):
    """A top-left (hi) to bottom-right (lo) gradient, L: (x + y) / 2 from two ramps."""
    gy = Image.linear_gradient("L").resize((w, h))
    gx = Image.linear_gradient("L").transpose(Image.Transpose.TRANSPOSE).resize((w, h))
    return ImageChops.add(gx, gy, 2.0).point(lambda v: int(hi + (lo - hi) * v / 255))


def surface(im, seed=0):
    """The plastic under the room's light (after Model-303's plate): a top-left to bottom-right light fall, a faint
    vignette and a fine moulded grain. On the 1x picture."""
    w, h = im.size
    light = diag(w, h, 238, 255)
    vig = Image.radial_gradient("L").resize((w, h)).point(lambda v: max(0, v - 150) * 22 // 105)
    import random
    random.seed(seed)
    grain = Image.effect_noise((w // 2 + 1, h // 2 + 1), 4.5).resize((w, h), Image.BILINEAR)
    fine = Image.effect_noise((w, h), 2)
    out = []
    for ch in im.split()[:3]:
        ch = ImageChops.multiply(ch, light).point(lambda v: min(255, v + 7))
        ch = ImageChops.subtract(ch, vig)
        ch = ImageChops.add(ch, grain, 1.0, -128)
        ch = ImageChops.add(ch, fine, 1.0, -128)
        out.append(ch)
    return Image.merge("RGBA", out + [im.split()[3]])


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.sin(a), cy - r * math.cos(a))


def arrowhead(p, tip, deg, size, colour):
    a = math.radians(deg)
    pts = [(0, 0), (-size * 0.5, size), (size * 0.5, size)]
    p.poly([(tip[0] + x * math.cos(a) - y * math.sin(a), tip[1] + x * math.sin(a) + y * math.cos(a)) for x, y in pts], colour)


# ---- the static panel (HardwareView::renderStatic) -----------------------------------------------------------------------
def groove(p, a, b, w):
    horizontal = abs(b[1] - a[1]) < abs(b[0] - a[0])
    off = (0, w * 0.85) if horizontal else (w * 0.85, 0)
    p.line([(a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])], w * 0.55, C["groove_light"], 0.75)
    p.line([a, b], w, C["groove_dark"])


def knob_body(p, cx, cy, r):
    """Lemus's knob (a straight skirt, a slightly domed top) under a fixed top-left light: a soft cast shadow and a
    contact one, a lit rim on the skirt, a dark far edge and a specular patch on the top. Drawn once; frames add the
    pointer only, so the highlights stay put while it turns."""
    box = [cx - r, cy - r, cx + r, cy + r]
    p.soft("ellipse", box, 0.55, 1.1, (0.9, 1.5))
    p.soft("ellipse", box, 0.6, 0.3, (0.2, 0.4))
    p.ellipse(box, None, grad=((0x4a, 0x47, 0x4b), (cx - r, cy - r), (0x0e, 0x0d, 0x0f), (cx + r * 0.6, cy + r)))
    p.arc(cx, cy, r - 0.35, -95, 25, 0.45, (0x9a, 0x97, 0x9c), 0.55)            # the skirt's rim toward the light
    t = r * 0.86
    p.soft("ellipse", [cx - t, cy - t, cx + t, cy + t], 0.5, 0.35, (0.25, 0.45))  # the top's step onto the skirt
    p.ellipse([cx - t, cy - t + 0.15, cx + t, cy + t + 0.15], None,
              grad=((0x39, 0x36, 0x3a), (cx - t * 0.6, cy - t * 0.7), (0x17, 0x16, 0x18), (cx + t * 0.5, cy + t * 0.8), True))
    p.arc(cx, cy + 0.15, t - 0.4, 95, 215, 0.7, BLACK, 0.35)                       # the dome's far edge
    p.ellipse([cx - t, cy - t + 0.15, cx + t, cy + t + 0.15], WHITE, 0.10, width=0.25)
    p.soft("ellipse", [cx - t * 0.72, cy - t * 0.80, cx + t * 0.02, cy - t * 0.16], 0.16, t * 0.12, colour=WHITE)


def channel(p, e):
    """The slider's recessed channel (Lemus's darker frame) as a well, and the slot as a deep one."""
    b = e["bbox"]
    p.box(b, darker(C["panel"], 0.06))
    p.well(b, r=0.3, depth=0.7, alpha=0.65, lip=0.32)
    cx = e["x"]
    slot = [cx - 1.6, e["slot"][1], cx + 1.6, e["slot"][3]]
    p.box(slot, C["slot_black"], r=0.4)
    p.well(slot, r=0.4, depth=0.9, alpha=0.9, lip=0.18)


def draw_print(p, e):
    t, col = e["type"], C.get(e.get("colour", "print_white"), C["print_white"])
    if t == "text":
        p.text(e["label"], e["bbox"], e["cap_h"], C["print_white"])
    elif t == "line":
        p.line(e["points"], e["stroke"], col)
    elif t == "groove":
        groove(p, e["points"][0], e["points"][1], e["stroke"])
    elif t == "scale":
        for k in range(e["n"]):
            y = e["y0"] + k * e["pitch"]
            p.box([e["bbox"][0], y - e["tick_w"] / 2, e["bbox"][2], y + e["tick_w"] / 2], col, r=e["tick_w"] * 0.45)
    elif t == "ring":
        p.ellipse([e["x"] - e["r"], e["y"] - e["r"], e["x"] + e["r"], e["y"] + e["r"]], col, width=e["stroke"])
    elif t == "dot":
        p.ellipse([e["x"] - e["r"], e["y"] - e["r"], e["x"] + e["r"], e["y"] + e["r"]], col)
    elif t == "arrowhead":
        arrowhead(p, (e["x"], e["y"]), e["dir_deg"], e["size"], col)
    elif t == "arc":
        p.arc(e["x"], e["y"], e["r"], e["start_deg"], e["end_deg"], e["stroke"], col)
        tip = polar(e["x"], e["y"], e["r"], e["start_deg"])   # the ends point down at the b and # signs
        arrowhead(p, (tip[0] + 0.2, tip[1] + 1.2), 200, 1.5, col)
        tip = polar(e["x"], e["y"], e["r"], e["end_deg"])
        arrowhead(p, (tip[0] - 0.2, tip[1] + 1.2), 160, 1.5, col)


def render_static(p, keep):
    """The panel without its moving parts; keep(e) picks the print and controls of this slice."""
    p.box([p.ox - 50, p.oy - 50, p.ox + 1000, p.oy + 1000], (0x1b, 0x1a, 0x19))
    cs = C["case"]
    p.box([0, 0, 570, 310], None, r=3.0, grad=(brighter(cs, 0.15), (0, 0), darker(cs, 0.25), (0, 310)))
    for e in ELEMENTS:
        if e["type"] != "region":
            continue
        b, col, st = e["bbox"], C[e["colour"]], e["style"]
        if st == "shelf":
            p.box(b, col)
            p.box([b[0], 4.0, b[2], 18.4], None, grad=(darker(col, 0.05), (0, 4.0), darker(C["shelf_dark"], 0.12), (0, 18.4)))
            p.box([b[0], 18.4, b[2], 19.3], BLACK, 0.3)
        elif st == "raised":
            p.box(b, None, grad=(brighter(col, 0.06), (0, b[1]), darker(col, 0.04), (0, b[3])))
            p.box([b[0], b[1], b[2], b[1] + 0.35], WHITE, 0.22)
        elif st in ("lower", "keybed"):
            p.box(b, col)
    y0, y1 = 162.6, 166.0     # the raised panel's lit front face
    for b in ([3.5, y0, 88.6, y1], [537.9, y0, 566.5, y1]):
        p.box(b, None, grad=(brighter(C["panel"], 0.42), (0, y0), brighter(C["panel"], 0.12), (0, y1)))
    p.box([3.5, y0, 566.5, y0 + 0.3], BLACK, 0.3)
    p.box([88.6, y0, 537.9, y0 + 1.6], None, grad=((0x3a, 0x38, 0x35), (0, y0), (0x1d, 0x1c, 0x1b), (0, y0 + 1.6)))
    for e in ELEMENTS + [QUALITY]:
        if not keep(e):
            continue
        if e["type"] in ("slider", "vswitch"):
            channel(p, e)
        elif e["type"] == "hswitch":
            b = e["bbox"]
            hh = (b[3] - b[1]) / 2
            p.box(b, C["slot_black"], r=hh)
            p.well(b, r=hh, depth=0.7, alpha=0.9, lip=0.28)
    for t in ("groove", "scale", "line", "arc", "ring", "dot", "arrowhead", "text"):
        for e in ELEMENTS + QUALITY_PRINT:
            if e["type"] == t and (t == "groove" or keep(e)):
                if t != "groove":   # the ink stands a hair proud of the plastic: a faint shade below it
                    p.shift, p.ink = (0.1, 0.17), (BLACK, 0.3)
                    draw_print(p, e)
                    p.shift, p.ink = (0.0, 0.0), None
                draw_print(p, e)
    for e in ELEMENTS:   # printed knob scales and the rotary switches' detent ticks
        if not keep(e):
            continue
        if e["type"] == "knob" and e.get("ticks"):
            n = e["ticks"]
            for i in range(n):
                a = e["min_deg"] + (e["max_deg"] - e["min_deg"]) * i / (n - 1)
                p.line([polar(e["x"], e["y"], e["tick_r"][0], a), polar(e["x"], e["y"], e["tick_r"][1], a)], 0.55, C["print_white"])
        elif e["type"] == "rotary":
            for a in e["detents"]:
                p.line([polar(e["x"], e["y"], e["tick_r"][0], a), polar(e["x"], e["y"], e["tick_r"][1], a)], 0.6, C["print_white"])


# ---- moving parts (HardwareView::drawSlider / drawSwitch / drawKnob) -----------------------------------------------------
STRIPES = {"green": C["stripe_green"], "orange": C["stripe_orange"], "yellow": C["stripe_yellow"]}


def draw_slider_cap(p, e, v):
    cx = e["x"]
    cy = e["travel"][0] + (e["travel"][1] - e["travel"][0]) * v
    w, h = e["cap_w"], e["cap_h"]
    cap = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    p.soft("box", cap, 0.6, 0.8, (0.7, 1.2), r=1.0)          # cast down-right by the top-left light
    p.soft("box", cap, 0.55, 0.22, (0.15, 0.3), r=1.0)       # contact
    p.box(cap, None, r=0.9, grad=((0x30, 0x2e, 0x31), (cap[0], cap[1]), (0x16, 0x15, 0x17), (cap[0], cap[3])))
    p.box([cap[0] + 0.5, cap[1] + 0.35, cap[2] - 0.5, cap[1] + 0.75], WHITE, 0.13)
    p.box([cap[0] + 0.35, cap[1] + 0.5, cap[0] + 0.7, cap[3] - 0.5], WHITE, 0.13)
    p.box([cap[2] - 0.6, cap[1] + 0.6, cap[2] - 0.25, cap[3] - 0.4], BLACK, 0.4)          # the far edges in shade
    p.box([cap[0] + 0.5, cap[3] - 0.55, cap[2] - 0.3, cap[3] - 0.2], BLACK, 0.4)
    p.soft("box", [cap[0] + 0.8, cap[1] + 0.9, cap[0] + w * 0.55, cy - h * 0.12], 0.07, 0.5, colour=WHITE)   # sheen
    p.box([cap[0] + 0.6, cy + h * 0.16, cap[2] - 0.6, cy + h * 0.16 + 0.45], BLACK, 0.35)
    s = STRIPES[e["stripe"]]
    p.box([cap[0] + 0.6, cy - 0.45, cap[2] - 0.6, cy + 0.4], s)
    p.box([cap[0] + 0.6, cy - 0.45, cap[2] - 0.6, cy - 0.2], brighter(s, 0.6), 0.7)


def draw_vswitch(p, e, d):
    cx, y = e["x"], e["positions"][d]
    w, h = e["cap_w"] - 0.6, e["cap_h"]
    cap = [cx - w / 2, y - h * 0.47, cx + w / 2, y - h * 0.47 + h]
    p.soft("box", cap, 0.6, 0.8, (0.7, 1.2), r=1.1)
    p.soft("box", cap, 0.55, 0.22, (0.15, 0.3), r=1.1)
    p.box(cap, None, r=1.1, grad=((0x2e, 0x2c, 0x30), (cap[0], cap[1]), (0x14, 0x13, 0x15), (cap[0], cap[3])))
    p.box([cap[0] + 0.35, cap[1] + 0.6, cap[0] + 0.7, cap[3] - 0.6], WHITE, 0.12)
    p.box([cap[2] - 0.6, cap[1] + 0.6, cap[2] - 0.25, cap[3] - 0.4], BLACK, 0.4)
    p.box([cx - 1.4, cap[3], cx + 1.4, cap[3] + 1.3], (0x0a, 0x0a, 0x0a))
    s = C["stripe_yellow"]
    p.box([cap[0] + 0.7, y - 0.42, cap[2] - 0.7, y + 0.43], s)
    p.box([cap[0] + 0.7, y - 0.42, cap[2] - 0.7, y - 0.17], brighter(s, 0.6), 0.6)


def draw_hswitch(p, e, d):
    x, y = e["positions"][d], (e["bbox"][1] + e["bbox"][3]) / 2
    r = e["lever_d"] / 2
    p.soft("ellipse", [x - r, y - r, x + r, y + r], 0.65, 0.35, (0.4, 0.6))
    p.ellipse([x - r, y - r, x + r, y + r], None, grad=((0xf4, 0xf2, 0xee), (x - r * 0.4, y - r * 0.5), (0x6d, 0x6a, 0x64), (x + r, y + r), True))


def draw_pointer(p, cx, cy, r, a):
    p.line([polar(cx, cy, r * 0.5, a), polar(cx, cy, r * 0.97, a)], 0.9, C["knob_pointer"])


# ---- skin JSON -----------------------------------------------------------------------------------------------------------
class Obj:
    def __init__(self, *pairs):
        self.pairs = list(pairs)


def dump(v, ind=0):
    sp = "  " * ind
    pairs = v.pairs if hasattr(v, "pairs") else list(v.items()) if isinstance(v, dict) else None
    if pairs is not None:
        if not pairs:
            return "{}"
        return "{\n%s\n%s}" % (",\n".join("%s  %s: %s" % (sp, dump(k), dump(x, ind + 1)) for k, x in pairs), sp)
    if isinstance(v, list):
        return "[]" if not v else "[\n%s\n%s]" % (",\n".join(sp + "  " + dump(x, ind + 1) for x in v), sp)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def B(x, y, w, h):
    return "%d %d %d %d" % (x, y, w, h)


def entry(name, typ, data, b, remap=None, focus="No"):
    return {"version": 2,
            "componentData": {"version": 1, "name": name, "type": typ, "data": data},
            "handle remapping": {"version": 1, "map": [{"key": "Data", "value": remap}] if remap else []},
            "bounds": {"version": 1, "acceptsHWFocus": focus, "showWhenDataModelInvalid": "Show", "whenVisible": "Always",
                       "boundsType": "Absolute", "bounds": b}}


def bg(colour="0"):
    return {"version": 1, "focussed": {"version": 1, "colour": colour, "image": ""}, "unfocussed": {"version": 1, "colour": colour, "image": ""}}


def component(children, actions=None, ignore=False, background=None):
    return {"version": 2, "actions": actions or [], "backgroundData": background or bg(), "ignoreMousePresses": ignore,
            "disableCoarseDataWheel": False, "componentsData": children}


def act(on, handler, extra=""):
    return {"version": 1, "onAction": on, "handler": handler, "handleName": "Data", "additionalData": extra}


ACCENT = "fff08a2e"   # the caps' orange line
FOCUS = {"version": 1, "backgroundColour": "00000000", "outlineColour": ACCENT, "backgroundInset": 4.0, "outlineThickness": 2.0}
QL = [act("Mouse Down", "Q-Link"), act("Double Click", "Show Overlay", "knob overlay"), act("Enter Pressed", "Show Overlay", "knob overlay")]


def focus_ring(b):
    e = entry("focus", "Focus", FOCUS, b)
    e["bounds"]["whenVisible"] = "WhenFocussed"
    return e


def overlay_def():
    return component([entry("overlay", "KnobOverlay", Obj(
        ("version", 2), ("version", 1),
        ("actions", [{"version": 1, "onAction": "Focus Lost", "handler": "Focus Lost", "handleName": "Focus Lost", "additionalData": ""}]),
        ("overlayType", "Knob With Header"), ("scaleType", "Linear"), ("polarityType", "Unipolar"),
        ("showMinusSign", True), ("handleName", "Data")), "0 0 1280 800", focus="Yes")], ignore=True)


DEFS = {}


def strip_def(strip, w, h, frames):
    """A film strip dragged vertically, a focus ring, Q-Link on touch, the overlay on double tap / Enter."""
    key = "ctl_" + os.path.splitext(strip)[0]
    DEFS[key] = component([
        focus_ring(B(-3, -3, w + 6, h + 6)),
        entry("strip", "Knob", {"version": 3, "knobType": "FilmStrip", "filmStrip": strip, "numFrames": frames, "invert": False,
                                "dragOrientation": "Vertical", "handleName": "Data"}, B(0, 0, w, h)),
    ], actions=QL)
    return key


def save(im, name):
    im.save(os.path.join(OUT, name), optimize=True)
    return name


# ---- a view: a slice of the panel on the page ----------------------------------------------------------------------------
class View:
    def __init__(self, win, scale, page_x, page_w, keep):
        """win = (x0, y0), the mm at the view's top left; the view is page_w x H px at page x page_x."""
        self.x0, self.y0, self.s, self.px, self.pw, self.keep = win[0], win[1], scale, page_x, page_w, keep

    def to_page(self, x, y):
        return (self.px + (x - self.x0) * self.s, (y - self.y0) * self.s)

    def page_box(self, b, pad=0.0):
        x0, y0 = self.to_page(b[0] - pad, b[1] - pad)
        x1, y1 = self.to_page(b[2] + pad, b[3] + pad)
        return [int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(x1)), int(math.ceil(y1))]

    def painter_for(self, pb):
        """A painter for the page px box pb = [x0, y0, x1, y1]."""
        return Painter(pb[2] - pb[0], pb[3] - pb[1], self.x0 + (pb[0] - self.px) / self.s, self.y0 + pb[1] / self.s, self.s)

    def background(self):
        p = self.painter_for([self.px, 0, self.px + self.pw, H])
        render_static(p, self.keep)
        return surface(p.result(), seed=self.px)


class Page:
    def __init__(self, name, fn):
        self.name, self.fn, self.kids, self.extent, self.qrows, self.overlap_ok = name, fn, [], {}, [], False

    def grow(self, key, b):
        e = self.extent.get(key)
        self.extent[key] = list(b) if e is None else [min(e[0], b[0]), min(e[1], b[1]), max(e[2], b[2]), max(e[3], b[3])]

    def strip(self, key, view, pb, frames, draw, base=None):
        """A film strip over page box pb; draw(painter, frame) draws one frame over base (drawn once, copied) or nothing."""
        w, h = pb[2] - pb[0], pb[3] - pb[1]
        assert h * frames <= 16384, "%s: film strip too tall for the MPC (%d)" % (key, h * frames)
        strip = Image.new("RGBA", (w, h * frames), (0, 0, 0, 0))
        for f in range(frames):
            p = base.copy() if base else view.painter_for(pb)
            draw(p, f)
            strip.paste(p.result(), (0, f * h))
        name = save(strip, "%s.png" % key)
        self.kids.append(entry(key, strip_def(name, w, h, frames), {"version": 1, "handleName": "Data"},
                               B(pb[0], pb[1], w, h), P(key), focus="Yes"))
        self.grow(key, pb)
        return pb

    def slider(self, view, e, frames=51):
        key = PARAM[e["param"]]
        cx, w, h = e["x"], e["cap_w"], e["cap_h"]
        b = [cx - w / 2 - 0.5, min(e["travel"]) - h / 2 - 0.5, cx + w / 2 + 2.4, max(e["travel"]) + h / 2 + 3.0]
        self.strip(key, view, view.page_box(b), frames, lambda p, f: draw_slider_cap(p, e, f / (frames - 1)))

    def vswitch(self, view, e):
        key = PARAM[e["param"]]
        w, h, ps = e["cap_w"], e["cap_h"], e["positions"]
        b = [e["x"] - w / 2 - 0.5, ps[0] - h * 0.47 - 0.5, e["x"] + w / 2 + 2.4, ps[-1] + h * 0.53 + 3.0]
        sb = self.strip(key, view, view.page_box(b), len(ps), lambda p, f: draw_vswitch(p, e, f))
        self.zones(key, view, sb)

    def hswitch(self, view, e):
        key = PARAM[e["param"]]
        sb = self.strip(key, view, view.page_box([e["bbox"][0] - 0.6, e["bbox"][1] - 0.6, e["bbox"][2] + 1.4, e["bbox"][3] + 1.6]), len(e["positions"]),
                        lambda p, f: draw_hswitch(p, e, e["order"].index(f)))
        self.zones(key, view, sb)

    def _knob_base(self, view, e):
        r = e["d"] / 2
        pb = view.page_box([e["x"] - r - 0.8, e["y"] - r - 0.8, e["x"] + r + 3.6, e["y"] + r + 4.8])
        base = view.painter_for(pb)
        knob_body(base, e["x"], e["y"], r)
        return pb, base, r

    def rotary(self, view, e):
        key = PARAM[e["param"]]
        pb, base, r = self._knob_base(view, e)
        self.strip(key, view, pb, len(e["detents"]), lambda p, f: draw_pointer(p, e["x"], e["y"], r, e["detents"][f]), base)
        q = r * 0.8   # the legends may cover the strip's corners, not the knob
        self.zones(key, view, view.page_box([e["x"] - q, e["y"] - q, e["x"] + q, e["y"] + q]))

    def knob(self, view, e, frames=64):
        key = PARAM[e["param"]]
        pb, base, r = self._knob_base(view, e)
        frames = min(frames, 16384 // (pb[3] - pb[1]))
        a0, a1 = e["min_deg"], e["max_deg"]
        self.strip(key, view, pb, frames, lambda p, f: draw_pointer(p, e["x"], e["y"], r, a0 + (a1 - a0) * f / (frames - 1)), base)

    def zones(self, key, view, keep_off):
        """Transparent radio buttons over each position's printed legend: tap a legend to pick it."""
        boxes = []
        for ids in LEGENDS[key]:
            bs = [bbox_of(EL[i]) for i in ids]
            z = view.page_box([min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)], pad=1.2)
            for a in (0, 1):                # at least a fingertip
                if z[a + 2] - z[a] < MIN_ZONE:
                    c = (z[a] + z[a + 2]) // 2
                    z[a], z[a + 2] = c - MIN_ZONE // 2, c + MIN_ZONE // 2
            boxes.append(z)
        for i in range(len(boxes)):         # neighbours meet half way
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    ox, oy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                    if ox < oy:
                        l, r = (a, b) if a[0] < b[0] else (b, a)
                        l[2] = r[0] = (l[2] + r[0]) // 2
                    else:
                        t, u = (a, b) if a[1] < b[1] else (b, a)
                        t[3] = u[1] = (t[3] + u[1]) // 2
        s = keep_off
        for z in boxes:                     # and keep off the switch itself
            if z[0] < s[2] and s[0] < z[2] and z[1] < s[3] and s[1] < z[3]:
                left = [(s[0] - z[0], 0), (z[2] - s[2], 1), (s[1] - z[1], 2), (z[3] - s[3], 3)]
                side = max(left)[1]
                if side == 0:
                    z[2] = s[0]
                elif side == 1:
                    z[0] = s[2]
                elif side == 2:
                    z[3] = s[1]
                else:
                    z[1] = s[3]
        for i, z in enumerate(boxes):
            self.kids.append(entry("%s %d" % (key, i), "Button", {"version": 2, "onImage": "blank.png", "offImage": "blank.png", "buttonId": i,
                                                                 "numButtonsInGroup": len(boxes), "handleName": "Data",
                                                                 "gestureBehaviour": GESTURE}, B(z[0], z[1], z[2] - z[0], z[3] - z[1]), P(key)))
            self.grow(key, z)

    def controls(self, view):
        for e in ELEMENTS + [QUALITY]:
            if e.get("param") not in PARAM or not view.keep(e):
                continue
            {"slider": self.slider, "vswitch": self.vswitch, "hswitch": self.hswitch, "rotary": self.rotary,
             "knob": self.knob}[e["type"]](view, e)

    def tab(self, art):
        kids = [entry("bg", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": art}, B(0, 0, W, H))] + self.kids
        rects = []
        for g in self.qrows:
            assert 1 <= len(g) <= 4, g
            ex = [self.extent[k] for k in g]
            rects.append((max(min(e[0] for e in ex) - 3, 2), max(min(e[1] for e in ex) - 3, 2),
                          min(max(e[2] for e in ex) + 3, W - 2), min(max(e[3] for e in ex) + 3, H - 2)))
        if not self.overlap_ok:
            for i in range(len(rects)):
                for j in range(i):
                    a, b = rects[i], rects[j]
                    assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], "%s: Q-Link blocks %d and %d overlap" % (self.name, j, i)
        self.rects = rects
        return {"version": 1, "tabName": self.name, "fnKeyIndex": self.fn, "fnKeySubIndex": 0,
                "componentDefinition": component(kids, background=bg("ff1b1a19")),
                "qlinkBoundsData": [B(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in rects]}


# ---- the tabs ------------------------------------------------------------------------------------------------------------
MAIN_Y = (31.5, 123.6)        # section titles to the button strip


def main_keep(x0, x1):
    def keep(e):
        if e["id"] in DROP or e["type"] in UNPRINTED:
            return False
        c = centre(e)
        return x0 <= c[0] <= x1 and MAIN_Y[0] <= c[1] <= MAIN_Y[1]
    return keep


def lower_keep(e):
    if e["id"] in DROP or e["type"] in UNPRINTED:
        return False
    c = centre(e)
    return c[0] < 88.6 and c[1] > 166.0


def main_view(x0, x1, scale, page_x=0, page_w=W):
    """Slice x0..x1 of the main panel, centred in page_w px."""
    wx0 = (x0 + x1) / 2 - page_w / scale / 2
    wy0 = (MAIN_Y[0] + MAIN_Y[1]) / 2 - H / scale / 2
    return View((wx0, wy0), scale, page_x, page_w, main_keep(x0, x1))


def build_page(name, fn, views, qrows, overlap_ok=False):
    p = Page(name, fn)
    art = Image.new("RGBA", (W, H), (0x1b, 0x1a, 0x19, 255))
    for v in views:
        art.alpha_composite(v.background(), dest=(v.px, 0))
        p.controls(v)
    p.qrows, p.overlap_ok = qrows, overlap_ok
    return p, save(art.convert("RGB"), "%s.png" % name.lower().replace("/", "_"))


S_MAIN = W / (224.5 - 3.0)    # MOD/VCO fills the width; the other slices use its scale


def pages():
    out = [build_page("MOD/VCO", 0, [main_view(3.0, 224.5, S_MAIN)],
                      [["tune", "lfo_rate", "lfo_wave", "vco_mod"], ["range", "pulse_width", "pwm_source"]]),
           build_page("MIX/VCF", 1, [main_view(223.9, 424.8, S_MAIN)],
                      [["pulse_level", "saw_level", "sub_level", "sub_mode"], ["noise_level", "vcf_freq", "vcf_res", "vcf_env"],
                       ["vcf_mod", "vcf_kybd"]])]
    # VCA/ENV: the lower left panel at its own scale on the left, VCA and ENV at the main scale on the right
    s_low = H / 146.0
    low_w = int(round((90.6 - 1.5) * s_low))
    low = View((1.5, 162.4), s_low, 0, low_w, lower_keep)
    right = main_view(424.8, 558.6, S_MAIN, page_x=low_w, page_w=W - low_w)
    out.append(build_page("VCA/ENV", 2, [low, right],
                          [["attack", "decay", "sustain", "release"], ["vca_mode", "env_trigger"],
                           ["volume", "portamento", "porta_mode", "transpose"], ["bend_vco", "bend_vcf", "bend_lfo", "quality"]],
                          overlap_ok=True))   # the left panel's switches sit beside the bender sliders
    return out


# ---- preview (defaults, offline) -----------------------------------------------------------------------------------------
def render_preview(p, art, defaults, zones=False):
    img = Image.open(os.path.join(OUT, art)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for k in p.kids:
        cd, (x, y, w, h) = k["componentData"], [int(v) for v in k["bounds"]["bounds"].split()]
        typ = cd["type"]
        remap = k["handle remapping"]["map"]
        idx = int(remap[0]["value"].split()[-1]) if remap else None
        if typ.startswith("ctl_"):
            sd = DEFS[typ]["componentsData"][1]["componentData"]["data"]
            strip = Image.open(os.path.join(OUT, sd["filmStrip"])).convert("RGBA")
            fr = int(round(defaults[idx]["default"] * (sd["numFrames"] - 1)))
            img.alpha_composite(strip.crop((0, fr * h, w, fr * h + h)), (x, y))
        elif typ == "Button" and zones:
            d.rectangle([x, y, x + w - 1, y + h - 1], outline=(80, 160, 255), width=1)
    if zones:
        for r in p.rects:
            d.rectangle(r, outline=(232, 60, 60), width=2)
    return img


def main():
    preview = "--preview" in sys.argv
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(os.path.join(OUT, "blank.png"))
    built = pages()
    tabs = [p.tab(art) for p, art in built]
    used = {k for p, _ in built for k in p.extent}
    missing = [k for k in LOCK if k not in used]
    assert not missing, "parameters with no control: %s" % missing
    maps = []
    for p, _ in built:
        q = {"Q-Link %d" % n: -1 for n in range(1, 17)}
        for gi, keys in enumerate(p.qrows):
            for i, key in enumerate(keys):
                q["Q-Link %d" % (13 - 4 * gi + i)] = LOCK.index(key)
        maps.append({"Tab": p.fn + 1, "SubTab": 1, "Bank Direction": "RowTopDown", "Q-Links": q})
    defs = [{"key": "knob overlay", "value": overlay_def()}] + [{"key": k, "value": v} for k, v in DEFS.items()]
    tui = {"pageData": {"version": 1,
                        "componentDefinitions": {"version": 2, "importFiles": [], "localComponentDefinitions": defs},
                        "replacementStrings": [], "info": {"version": 1, "type": "CompleteDescription"}, "tabs": tabs}}
    open(os.path.join(OUT, "TUI.json"), "w").write(dump(tui) + "\n")
    ql = {"version": 4, "info": {"version": 1, "type": "CompleteDescription"},
          "Screen Mode Q-Links": {"version": 4, "map": maps}, "Program Mode Q-Links": {"Q-Link %d" % n: -1 for n in range(1, 17)}}
    open(os.path.join(OUT, "Q-Links.json"), "w").write(dump(ql) + "\n")
    names = [f.lower() for f in os.listdir(OUT)]
    assert len(names) == len(set(names)), "file names clash on a case-insensitive drive"
    if preview:
        defaults = json.load(open(os.path.join(ROOT, "build", "params.json")))["params"]
        os.makedirs(PREVIEW, exist_ok=True)
        for f in os.listdir(PREVIEW):
            os.remove(os.path.join(PREVIEW, f))
        for p, art in built:
            base = p.name.lower().replace("/", "_")
            render_preview(p, art, defaults).convert("RGB").save(os.path.join(PREVIEW, base + ".png"))
            render_preview(p, art, defaults, zones=True).convert("RGB").save(os.path.join(PREVIEW, base + "-zones.png"))
    print("wrote %s - %d tabs, %d files, %d KB" % (OUT, len(tabs), len(names), sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) // 1024))


if __name__ == "__main__":
    main()
