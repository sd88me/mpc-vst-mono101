#!/usr/bin/env python3
"""Mono-101's native MPC skin: skins/TUI.json + skins/Q-Links.json + the PNGs they use.

Layout: two tabs, the panel split in two so nothing has to shrink.
    VCO      CONTROLLER (VOLUME, TUNE, PORTAMENTO knobs stacked, the portamento switch), BENDER (VCO / VCF / LFO MOD
             sliders, TRANSPOSE), MODULATOR (RATE, WAVE under it), VCO (MOD with RANGE under it, PW with PWM).
    VCF      SOURCE MIXER (+ SUB OSC), VCF (+ SAVE / DELETE PRESET), VCA (MODE, and QUALITY in its foot), ENV (+ TRIGGER);
             SAVE PRESET shows the drawn naming keyboard over the tab (kb_open).
Sliders and knobs are Knob film strips (sliders dragged vertically); the switches are film strips of their positions
with transparent radio buttons over them (tap a position or its legend).
    MODS     ALL MODS (PURE / MODDED), then the circuitbenders mods, each with its ON / OFF switch: FILTER OVERDRIVE, PWM SOURCE, VCF FM, LFO RANGE,\n             LFO TRIG (from the keys).\nQ-Links: VCO controller / bender+transpose / modulator / VCO; VCF mixer / VCF / KYBD+VCA / ENV; MODS one block per\nmod (LFO RANGE and TRIG together).

Look: the SH-101's, from Lemus (tools/panel/panel.json's colours; the slider caps and knobs drawn as Lemus's HardwareView
draws them): the grey panel with moulded grooves round the sections, black caps with a green / orange line, black knobs
with an orange pointer, black slide switches with a yellow line, light lever switches. Lit as in SKIN_STUDIO's "Realistic hardware skins" (Model-303):
grain, a top-left light, soft cast shadows, recessed wells, knob highlights that stay put. Legends in Univers 53 Extended
(emboldened), the wordmark in Earth Normal: the faces of our Roland ports.
    python3 tools/make_tui.py [--preview]     # -> skins/ (build-sdk.sh runs it); --preview also writes build/skin-preview/*.png
"""
import colorsys, json, math, os, random, re, shutil, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "skins")
PREVIEW = os.path.join(ROOT, "build", "skin-preview")
FONTS = os.path.join(ROOT, "tools", "fonts")
LOCK = [l.strip() for l in open(os.path.join(ROOT, "params.lock")) if l.strip() and not l.startswith("#")]
PANEL = json.load(open(os.path.join(ROOT, "tools", "panel", "panel.json")))
FONT_FILE = os.path.join(FONTS, "Univers_53_Extended_Regular.otf")   # our Roland ports' face
CAP_RATIO = 0.722           # Univers 53: cap height / em
BOLDEN = 0.07               # its one weight, emboldened by a stroke of this much of the cap height
LOGO_FILE = os.path.join(FONTS, "Earth_Normal.ttf")
LABEL_FONT = "Titillium Web"   # the value labels: drawn by the MPC
GESTURE = "Instant"
DEVICE_TEXT = 0.64          # the MPC draws a Label's font at about this fraction of its height
W, H = 1280, 628            # content area
SS = 3                      # supersampling


def P(key):
    return "Parameter %d" % LOCK.index(key)


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


C = {k: hexrgb(v["hex"]) for k, v in PANEL["colours"].items()}   # Lemus's measured SH-101 palette


def darker(c, a):
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in c[:3]])
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, v / (1 + a)))


def brighter(c, a):
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in c[:3]])
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, 1 - (1 - v) / (1 + a)))


def rgba(c, alpha=1.0):
    return tuple(c[:3]) + (int(round(255 * alpha)),)


BLACK, WHITE = (0, 0, 0), (255, 255, 255)
INK = C["print_white"]
CHOICES = {
    "lfo_wave": ["TRI", "SQR", "RND", "NOISE"], "range": ["16'", "8'", "4'", "2'"], "pwm_source": ["LFO", "MAN", "ENV"],
    "sub_mode": ["1 OCT", "2 OCT", "2 OCT PW"], "vca_mode": ["ENV", "GATE"], "env_trigger": ["GATE+TRIG", "GATE", "LFO"],
    "porta_mode": ["ON", "AUTO", "OFF"], "transpose": ["L", "M", "H"], "quality": ["HQ", "AUTO", "ECO"],
    "drive_on": ["OFF", "ON"], "pwm_mod_on": ["OFF", "ON"], "pwm_mod_source": ["TRI", "SQR", "RND", "NOISE", "SUB 1", "SUB 2"],
    "fm_on": ["OFF", "ON"], "fm_source": ["PULSE", "SAW", "SUB 1", "SUB 2", "SUB PW", "NOISE"], "lfo_range": ["SLOW", "NORM", "FAST"],
    "lfo_trig": ["OFF", "ON"], "mods": ["PURE", "MODDED"],
}


# ---- a painter (panel mm for the parts drawn after Lemus, px for the page) ------------------------------------------------
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

    def text(self, label, b, cap_h, colour, sx=None, font_file=None, cap_ratio=None, bolden=None):
        """Lemus's drawLegend: cap height centred in the box, scaled across to the box's width (0.7-1.3), digits only
        narrowed; sx fixes the scale instead."""
        px = cap_h * self.k / (cap_ratio or CAP_RATIO)
        font = ImageFont.truetype(font_file or FONT_FILE, max(4, int(round(px))))
        sw = max(0, int(round(cap_h * self.k * (BOLDEN if bolden is None else bolden))))
        x0, y0, x1, y1 = font.getbbox(label, anchor="ls", stroke_width=sw)
        if x1 <= x0:
            return
        pad = int(px * 0.3) + 2
        tw = x1 - x0
        m = Image.new("L", (tw + 2 * pad, y1 - y0 + 2 * pad), 0)
        ImageDraw.Draw(m).text((pad - x0, pad - y0), label, font=font, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
        bw = (b[2] - b[0]) * self.k
        # Univers runs wide: fit to the panel's measured widths (digits only ever narrowed)
        if sx is None:
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


# ---- Lemus's parts (HardwareView), in mm on a painter scaled to the control -------------------------------------------
STRIPES = {"green": C["stripe_green"], "orange": C["stripe_orange"], "yellow": C["stripe_yellow"]}
CAP_MM = 8.7                # Lemus's slider cap width; a cap's painter is scaled so that it is the cap's width in px
KNOB_MM = 9.8               # and the knob's radius


def draw_cap(p, cx, cy, w, h, stripe):
    """A slider cap (drawSlider) under the top-left light: soft cast and contact shadows, lit near edges, far edges in
    shade, the coloured line."""
    cap = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    p.soft("box", cap, 0.6, 0.8, (0.7, 1.2), r=1.0)
    p.soft("box", cap, 0.55, 0.22, (0.15, 0.3), r=1.0)
    p.box(cap, None, r=0.9, grad=((0x30, 0x2e, 0x31), (cap[0], cap[1]), (0x16, 0x15, 0x17), (cap[0], cap[3])))
    p.box([cap[0] + 0.5, cap[1] + 0.35, cap[2] - 0.5, cap[1] + 0.75], WHITE, 0.13)
    p.box([cap[0] + 0.35, cap[1] + 0.5, cap[0] + 0.7, cap[3] - 0.5], WHITE, 0.13)
    p.box([cap[2] - 0.6, cap[1] + 0.6, cap[2] - 0.25, cap[3] - 0.4], BLACK, 0.4)
    p.box([cap[0] + 0.5, cap[3] - 0.55, cap[2] - 0.3, cap[3] - 0.2], BLACK, 0.4)
    p.box([cap[0] + 0.6, cy + h * 0.16, cap[2] - 0.6, cy + h * 0.16 + 0.45], BLACK, 0.35)   # the grip's step
    p.soft("box", [cap[0] + 0.8, cap[1] + 0.9, cap[0] + w * 0.55, cy - h * 0.12], 0.07, 0.5, colour=WHITE)
    s = STRIPES[stripe]
    p.box([cap[0] + 0.6, cy - 0.45, cap[2] - 0.6, cy + 0.4], s)
    p.box([cap[0] + 0.6, cy - 0.45, cap[2] - 0.6, cy - 0.2], brighter(s, 0.6), 0.7)


def knob_body(p, cx, cy, r):
    """Lemus's knob (a straight skirt, a slightly domed top) under a fixed top-left light: a soft cast shadow and a
    contact one, a lit rim on the skirt, a dark far edge and a specular patch on the top. Drawn once; frames add the
    pointer only, so the highlights stay put while it turns."""
    box = [cx - r, cy - r, cx + r, cy + r]
    p.soft("ellipse", box, 0.55, 1.1, (0.9, 1.5))
    p.soft("ellipse", box, 0.6, 0.3, (0.2, 0.4))
    p.ellipse(box, None, grad=((0x4a, 0x47, 0x4b), (cx - r, cy - r), (0x0e, 0x0d, 0x0f), (cx + r * 0.6, cy + r)))
    p.arc(cx, cy, r - 0.35, -95, 25, 0.45, (0x9a, 0x97, 0x9c), 0.55)
    t = r * 0.86
    p.soft("ellipse", [cx - t, cy - t, cx + t, cy + t], 0.5, 0.35, (0.25, 0.45))
    p.ellipse([cx - t, cy - t + 0.15, cx + t, cy + t + 0.15], None,
              grad=((0x39, 0x36, 0x3a), (cx - t * 0.6, cy - t * 0.7), (0x17, 0x16, 0x18), (cx + t * 0.5, cy + t * 0.8), True))
    p.arc(cx, cy + 0.15, t - 0.4, 95, 215, 0.7, BLACK, 0.35)
    p.ellipse([cx - t, cy - t + 0.15, cx + t, cy + t + 0.15], WHITE, 0.10, width=0.25)
    p.soft("ellipse", [cx - t * 0.72, cy - t * 0.80, cx + t * 0.02, cy - t * 0.16], 0.16, t * 0.12, colour=WHITE)


def draw_pointer(p, cx, cy, r, a):
    p.line([polar(cx, cy, r * 0.5, a), polar(cx, cy, r * 0.97, a)], 0.9, C["knob_pointer"])


# ---- the page's print and mouldings (px) --------------------------------------------------------------------------------
GROOVE = 2.6                # px
SHADE = ((0.6, 1.0), 0.32)  # the ink's faint shade: offset px, alpha


def groove(p, a, b, w=GROOVE):
    """A moulded groove: a dark line with a lit edge below or to the right (Lemus's groove())."""
    horizontal = abs(b[1] - a[1]) < abs(b[0] - a[0])
    off = (0, w * 0.85) if horizontal else (w * 0.85, 0)
    p.line([(a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])], w * 0.55, C["groove_light"], 0.75)
    p.line([a, b], w, C["groove_dark"])


def text_width(text, cap, font_file=FONT_FILE, cap_ratio=CAP_RATIO, bolden=BOLDEN):
    f = ImageFont.truetype(font_file, max(4, int(round(cap * SS / cap_ratio))))
    sw = max(0, int(round(cap * SS * bolden)))
    b = f.getbbox(text, anchor="ls", stroke_width=sw)
    return (b[2] - b[0]) / SS


def printed(p, fn):
    """Draw fn(p) twice: its faint shade, then the ink."""
    p.shift, p.ink = SHADE[0], (BLACK, SHADE[1])
    fn(p)
    p.shift, p.ink = (0.0, 0.0), None
    fn(p)


def legend(p, text, cx, cy, cap, colour=INK, fit=None, align="c"):
    """Print text with its cap height centred on cy: centred on cx (align "c"), or ending ("r") / starting ("l") there;
    narrowed to fit px if wider."""
    w = text_width(text, cap)
    sx = min(1.0, fit / w) if fit else 1.0
    w *= sx
    x = cx if align == "c" else cx - w / 2 if align == "r" else cx + w / 2
    printed(p, lambda q: q.text(text, [x - w / 2, cy - cap / 2, x + w / 2, cy + cap / 2], cap, colour, sx=sx))


def sections(p, spans, y0, y1, head=40, cap=17):
    """Section boxes ruled by grooves as on the panel, each with its title strip; spans = (title, x0, x1)."""
    for title, a, b in spans:
        for x in (a, b):
            groove(p, (x, y0), (x, y1))
        for y in (y0, y0 + head, y1):
            groove(p, (a, y), (b, y))
    for title, a, b in spans:
        if not title:
            continue
        c = cap
        while text_width(title, c) * 0.85 > b - a - 12 and c > 9:   # a narrow box takes a smaller title first
            c -= 0.5
        legend(p, title, (a + b) / 2, y0 + head / 2 + 1, c, fit=b - a - 12)


def well(p, b, colour, r=4, depth=3, alpha=0.7, lip=0.3):
    p.box(b, colour, r=r)
    p.well(b, r=r, depth=depth, alpha=alpha, lip=lip)


# ---- art ----------------------------------------------------------------------------------------------------------------
FH = 250                    # a fader's travel picture: the cap centre runs from CAP_H/2 to FH - CAP_H/2 below its top
CAP_W, CAP_H = 34, 56
FADER_FRAMES = 51           # 0.2 steps
STRIP_PAD = (22, 4, 30, 9)  # a fader strip's box round the column: left, top, right, bottom (the shadow falls down-right)
KNOB_BOX, KNOB_C, KNOB_R = 124, 56, 40   # knob strip size, the knob's centre in it, its radius (px)
KNOB_FRAMES = 64
KNOB_SWEEP = 150            # degrees each way (Lemus's knobs)


def fader_frames(h):
    return min(FADER_FRAMES, 16384 // (STRIP_PAD[1] + h + STRIP_PAD[3]))


def fader_strip(stripe, h=FH):
    """The cap at each position, alone: the channel, slot and scale are in the page."""
    name = "fader_%s_%d.png" % (stripe, h)
    l, t, r, b = STRIP_PAD
    w, fh = l + r, t + h + b
    frames = fader_frames(h)
    if os.path.exists(os.path.join(OUT, name)):
        return name
    m = CAP_W / CAP_MM
    strip = Image.new("RGBA", (w, fh * frames), (0, 0, 0, 0))
    for f in range(frames):
        p = Painter(w, fh, 0, 0, m)
        cy = t + (h - CAP_H / 2) - (h - CAP_H) * f / (frames - 1)
        draw_cap(p, l / m, cy / m, CAP_MM, CAP_H / m, stripe)
        strip.paste(p.result(), (0, f * fh))
    assert strip.height <= 16384, "film strip too tall for the MPC"
    return save(strip, name)


def knob_strip(name):
    m = KNOB_R / KNOB_MM
    c = KNOB_C / m
    base = Painter(KNOB_BOX, KNOB_BOX, 0, 0, m)
    knob_body(base, c, c, KNOB_MM)
    strip = Image.new("RGBA", (KNOB_BOX, KNOB_BOX * KNOB_FRAMES), (0, 0, 0, 0))
    for f in range(KNOB_FRAMES):
        p = base.copy()
        draw_pointer(p, c, c, KNOB_MM, -KNOB_SWEEP + 2 * KNOB_SWEEP * f / (KNOB_FRAMES - 1))
        strip.paste(p.result(), (0, f * KNOB_BOX))
    return save(strip, name)


# ---- the panel's switches (HardwareView::drawSwitch and the rotary switches), each a film strip of its positions ----------
SW_W, SW_H, SW_PITCH = 34, 52, 42   # a slide switch's cap (px) and its positions' spacing (a fingertip each)
SW_MM = 8.6                         # Lemus's switch cap width
ROT_R = 40                          # a rotary switch's knob radius (px)
ROT_DETENTS = {4: [-45, -15, 15, 45], 6: [-120, -72, -24, 24, 72, 120]}
HS_PITCH, HS_LEVER = 46, 28         # a lever switch's positions' spacing and its lever's diameter (px)


def switch_cap(p, cx, cy, w, h):
    """A slide switch's cap (drawSwitch): black, a yellow line across, lit as the slider caps."""
    cap = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    p.soft("box", cap, 0.6, 0.8, (0.7, 1.2), r=1.1)
    p.soft("box", cap, 0.55, 0.22, (0.15, 0.3), r=1.1)
    p.box(cap, None, r=1.1, grad=((0x2e, 0x2c, 0x30), (cap[0], cap[1]), (0x14, 0x13, 0x15), (cap[0], cap[3])))
    p.box([cap[0] + 0.5, cap[1] + 0.35, cap[2] - 0.5, cap[1] + 0.75], WHITE, 0.12)
    p.box([cap[0] + 0.35, cap[1] + 0.6, cap[0] + 0.7, cap[3] - 0.6], WHITE, 0.12)
    p.box([cap[2] - 0.6, cap[1] + 0.6, cap[2] - 0.25, cap[3] - 0.4], BLACK, 0.4)
    p.box([cap[0] + 0.5, cap[3] - 0.55, cap[2] - 0.3, cap[3] - 0.2], BLACK, 0.4)
    p.soft("box", [cap[0] + 0.8, cap[1] + 0.9, cap[0] + w * 0.55, cy - h * 0.12], 0.06, 0.5, colour=WHITE)
    s = C["stripe_yellow"]
    p.box([cap[0] + 0.7, cy - 0.42, cap[2] - 0.7, cy + 0.43], s)
    p.box([cap[0] + 0.7, cy - 0.42, cap[2] - 0.7, cy - 0.17], brighter(s, 0.6), 0.6)


def lever(p, x, y, r):
    """A lever switch's knob (PORTAMENTO, TRANSPOSE): a light round lever, lit from the top left."""
    p.soft("ellipse", [x - r, y - r, x + r, y + r], 0.65, r * 0.35, (r * 0.3, r * 0.45))
    p.ellipse([x - r, y - r, x + r, y + r], None, grad=((0xf4, 0xf2, 0xee), (x - r * 0.4, y - r * 0.5), (0x6d, 0x6a, 0x64), (x + r, y + r), True))
    p.ellipse([x - r, y - r, x + r, y + r], BLACK, 0.25, width=0.8)


def wave_glyph(p, kind, cx, cy, w, h, colour=INK):
    """The LFO's printed wave signs: triangle and square."""
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    if kind == "TRI":
        pts = [(x0, cy), (x0 + w / 4, y0), (x0 + 3 * w / 4, y1), (x1, cy)]
    elif kind == "SQR":
        pts = [(x0, y1), (x0, y0), (cx, y0), (cx, y1), (x1, y1), (x1, y0)]
    elif kind == "RND":   # sample and hold: steps
        k = w / 4
        lv = [0.6, 0.0, 1.0, 0.35]
        pts = []
        for i, v in enumerate(lv):
            yy = y0 + h * v
            pts += [(x0 + i * k, yy), (x0 + (i + 1) * k, yy)]
    else:                 # noise: a scribble
        lv = [0.5, 0.1, 0.8, 0.25, 0.95, 0.0, 0.7, 0.3, 0.9, 0.5]
        pts = [(x0 + w * i / (len(lv) - 1), y0 + h * v) for i, v in enumerate(lv)]
    p.line(pts, 2.0, colour)


def film(name, w, h, frames, scale, ox, oy, draw, base=None):
    """A film strip w x h per frame: draw(painter, f) on a painter showing page box (ox, oy) at `scale`."""
    assert h * frames <= 16384, "%s: film strip too tall for the MPC" % name
    strip = Image.new("RGBA", (w, h * frames), (0, 0, 0, 0))
    for f in range(frames):
        p = base.copy() if base else Painter(w, h, ox / scale, oy / scale, scale)
        draw(p, f)
        strip.paste(p.result(), (0, f * h))
    return save(strip, name)


def wordmark(p, cx, cy, cap):
    """MONO-101 in Earth Normal (it has no dash: drawn)."""
    a, b = "MONO", "101"
    wa, wb = text_width(a, cap, LOGO_FILE, 0.70, 0), text_width(b, cap, LOGO_FILE, 0.70, 0)
    dash, gap = cap * 0.62, cap * 0.16
    x = cx - (wa + wb + dash + 2 * gap) / 2

    def ink(q):
        q.text(a, [x, cy - cap / 2, x + wa, cy + cap / 2], cap, INK, sx=1.0, font_file=LOGO_FILE, cap_ratio=0.70, bolden=0)
        q.box([x + wa + gap, cy - cap * 0.09, x + wa + gap + dash, cy + cap * 0.09], INK)
        x2 = x + wa + dash + 2 * gap
        q.text(b, [x2, cy - cap / 2, x2 + wb, cy + cap / 2], cap, INK, sx=1.0, font_file=LOGO_FILE, cap_ratio=0.70, bolden=0)
    printed(p, ink)


def scale(p, cx, top, h, left=True, right=True, numbers_left=False, numbers_right=False):
    """The 0-10 scale either side of a slider's channel, as printed on the panel: 11 ticks; on a section's outer
    sliders the numerals 10, 5 and 0 stand in for their ticks."""
    y_top, y_bot = top + CAP_H / 2, top + h - CAP_H / 2
    for side, on, nums in ((-1, left, numbers_left), (1, right, numbers_right)):
        if not on:
            continue
        for i in range(11):
            y = y_bot - (y_bot - y_top) * i / 10
            x0, x1 = (cx - 30, cx - 21) if side < 0 else (cx + 21, cx + 30)
            if nums and i % 5 == 0:
                legend(p, str(i), (x0 + x1) / 2, y, 8.5)
            else:
                printed(p, lambda q, y=y, x0=x0, x1=x1: q.box([x0, y - 1.3, x1, y + 1.3], INK, r=1.1))


def fader_bed(p, cx, top, h):
    """The fader's recessed channel and its slot (Lemus's channel(), as wells)."""
    y_top, y_bot = top + CAP_H / 2, top + h - CAP_H / 2
    ch = [cx - 17, top - 4, cx + 17, top + h + 4]
    well(p, ch, darker(C["panel"], 0.06), r=1.5, depth=3.0, alpha=0.65, lip=0.32)
    well(p, [cx - 4, y_top - 8, cx + 4, y_bot + 8], C["slot_black"], r=2, depth=4.0, alpha=0.9, lip=0.18)


def value_well(p, x0, y0, x1, y1):
    well(p, [x0, y0, x1, y1], (0x1d, 0x1c, 0x1b), r=5, depth=2.5, alpha=0.8, lip=0.3)
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


def entry(name, typ, data, b, remap=None, focus="No", ind=None):
    bd = {"version": 2 if ind else 1, "acceptsHWFocus": focus, "showWhenDataModelInvalid": "Show", "whenVisible": "Always",
          "boundsType": "Absolute", "bounds": b}
    if ind:   # shown only while the handle has that index (needs bounds version 2)
        bd["additionalInvalidatingHandles"] = ind
    return {"version": 2,
            "componentData": {"version": 1, "name": name, "type": typ, "data": data},
            "handle remapping": {"version": 1, "map": [{"key": "Data", "value": remap}] if remap else []},
            "bounds": bd}


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




def label(b, remap, h=22.0, colour="ffedede8", just="horizontallyCentred verticallyCentred", ind=None):
    style = {"version": 1, "font": {"version": 1, "name": LABEL_FONT, "style": "SemiBold", "height": h}, "colour": colour,
             "justification": just, "case": "Original"}
    return entry("label", "Label", {"version": 1, "textStyle": style, "type": "Value", "handleName": "Data"}, b, remap, ind=ind)


# ---- presets: SAVE / DELETE PRESET and the naming keyboard (the plugin's kb_open shows it) ------------------------------------
FAV_NAME_MAX = 20           # the plugin's kFavNameMax
KB_ROWS = [("1234567890", ["kb_bksp"]), ("QWERTYUIOP", []), ("ASDFGHJKL-", []), ("ZXCVBNM", ["kb_space"])]


def sh_key(w, h, caption, lit, cap_h=None):
    """A key as the SH-101's buttons: a light grey cap in a dark well, its name printed dark; pressed, it sits lower."""
    p = Painter(w, h, 0, 0, 1.0)
    p.box([0, 0, w, h], (0x15, 0x14, 0x14), r=6)
    p.well([0, 0, w, h], r=6, depth=2.5, alpha=0.8, lip=0)
    dy = 1.4 if lit else 0.0
    cap = [3.5, 3.5 + dy, w - 3.5, h - 3.5 + dy]
    p.soft("box", cap, 0.7, 1.4, (1.0, 1.8), r=3)
    top, bot = brighter(C["cap_light"], 0.08), darker(C["cap_light"], 0.22)
    if lit:
        top, bot = darker(top, 0.12), darker(bot, 0.12)
    p.box(cap, None, r=3, grad=(top, (0, cap[1]), bot, (0, cap[3])))
    p.box([cap[0] + 1.5, cap[1] + 0.8, cap[2] - 1.5, cap[1] + 1.8], WHITE, 0.55)
    p.box([cap[0] + 1.5, cap[3] - 1.6, cap[2] - 1.5, cap[3] - 0.6], BLACK, 0.25)
    cap_h = cap_h or min(h * 0.28, 12)
    tw = text_width(caption, cap_h)
    sx = min(1.0, (cap[2] - cap[0] - 10) / tw)
    cx, cy = (cap[0] + cap[2]) / 2, (cap[1] + cap[3]) / 2
    p.text(caption, [cx - tw * sx / 2, cy - cap_h / 2, cx + tw * sx / 2, cy + cap_h / 2], cap_h, (0x2a, 0x28, 0x26), sx=sx)
    return p.result()


def slug(k):   # exFAT is case-insensitive: one file name per key, whatever its caption
    return re.sub(r"[^a-z0-9_]", "_", k.lower())


def momentary(key, caption, x, y, w, h, cap_h=None, ind=None):
    """A momentary button (the plugin drops it back to 0)."""
    on = save(sh_key(w, h, caption, True, cap_h), slug(key) + "_on.png")
    off = save(sh_key(w, h, caption, False, cap_h), slug(key) + "_off.png")
    return entry(key, "Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": 1, "numButtonsInGroup": 1,
                                 "handleName": "Data", "gestureBehaviour": GESTURE}, B(x, y, w, h), P(key), ind=ind)


def keyboard(p):
    """The drawn keyboard for naming a preset: a full-page panel, the name, 42 keys; shown while kb_open = 1."""
    ind = ["IndexedEnabling/1/2/%s" % P("kb_open")]
    q = Painter(W, H, 0, 0, 1.0)
    pc = C["panel"]
    q.box([0, 0, W, H], None, grad=(brighter(pc, 0.06), (0, 0), darker(pc, 0.04), (0, H)))
    sections(q, [("", 16, W - 16)], Y0, Y1, head=0)
    legend(q, "PRESET NAME", 48, 53, 15, align="l")
    value_well(q, 300, 26, 1210, 80)
    legend(q, "MAX %d CHARACTERS" % FAV_NAME_MAX, 1196, 98, 8.5, colour=darker(INK, 0.2), align="r")
    panel = save(surface(q.result(), seed=7).convert("RGB"), "kb_panel.png")
    p.kids.append(entry("kb panel", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": panel}, B(0, 0, W, H), ind=ind))
    p.kids.append(label(B(316, 26, 880, 54), P("fav_name"), h=40.0, just="left verticallyCentred", ind=ind))
    kw, kh, gap, x0, y0 = 98, 82, 8, 70, 112
    for r, (chars, extra) in enumerate(KB_ROWS):
        y = y0 + r * (kh + gap)
        x = x0 + r * 30
        for c in chars:
            p.kids.append(momentary("kb_" + ("dash" if c == "-" else c.lower()), c, x, y, kw, kh, cap_h=20, ind=ind))
            x += kw + gap
        for k in extra:
            p.kids.append(momentary(k, {"kb_bksp": "DEL", "kb_space": "SPACE"}[k], x, y, 1210 - x, kh, cap_h=17, ind=ind))
    y = y0 + 4 * (kh + gap)
    p.kids.append(momentary("kb_shift", "SHIFT", x0, y, 200, kh, cap_h=17, ind=ind))
    p.kids.append(momentary("kb_cancel", "CANCEL", 640 - 130, y, 260, kh, cap_h=17, ind=ind))
    p.kids.append(momentary("kb_save", "SAVE", 1210 - 260, y, 260, kh, cap_h=17, ind=ind))


# ---- a tab -----------------------------------------------------------------------------------------------------------------
class Page:
    def __init__(self, name, fn):
        self.name, self.fn, self.kids, self.extent, self.qrows = name, fn, [], {}, []
        self.p = Painter(W, H, 0, 0, 1.0)
        pc = C["panel"]
        self.p.box([0, 0, W, H], None, grad=(brighter(pc, 0.06), (0, 0), darker(pc, 0.04), (0, H)))

    def fader(self, key, cx, top, stripe, h=FH, value=True, numbers=(False, False)):
        fader_bed(self.p, cx, top, h)
        scale(self.p, cx, top, h, numbers_left=numbers[0], numbers_right=numbers[1])
        name = fader_strip(stripe, h)
        l, t, r, b = STRIP_PAD
        w, fh = l + r, t + h + b
        self.kids.append(entry(key, strip_def(name, w, fh, fader_frames(h)), {"version": 1, "handleName": "Data"},
                               B(cx - l, top - t, w, fh), P(key), focus="Yes"))
        if value:
            value_well(self.p, cx - 34, top + h + 12, cx + 34, top + h + 38)
            self.kids.append(label(B(cx - 34, top + h + 12, 68, 26), P(key), h=24.0))
        self.extent[key] = (cx - 36, top - 6, cx + 36, top + h + 42)

    def knob(self, key, cx, cy, strip, ticks=11, side=False):
        for i in range(ticks):   # the printed scale
            a = -KNOB_SWEEP + 2 * KNOB_SWEEP * i / (ticks - 1)
            printed(self.p, lambda q, a=a: q.line([polar(cx, cy, KNOB_R + 7, a), polar(cx, cy, KNOB_R + (15 if i % 5 == 0 else 12), a)], 2.4, INK))
        self.kids.append(entry(key, strip_def(strip, KNOB_BOX, KNOB_BOX, KNOB_FRAMES), {"version": 1, "handleName": "Data"},
                               B(cx - KNOB_C, cy - KNOB_C, KNOB_BOX, KNOB_BOX), P(key), focus="Yes"))
        if side:   # the value to the right of the knob, under its name
            value_well(self.p, cx + 80, cy - 4, cx + 180, cy + 23)
            self.kids.append(label(B(cx + 80, cy - 4, 100, 27), P(key), h=24.0))
            self.extent[key] = (cx - 64, cy - 62, cx + 184, cy + 62)
        else:
            value_well(self.p, cx - 50, cy + 92, cx + 50, cy + 119)
            self.kids.append(label(B(cx - 50, cy + 92, 100, 27), P(key), h=24.0))
            self.extent[key] = (cx - 76, cy - 64, cx + 76, cy + 124)

    def zones(self, key, boxes, ids=None):
        """Transparent radio buttons: tap a position (or its legend) to pick it."""
        n = len(boxes)
        for i, z in enumerate(boxes):
            bid = ids[i] if ids else i
            self.kids.append(entry("%s %d" % (key, bid), "Button", {"version": 2, "onImage": "blank.png", "offImage": "blank.png",
                                                                   "buttonId": bid, "numButtonsInGroup": n, "handleName": "Data",
                                                                   "gestureBehaviour": GESTURE}, B(*[int(round(v)) for v in z]), P(key)))
        self.extent[key] = (min(z[0] for z in boxes), min(z[1] for z in boxes), max(z[0] + z[2] for z in boxes), max(z[1] + z[3] for z in boxes))

    def strip(self, key, name, b, frames):
        self.kids.append(entry(key, strip_def(name, b[2], b[3], frames), {"version": 1, "handleName": "Data"}, B(*b), P(key), focus="Yes"))

    def vswitch(self, key, cx, top, cap=9.5, limit=None, order=None):
        """A slide switch as on the panel: a black cap with a yellow line in a recessed slot, position 0 at the top; the
        legends to its right. Each row (cap and legend) is a tap target."""
        opts = CHOICES[key]
        n = len(opts)
        order = order or list(range(n))   # which choice each position (top to bottom) is
        ys = [top + SW_H / 2 + i * SW_PITCH for i in range(n)]
        bot = ys[-1] + SW_H / 2
        well(self.p, [cx - SW_W / 2 - 4, top - 4, cx + SW_W / 2 + 4, bot + 4], darker(C["panel"], 0.06), r=1.5, depth=2.5, alpha=0.65, lip=0.32)
        well(self.p, [cx - 4, ys[0] - 6, cx + 4, ys[-1] + 6], C["slot_black"], r=2, depth=3.0, alpha=0.9, lip=0.18)
        right = cx + SW_W / 2 + 14 + max(text_width(o, cap) for o in opts) + 6
        right = min(right, limit) if limit else right
        for o, y in zip([opts[i] for i in order], ys):
            printed(self.p, lambda q, y=y: q.box([cx + SW_W / 2 + 6, y - 1.2, cx + SW_W / 2 + 10, y + 1.2], INK, r=1))
            legend(self.p, o, cx + SW_W / 2 + 14, y, cap, align="l")
        b = [int(cx - SW_W / 2 - 4), int(top - 4), SW_W + 14, int(bot - top) + 14]
        m = SW_W / SW_MM
        name = film("sw_%s.png" % key, b[2], b[3], n, m, b[0], b[1], lambda p, f: switch_cap(p, cx / m, ys[order.index(f)] / m, SW_MM - 0.4, SW_H / m))
        self.strip(key, name, b, n)
        x0 = cx - SW_W / 2 - 6
        self.zones(key, [(x0, y - SW_PITCH / 2, right - x0, SW_PITCH) for y in ys], ids=order)

    def rotary(self, key, cx, cy, glyphs=False):
        """A rotary switch as on the panel (WAVE, RANGE): a small black knob with detent ticks and the legends round its
        top. The columns over it are tap targets (left column, first position)."""
        opts = CHOICES[key]
        n = len(opts)
        det = ROT_DETENTS[n]
        r = ROT_R
        for i, (o, a) in enumerate(zip(opts, det)):
            printed(self.p, lambda q, a=a: q.line([polar(cx, cy, r + 6, a), polar(cx, cy, r + 12, a)], 2.4, INK))
            lx, ly = polar(cx, cy, r + 26, a)
            if glyphs:
                printed(self.p, lambda q, o=o, lx=lx, ly=ly: wave_glyph(q, o, lx, ly, 20, 11))
            elif abs(a) > 60:   # the low positions: legends beside the knob, reading away from it
                legend(self.p, o, lx + (8 if a > 0 else -8), ly, 10, align="l" if a > 0 else "r")
            elif n > 4:         # the top pair: reading away from each other
                legend(self.p, o, lx + (-8 if a > 0 else 8), ly, 10, align="l" if a > 0 else "r")
            else:
                legend(self.p, o, lx, ly, 11)
        m = r / KNOB_MM
        bx = [int(cx - r - 4), int(cy - r - 4), int(2 * r + 12), int(2 * r + 14)]
        base = Painter(bx[2], bx[3], bx[0] / m, bx[1] / m, m)
        knob_body(base, cx / m, cy / m, KNOB_MM)
        name = film("sw_%s.png" % key, bx[2], bx[3], n, m, bx[0], bx[1],
                    lambda p, f: draw_pointer(p, cx / m, cy / m, KNOB_MM, det[f]), base)
        self.strip(key, name, bx, n)
        if n > 4:   # a tap target on each legend; the knob itself drags
            boxes = []
            for o, a in zip(opts, det):
                lx, ly = polar(cx, cy, r + 26, a)
                tw = text_width(o, 10)
                if abs(a) > 60:
                    x0 = lx + 2 if a > 0 else lx - tw - 14
                    boxes.append((x0, ly - 15, tw + 12, 30))
                else:
                    x0 = lx - 10 if a > 0 else lx - tw - 10
                    boxes.append((x0, ly - 15, tw + 20, 30))
            self.zones(key, boxes)
            self.extent[key] = (min(self.extent[key][0], bx[0]), self.extent[key][1], max(self.extent[key][2], bx[0] + bx[2]), max(self.extent[key][3], bx[1] + bx[3]))
            return
        span, top = 128, cy - r - 44
        cw = span / n
        self.zones(key, [(cx - span / 2 + i * cw, top, cw, cy + r + 10 - top) for i in range(n)])

    def hswitch(self, key, cx, y, order=None, cap=10, pitch=HS_PITCH):
        """A lever switch as on the panel (PORTAMENTO, TRANSPOSE): a light round lever in a black slot, the legends above.
        order: which choice each position (left to right) is."""
        opts = CHOICES[key]
        n = len(opts)
        order = order or list(range(n))
        xs = [cx + (i - (n - 1) / 2) * pitch for i in range(n)]
        hr = HS_LEVER / 2 + 2
        sl = [xs[0] - hr - 4, y - hr, xs[-1] + hr + 4, y + hr]
        self.p.box(sl, C["slot_black"], r=hr)
        self.p.well(sl, r=hr, depth=2.5, alpha=0.9, lip=0.28)
        for i, x in enumerate(xs):
            legend(self.p, opts[order[i]], x, y - hr - 14, cap)
        b = [int(sl[0]) - 2, int(sl[1]) - 2, int(sl[2] - sl[0]) + 8, int(sl[3] - sl[1]) + 8]
        name = film("sw_%s.png" % key, b[2], b[3], n, 1.0, b[0], b[1], lambda p, f: lever(p, xs[order.index(f)], y, HS_LEVER / 2))
        self.strip(key, name, b, n)
        top = y - hr - 30
        self.zones(key, [(x - pitch / 2, top, pitch, y + hr + 6 - top) for x in xs], ids=order)

    def caption(self, cx, y, text, cap=11.0):
        legend(self.p, text, cx, y, cap)

    def art(self):
        return save(surface(self.p.result(), seed=self.fn).convert("RGB"), "%s.png" % self.name.lower())

    def tab(self, art):
        kids = [entry("bg", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": art}, B(0, 0, W, H))] + self.kids
        rects = []
        for g in self.qrows:
            assert 1 <= len(g) <= 4, g
            ex = [self.extent[k] for k in g]
            rects.append((max(min(e[0] for e in ex), 2), max(min(e[1] for e in ex), 2),
                          min(max(e[2] for e in ex), W - 2), min(max(e[3] for e in ex), H - 2)))
        for i in range(len(rects)):
            for j in range(i):
                a, b = rects[i], rects[j]
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], "%s: Q-Link blocks %d and %d overlap" % (self.name, j, i)
        self.rects = rects
        return {"version": 1, "tabName": self.name, "fnKeyIndex": self.fn, "fnKeySubIndex": 0,
                "componentDefinition": component(kids, background=bg("ff6e6c67")),
                "qlinkBoundsData": [B(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in rects]}


# ---- the tabs ------------------------------------------------------------------------------------------------------------
TOP = 96                     # faders' top
Y0, Y1 = 8, H - 8            # the section boxes


def page_one():
    """CONTROLLER (stacked), BENDER, MODULATOR and VCO: the panel's left side, each switch under its section's faders."""
    p = Page("VCO", 0)
    kstrip = knob_strip("knob.png")
    sections(p.p, [("CONTROLLER", 16, 330), ("BENDER", 330, 620), ("MODULATOR", 620, 800), ("VCO", 800, 1264)], Y0, Y1)
    sy = TOP + FH + 54                       # the switches' row
    # CONTROLLER: the knobs one above the other, each with its name and value to the right; the portamento switch below
    for key, cap, cy, lo, hi in [("volume", "VOLUME", 124, "0", "10"), ("tune", "TUNE", 262, "-5", "+5"),
                                 ("portamento", "PORTAMENTO", 400, "0", "10")]:
        cx = 92
        p.knob(key, cx, cy, kstrip, side=True)
        legend(p.p, cap, cx + 130, cy - 24, 11 if len(cap) > 6 else 12, fit=110)
        legend(p.p, lo, cx - 50, cy + 60, 9)
        legend(p.p, hi, cx + 50, cy + 60, 9)
    p.caption(173, 496, "PORTAMENTO", 10)
    p.hswitch("porta_mode", 173, 566, order=[1, 2, 0], pitch=62)   # the panel's AUTO / OFF / ON
    # BENDER: its three sliders, TRANSPOSE under them
    for key, cap, cx in [("bend_vco", "VCO", 385), ("bend_vcf", "VCF", 475), ("bend_lfo", "LFO MOD", 565)]:
        p.caption(cx, TOP - 20, cap)
        p.fader(key, cx, TOP, "orange", numbers=(key == "bend_vco", key == "bend_lfo"))
    p.caption(475, sy, "TRANSPOSE", 10)
    p.hswitch("transpose", 475, sy + 92, pitch=56)
    legend(p.p, "PITCH BEND: VCO, VCF", 475, 584, 8, colour=darker(INK, 0.2))
    legend(p.p, "MOD WHEEL: LFO MOD", 475, 602, 8, colour=darker(INK, 0.2))
    # MODULATOR: RATE, the wave switch under it
    p.caption(710, TOP - 20, "RATE")
    p.fader("lfo_rate", 710, TOP, "green", numbers=(True, True))
    p.caption(710, sy, "WAVE", 10)
    p.rotary("lfo_wave", 710, sy + 112, glyphs=True)
    # VCO: MOD with RANGE under it, PW with PWM under it
    p.caption(920, TOP - 20, "MOD")
    p.fader("vco_mod", 920, TOP, "orange", numbers=(True, True))
    p.caption(920, sy, "RANGE", 10)
    p.rotary("range", 920, sy + 112)
    p.caption(1144, TOP - 20, "PW")
    p.fader("pulse_width", 1144, TOP, "orange", numbers=(True, True))
    p.caption(1144, sy, "PWM", 10)
    p.vswitch("pwm_source", 1120, sy + 30, cap=11)
    p.qrows = [["volume", "tune", "portamento", "porta_mode"], ["bend_vco", "bend_vcf", "bend_lfo", "transpose"],
               ["lfo_rate", "lfo_wave"], ["vco_mod", "range", "pulse_width", "pwm_source"]]
    return p, p.art()


PITCH2, X2 = 87, 16
COLS2 = ["pulse_level", "saw_level", "sub_level", "noise_level", "vcf_freq", "vcf_res", "vcf_env", "vcf_mod", "vcf_kybd",
         "attack", "decay", "sustain", "release"]
CAPS = {"pulse_level": "PULSE", "saw_level": "SAW", "sub_level": "SUB", "noise_level": "NOISE", "vcf_freq": "FREQ",
        "vcf_res": "RES", "vcf_env": "ENV", "vcf_mod": "MOD", "vcf_kybd": "KYBD", "attack": "A", "decay": "D", "sustain": "S",
        "release": "R"}
VCA_W = 110


def x2(i):
    """Column i's left edge: the VCA's column sits between the VCF's and the ENV's."""
    return X2 + PITCH2 * i + (VCA_W if i >= 9 else 0)


def page_two():
    """SOURCE MIXER, VCF, VCA, ENV: the faders with the switches under them; QUALITY in the VCA column's foot."""
    p = Page("VCF", 1)
    vca0, env1 = x2(9) - VCA_W, x2(13)
    sy = TOP + FH + 54
    sections(p.p, [("SOURCE MIXER", x2(0), x2(4)), ("VCF", x2(4), vca0), ("VCA", vca0, x2(9)), ("ENV", x2(9), env1)], Y0, Y1)
    qy = sy - 14                             # QUALITY: a box of its own under the VCA's switch
    groove(p.p, (vca0, qy), (x2(9), qy))
    groove(p.p, (vca0, qy + 40), (x2(9), qy + 40))
    legend(p.p, "QUALITY", vca0 + VCA_W / 2, qy + 21, 13, fit=VCA_W - 14)
    for i, key in enumerate(COLS2):
        sec = 0 if i < 4 else 4 if i < 9 else 9
        last = 3 if i < 4 else 8 if i < 9 else 12
        cx = x2(i) + PITCH2 // 2
        p.caption(cx, TOP - 20, CAPS[key])
        p.fader(key, cx, TOP, "green" if i < 4 else "orange", numbers=(i == sec, i == last))
    mx = (x2(0) + x2(4)) // 2
    p.caption(mx, sy, "SUB OSC", 10)
    p.vswitch("sub_mode", mx - 46, sy + 30, cap=11)
    ex = (x2(9) + env1) // 2
    p.caption(ex, sy, "TRIGGER", 10)
    p.vswitch("env_trigger", ex - 56, sy + 30, cap=11)
    p.caption(vca0 + VCA_W // 2, TOP - 20, "MODE")
    p.vswitch("vca_mode", vca0 + 30, TOP + 10, cap=10, limit=x2(9) + 2)
    p.vswitch("quality", vca0 + 30, qy + 58, cap=10, limit=x2(9) + 2)
    vx = (x2(4) + vca0) // 2
    wordmark(p.p, vx, sy + 50, 36)
    legend(p.p, "MONOPHONIC SYNTHESIZER", vx, sy + 92, 10)
    legend(p.p, "CIRCUIT MODEL BY LEMUS", vx, sy + 114, 8.5, colour=darker(INK, 0.25))
    # presets: SAVE PRESET names the sound on the drawn keyboard; DELETE PRESET empties the picked user preset
    p.kids.append(momentary("fav_add", "SAVE PRESET", int(vx) - 186, sy + 144, 176, 52))
    p.kids.append(momentary("fav_del", "DELETE PRESET", int(vx) + 10, sy + 144, 176, 52))
    p.qrows = [COLS2[0:4], COLS2[4:8], ["vcf_kybd", "vca_mode"], COLS2[9:13]]
    art = p.art()
    keyboard(p)   # last: over everything while it shows
    return p, art


MODS = [("MODS", 16, 156), ("FILTER OVERDRIVE", 156, 356), ("PWM SOURCE", 356, 596), ("VCF FM", 596, 940),
        ("LFO RANGE", 940, 1102), ("LFO TRIG", 1102, 1264)]


def page_three():
    """The circuitbenders SH-101 mods, laid out as the other tabs: each mod's ON / OFF switch and its sliders on top, its
    rotary under them; the master PURE / MODDED switch first (PURE: the stock board whatever the mods' own switches say)."""
    p = Page("MODS", 2)
    sections(p.p, MODS, Y0, Y1, cap=15)
    on = [1, 0]                              # ON at the top, as a toggle
    sy = TOP + FH + 54                       # the switches' row under the sliders
    dim = darker(INK, 0.2)
    # the master switch
    p.caption(86, TOP - 20, "ALL MODS", 10)
    p.vswitch("mods", 40, TOP + 10, cap=10, order=on)
    for i, t in enumerate(["PURE: THE STOCK", "SH-101, EVERY", "MOD BYPASSED", "", "MODDED: EACH", "MOD BY ITS OWN", "SWITCH"]):
        if t:
            legend(p.p, t, 86, sy + 20 + i * 22, 8, colour=dim, fit=124)
    # FILTER OVERDRIVE: ON / OFF, the DRIVE slider
    p.caption(210, TOP - 20, "MOD", 10)
    p.vswitch("drive_on", 196, TOP + 10, cap=11, order=on)
    p.caption(302, TOP - 20, "DRIVE")
    p.fader("drive", 302, TOP, "orange", numbers=(True, True))
    for i, t in enumerate(["THE MIXER INTO", "THE VCF, HARDER:", "1X TO 8X"]):
        legend(p.p, t, 256, sy + 20 + i * 22, 8, colour=dim, fit=186)
    # PWM SOURCE: ON / OFF, the source under it
    p.caption(410, TOP - 20, "MOD", 10)
    p.vswitch("pwm_mod_on", 396, TOP + 10, cap=11, order=on)
    for i, t in enumerate(["FOR THE PWM", "SWITCH'S LFO", "POSITION", "(VCO TAB)"]):
        legend(p.p, t, 530, TOP + 10 + i * 22, 8, colour=dim, fit=110)
    p.caption(476, sy, "SOURCE", 10)
    p.rotary("pwm_mod_source", 476, sy + 112)
    # VCF FM: ON / OFF, the AMOUNT slider; the source under them
    p.caption(680, TOP - 20, "MOD", 10)
    p.vswitch("fm_on", 666, TOP + 10, cap=11, order=on)
    p.caption(860, TOP - 20, "AMOUNT")
    p.fader("fm_amount", 860, TOP, "orange", numbers=(True, True))
    p.caption(768, sy, "SOURCE", 10)
    p.rotary("fm_source", 768, sy + 112)
    # LFO RANGE: SLOW / NORMAL / FAST, FAST at the top
    p.caption(1021, TOP - 20, "RANGE", 10)
    p.vswitch("lfo_range", 990, TOP + 10, cap=11, order=[2, 1, 0])
    for i, t in enumerate(["FAST: TO 550 HZ", "NORM: 12 S - 36 HZ", "SLOW: 50 S - 9 HZ"]):
        legend(p.p, t, 1021, sy + 20 + i * 22, 8, colour=dim, fit=150)
    # LFO TRIG: ON / OFF
    p.caption(1183, TOP - 20, "KEY TRIG", 10)
    p.vswitch("lfo_trig", 1150, TOP + 10, cap=11, order=on)
    for i, t in enumerate(["ON: THE LFO", "RESTARTS ON", "EACH KEY"]):
        legend(p.p, t, 1183, sy + 20 + i * 22, 8, colour=dim, fit=150)
    p.qrows = [["mods", "drive_on", "drive"], ["pwm_mod_on", "pwm_mod_source"], ["fm_on", "fm_amount", "fm_source"],
               ["lfo_range", "lfo_trig"]]
    return p, p.art()


# ---- preview (defaults, offline) ------------------------------------------------------------------------------------------
def render_preview(p, art, defaults, zones=False, keyboard_open=False):
    img = Image.open(os.path.join(OUT, art)).convert("RGBA")
    d = ImageDraw.Draw(img)
    tf = lambda px: ImageFont.truetype(os.path.join(FONTS, "TitilliumWeb-SemiBold.ttf"), int(round(px)))
    for k in p.kids:
        if ("additionalInvalidatingHandles" in k["bounds"]) != keyboard_open:
            continue
        cd, (x, y, w, h) = k["componentData"], [int(v) for v in k["bounds"]["bounds"].split()]
        typ, data = cd["type"], cd["data"]
        remap = k["handle remapping"]["map"]
        idx = int(remap[0]["value"].split()[-1]) if remap else None
        spec = defaults[idx] if idx is not None else {}
        if typ.startswith("ctl_"):
            sd = DEFS[typ]["componentsData"][1]["componentData"]["data"]
            strip = Image.open(os.path.join(OUT, sd["filmStrip"])).convert("RGBA")
            fr = int(round(spec["default"] * (sd["numFrames"] - 1)))
            img.alpha_composite(strip.crop((0, fr * h, w, fr * h + h)), (x, y))
        elif typ == "Button":
            n = data["numButtonsInGroup"]
            cur = int(round(spec["default"] * (n - 1)))
            img.alpha_composite(Image.open(os.path.join(OUT, data["onImage" if cur == data["buttonId"] else "offImage"])).convert("RGBA"), (x, y))
        elif typ == "Image":
            img.alpha_composite(Image.open(os.path.join(OUT, data["image"])).convert("RGBA"), (x, y))
        elif typ == "Label":
            st = data["textStyle"]
            if keyboard_open:
                d.text((x + 6, y + h / 2), "Acid Bass_", font=tf(st["font"]["height"] * DEVICE_TEXT), fill=INK, anchor="lm")
            else:
                d.text((x + w / 2, y + h / 2), spec.get("display", ""), font=tf(st["font"]["height"] * DEVICE_TEXT), fill=INK, anchor="mm")
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
    pages = [page_one(), page_two(), page_three()]
    tabs = [p.tab(art) for p, art in pages]
    maps = []
    for p, _ in pages:
        q = {"Q-Link %d" % n: -1 for n in range(1, 17)}
        for gi, keys in enumerate(p.qrows):
            for i, key in enumerate(keys):
                q["Q-Link %d" % (13 - 4 * gi + i)] = LOCK.index(key)
        maps.append({"Tab": p.fn + 1, "SubTab": 1, "Bank Direction": "RowTopDown", "Q-Links": q})
    defs = [{"key": "knob overlay", "value": overlay_def()}] + [{"key": k, "value": v} for k, v in DEFS.items()]
    repl = [{"key": P(k), "value": v} for k, v in CHOICES.items()]
    tui = {"pageData": {"version": 1,
                        "componentDefinitions": {"version": 2, "importFiles": [], "localComponentDefinitions": defs},
                        "replacementStrings": repl, "info": {"version": 1, "type": "CompleteDescription"}, "tabs": tabs}}
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
        for p, art in pages:
            img = render_preview(p, art, defaults)
            img.convert("RGB").save(os.path.join(PREVIEW, p.name.lower() + ".png"))
            render_preview(p, art, defaults, zones=True).convert("RGB").save(os.path.join(PREVIEW, p.name.lower() + "-qlinks.png"))
            if any("additionalInvalidatingHandles" in k["bounds"] for k in p.kids):
                render_preview(p, art, defaults, keyboard_open=True).convert("RGB").save(os.path.join(PREVIEW, p.name.lower() + "-keyboard.png"))
    print("wrote %s - %d tabs, %d files, %d KB" % (OUT, len(tabs), len(names), sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) // 1024))


if __name__ == "__main__":
    main()
