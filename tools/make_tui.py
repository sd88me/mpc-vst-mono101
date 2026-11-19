#!/usr/bin/env python3
"""Mono-101's native MPC skin: skins/TUI.json + skins/Q-Links.json + the PNGs they use, all art drawn here (Pillow,
Titillium Web OFL). After OTT's / Acid's make_tui.

Two tabs:
    PANEL    the synth board's sections as on the instrument: MODULATOR, VCO, SOURCE MIXER, VCF, VCA, ENV. Sixteen faders
             (Knob film strips dragged vertically), the switches as lit radio groups.
    CONTROL  VOLUME, TUNE, PORTAMENTO (+ mode), the bender's VCO / VCF / LFO MOD sliders, TRANSPOSE, QUALITY.
Q-Links: PANEL four blocks of four faders, left to right; CONTROL two blocks.
    python3 tools/make_tui.py [--preview]     # -> skins/ (build-sdk.sh runs it); --preview also writes build/skin-preview/*.png
"""
import json, os, shutil, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "skins")
FONTS = os.path.join(ROOT, "tools", "fonts")
PREVIEW = os.path.join(ROOT, "build", "skin-preview")
LOCK = [l.strip() for l in open(os.path.join(ROOT, "params.lock")) if l.strip() and not l.startswith("#")]
FONT = "Titillium Web"
GESTURE = "Instant"
DEVICE_TEXT = 0.64          # the MPC draws a Label's font at about this fraction of its height
W, H = 1280, 628            # content area

# colours: a dark grey case, lighter section boxes, white legends, one blue accent (the section rules)
CASE, CASE2 = (40, 42, 46), (30, 32, 35)
BOX, BOX_EDGE = (54, 57, 62), (78, 82, 88)
INK, INK_DIM = (236, 238, 240), (150, 156, 164)
ACCENT_RGB = (86, 156, 214)
ACCENT = "ff569cd6"
WELL = (22, 23, 25)
CHOICES = {
    "lfo_wave": ["TRI", "SQR", "RND", "NOISE"], "range": ["16'", "8'", "4'", "2'"], "pwm_source": ["LFO", "MAN", "ENV"],
    "sub_mode": ["1 OCT", "2 OCT", "2 OCT PW"], "vca_mode": ["ENV", "GATE"], "env_trigger": ["GATE+TRIG", "GATE", "LFO"],
    "porta_mode": ["ON", "AUTO", "OFF"], "transpose": ["L", "M", "H"], "quality": ["HQ", "AUTO", "ECO"],
}


def P(key):
    return "Parameter %d" % LOCK.index(key)


def ttf(px, weight="SemiBold"):
    return ImageFont.truetype(os.path.join(FONTS, "TitilliumWeb-%s.ttf" % weight), int(round(px)))


# ---- JSON (keeps key order; the overlay widget has a duplicate "version" key) --------------------------------------------
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


FOCUS = {"version": 1, "backgroundColour": "00000000", "outlineColour": ACCENT, "backgroundInset": 4.0, "outlineThickness": 2.0}
QL = [act("Mouse Down", "Q-Link"), act("Double Click", "Show Overlay", "knob overlay"), act("Enter Pressed", "Show Overlay", "knob overlay")]


def focus_ring(b):
    e = entry("focus", "Focus", FOCUS, b)
    e["bounds"]["whenVisible"] = "WhenFocussed"
    return e


def label(b, remap, h=22.0, colour="ffeceef0"):
    style = {"version": 1, "font": {"version": 1, "name": FONT, "style": "SemiBold", "height": h}, "colour": colour,
             "justification": "horizontallyCentred verticallyCentred", "case": "Original"}
    return entry("label", "Label", {"version": 1, "textStyle": style, "type": "Value", "handleName": "Data"}, b, remap)


def overlay_def():
    return component([entry("overlay", "KnobOverlay", Obj(
        ("version", 2), ("version", 1),
        ("actions", [{"version": 1, "onAction": "Focus Lost", "handler": "Focus Lost", "handleName": "Focus Lost", "additionalData": ""}]),
        ("overlayType", "Knob With Header"), ("scaleType", "Linear"), ("polarityType", "Unipolar"),
        ("showMinusSign", True), ("handleName", "Data")), "0 0 1280 800", focus="Yes")], ignore=True)


DEFS = {}


def strip_def(strip, w, h, frames):
    """A film strip dragged vertically (a fader or a knob), a focus ring, Q-Link on touch, the overlay on double tap / Enter."""
    key = "ctl_" + os.path.splitext(strip)[0]
    if key not in DEFS:
        DEFS[key] = component([
            focus_ring(B(-4, -4, w + 8, h + 8)),
            entry("strip", "Knob", {"version": 3, "knobType": "FilmStrip", "filmStrip": strip, "numFrames": frames, "invert": False,
                                    "dragOrientation": "Vertical", "handleName": "Data"}, B(0, 0, w, h)),
        ], actions=QL)
    return key


def save(im, name):
    im.save(os.path.join(OUT, name))
    return name


# ---- art --------------------------------------------------------------------------------------------------------------------
FW, FH = 44, 250            # fader picture (slot + cap); its travel is the cap centre from CAP_H/2 to FH - CAP_H/2
CAP_W, CAP_H = 40, 24
FADER_FRAMES = 61           # 61 x 250 px under the MPC's 16384 px strip limit
KNOB = 116
KNOB_FRAMES = 128


def fader_strip(name, short=False):
    h = 170 if short else FH
    frames = FADER_FRAMES if not short else 91
    strip = Image.new("RGBA", (FW, h * frames), (0, 0, 0, 0))
    for f in range(frames):
        im = Image.new("RGBA", (FW, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([FW // 2 - 4, 4, FW // 2 + 3, h - 5], 3, fill=(10, 10, 11), outline=(70, 72, 76))
        cy = (h - CAP_H / 2) - (h - CAP_H) * f / (frames - 1)
        x0, y0 = (FW - CAP_W) // 2, int(round(cy - CAP_H / 2))
        d.rounded_rectangle([x0 + 1, y0 + 2, x0 + CAP_W, y0 + CAP_H + 1], 4, fill=(0, 0, 0, 120))      # shadow
        d.rounded_rectangle([x0, y0, x0 + CAP_W - 1, y0 + CAP_H - 1], 4, fill=(66, 69, 74), outline=(18, 19, 21))
        d.rectangle([x0 + 2, y0 + 2, x0 + CAP_W - 3, y0 + CAP_H // 2 - 2], fill=(84, 88, 94))             # lit upper half
        d.line([(x0 + 4, y0 + CAP_H // 2), (x0 + CAP_W - 5, y0 + CAP_H // 2)], fill=(245, 245, 245), width=3)
        strip.paste(im, (0, f * h))
    assert strip.height <= 16384, "film strip too tall for the MPC"
    return save(strip, name), h, frames


def knob_strip(name):
    """128 frames, -135 to +135 degrees: a dark cap with a white pointer, the scale baked in the page."""
    import math
    s = KNOB * 3
    strip = Image.new("RGBA", (KNOB, KNOB * KNOB_FRAMES), (0, 0, 0, 0))
    for f in range(KNOB_FRAMES):
        im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c, r = s / 2, s * 0.36
        d.ellipse([c - r + 6, c - r + 9, c + r + 6, c + r + 9], fill=(0, 0, 0, 110))
        d.ellipse([c - r, c - r, c + r, c + r], fill=(30, 31, 34), outline=(12, 12, 13), width=6)
        d.ellipse([c - r * 0.82, c - r * 0.82, c + r * 0.82, c + r * 0.82], fill=(52, 55, 60))
        a = math.radians(-135 + 270 * f / (KNOB_FRAMES - 1))
        x1, y1 = c + math.sin(a) * r * 0.28, c - math.cos(a) * r * 0.28
        x2, y2 = c + math.sin(a) * r * 0.92, c - math.cos(a) * r * 0.92
        d.line([(x1, y1), (x2, y2)], fill=(245, 245, 245), width=12)
        strip.paste(im.resize((KNOB, KNOB), Image.LANCZOS), (0, f * KNOB))
    return save(strip, name)


def key_art(w, h, caption, lit):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 6, fill=(36, 70, 98) if lit else (28, 29, 32),
                        outline=ACCENT_RGB if lit else (84, 88, 94), width=2)
    if lit:   # the LED
        d.rounded_rectangle((7, h // 2 - 4, 13, h // 2 + 4), 2, fill=(255, 92, 72))
    size = 17 if len(caption) <= 6 else 15
    d.text((w / 2 + (5 if lit else 0), h / 2 + 1), caption, font=ttf(size, "Bold"), fill=INK if lit else INK_DIM, anchor="mm")
    return im


def fader_scale(d, cx, top, h, numbers=False):
    """0-10 ticks left of a fader slot; numbers on the first fader of a section (as the panel prints them)."""
    for i in range(11):
        y = top + (h - CAP_H / 2) - (h - CAP_H) * i / 10
        long = i % 5 == 0
        d.line([(cx - (30 if long else 27), y), (cx - 22, y)], fill=INK_DIM, width=2)
        if numbers and long:
            d.text((cx - 33, y), str(i), font=ttf(12), fill=INK_DIM, anchor="rm")


class Page:
    def __init__(self, name, fn):
        self.name, self.fn, self.kids, self.extent, self.qrows = name, fn, [], {}, []

    def fader(self, key, cx, top, strip, value=True):
        name, h, frames = strip
        self.kids.append(entry(key, strip_def(name, FW, h, frames), {"version": 1, "handleName": "Data"},
                               B(cx - FW // 2, top, FW, h), P(key), focus="Yes"))
        if value:
            self.kids.append(label(B(cx - 34, top + h + 6, 68, 26), P(key), h=24.0))
        self.extent[key] = (cx - 36, top - 4, cx + 36, top + h + 36)

    def knob(self, key, cx, cy, strip):
        self.kids.append(entry(key, strip_def(strip, KNOB, KNOB, KNOB_FRAMES), {"version": 1, "handleName": "Data"},
                               B(cx - KNOB // 2, cy - KNOB // 2, KNOB, KNOB), P(key), focus="Yes"))
        self.kids.append(label(B(cx - 50, cy + KNOB // 2 + 34, 100, 28), P(key), h=24.0))
        self.extent[key] = (cx - 76, cy - KNOB // 2 - 6, cx + 76, cy + KNOB // 2 + 66)

    def radio(self, key, x, y, w, h, gap=6, horizontal=False):
        opts = CHOICES[key]
        for i, o in enumerate(opts):
            on = save(key_art(w, h, o, True), "%s_%d_on.png" % (key, i))
            off = save(key_art(w, h, o, False), "%s_%d_off.png" % (key, i))
            bx, by = (x + i * (w + gap), y) if horizontal else (x, y + i * (h + gap))
            self.kids.append(entry("%s %d" % (key, i), "Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": i,
                                                                 "numButtonsInGroup": len(opts), "handleName": "Data",
                                                                 "gestureBehaviour": GESTURE}, B(bx, by, w, h), P(key)))
        n = len(opts)
        self.extent[key] = (x - 4, y - 4, x + (n * (w + gap) if horizontal else w) + 4, y + (h if horizontal else n * (h + gap)) + 4)

    def tab(self, art):
        kids = [entry("bg", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": art}, B(0, 0, W, H))] + self.kids
        rects = []
        for g in self.qrows:
            assert len(g) == 4, g
            ex = [self.extent[k] for k in g]
            rects.append((max(min(e[0] for e in ex), 2), max(min(e[1] for e in ex), 2),
                          min(max(e[2] for e in ex), W - 2), min(max(e[3] for e in ex), H - 2)))
        for i in range(len(rects)):
            for j in range(i):
                a, b = rects[i], rects[j]
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], "%s: Q-Link blocks %d and %d overlap" % (self.name, j, i)
        self.rects = rects
        return {"version": 1, "tabName": self.name, "fnKeyIndex": self.fn, "fnKeySubIndex": 0,
                "componentDefinition": component(kids, background=bg("ff28292e")),
                "qlinkBoundsData": [B(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in rects]}


def page_base():
    im = Image.new("RGB", (W, H), CASE)
    d = ImageDraw.Draw(im)
    for y in range(H):   # a slight vertical shade
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(CASE[i] * (1 - t) + CASE2[i] * t) for i in range(3)))
    return im, d


def section(d, x0, x1, y0, y1, title):
    d.rounded_rectangle([x0, y0, x1, y1], 8, fill=BOX, outline=BOX_EDGE, width=2)
    d.rectangle([x0 + 10, y0 + 30, x1 - 10, y0 + 32], fill=ACCENT_RGB)
    size = 17
    while ttf(size, "Bold").getlength(title) > x1 - x0 - 10 and size > 10:
        size -= 1
    d.text(((x0 + x1) / 2, y0 + 16), title, font=ttf(size, "Bold"), fill=INK, anchor="mm")


def caption(d, cx, y, text, size=15):
    d.text((cx, y), text, font=ttf(size, "Bold"), fill=INK, anchor="mm")


# ---- PANEL ----------------------------------------------------------------------------------------------------------------
PITCH, X0 = 73, 20
COLS = ["lfo_rate", "vco_mod", "pulse_width", "pulse_level", "saw_level", "sub_level", "noise_level",
        "vcf_freq", "vcf_res", "vcf_env", "vcf_mod", "vcf_kybd", None, "attack", "decay", "sustain", "release"]
CAPS = {"lfo_rate": "RATE", "vco_mod": "MOD", "pulse_width": "PW", "pulse_level": "PULSE", "saw_level": "SAW", "sub_level": "SUB",
        "noise_level": "NOISE", "vcf_freq": "FREQ", "vcf_res": "RES", "vcf_env": "ENV", "vcf_mod": "MOD", "vcf_kybd": "KYBD",
        "attack": "A", "decay": "D", "sustain": "S", "release": "R"}
SECTIONS = [("MODULATOR", 0, 0), ("VCO", 1, 2), ("SOURCE MIXER", 3, 6), ("VCF", 7, 11), ("VCA", 12, 12), ("ENV", 13, 16)]
TOP = 96                     # faders' top


def cx_of(i):
    return X0 + PITCH * i + PITCH // 2


def panel_page():
    p = Page("PANEL", 0)
    im, d = page_base()
    for title, a, b in SECTIONS:
        section(d, X0 + PITCH * a + 3, X0 + PITCH * (b + 1) - 3, 8, H - 8, title)
    strip = fader_strip("fader.png")
    for i, key in enumerate(COLS):
        if key is None:
            continue
        cx = cx_of(i)
        fader_scale(d, cx, TOP, FH, numbers=any(i == a for _, a, _ in SECTIONS))
        caption(d, cx, TOP - 22, CAPS[key])
        d.rounded_rectangle([cx - 34, TOP + FH + 6, cx + 33, TOP + FH + 31], 5, fill=WELL)
        p.fader(key, cx, TOP, strip)
    # switches: under their sections
    sy = TOP + FH + 52
    bw, bh = 62, 38
    caption(d, cx_of(0), sy, "WAVE", 14)
    p.radio("lfo_wave", cx_of(0) - bw // 2, sy + 16, bw, bh)
    caption(d, cx_of(1), sy, "RANGE", 14)
    p.radio("range", cx_of(1) - bw // 2, sy + 16, bw, bh)
    caption(d, cx_of(2), sy, "PWM", 14)
    p.radio("pwm_source", cx_of(2) - bw // 2, sy + 16, bw, bh)
    mx = (cx_of(4) + cx_of(5)) // 2
    caption(d, mx, sy, "SUB OSC", 14)
    p.radio("sub_mode", mx - 70, sy + 16, 140, bh)
    caption(d, cx_of(12), TOP - 22, "MODE")
    p.radio("vca_mode", cx_of(12) - bw // 2, TOP, bw, 46, gap=10)
    ex = (cx_of(14) + cx_of(15)) // 2
    caption(d, ex, sy, "TRIGGER", 14)
    p.radio("env_trigger", ex - 70, sy + 16, 140, bh)
    # the wordmark in the VCF's switch space
    vx = (cx_of(7) + cx_of(11)) // 2
    d.text((vx, sy + 52), "MONO-101", font=ttf(46, "Bold"), fill=INK, anchor="mm")
    d.text((vx, sy + 96), "MONOPHONIC SYNTHESIZER", font=ttf(15, "Bold"), fill=INK_DIM, anchor="mm")
    d.text((vx, sy + 120), "CIRCUIT  MODEL  BY  LEMUS", font=ttf(13), fill=INK_DIM, anchor="mm")
    faders = [k for k in COLS if k]
    p.qrows = [faders[i:i + 4] for i in range(0, 16, 4)]
    return p, save(im, "panel.png")


# ---- CONTROL ----------------------------------------------------------------------------------------------------------------
def control_page():
    p = Page("CONTROL", 1)
    im, d = page_base()
    kstrip = knob_strip("knob.png")
    section(d, 24, 676, 8, H - 8, "CONTROLLER")
    section(d, 700, 1052, 8, H - 8, "BENDER")
    section(d, 1076, 1256, 8, H - 8, "QUALITY")
    ky = 190
    for key, cap, cx in [("volume", "VOLUME", 130), ("tune", "TUNE", 350), ("portamento", "PORTAMENTO", 570)]:
        import math
        for i in range(11):   # the knob's scale
            a = math.radians(-135 + 27 * i)
            r0, r1 = KNOB / 2 + 6, KNOB / 2 + (16 if i % 5 == 0 else 11)
            d.line([(cx + math.sin(a) * r0, ky - math.cos(a) * r0), (cx + math.sin(a) * r1, ky - math.cos(a) * r1)], fill=INK_DIM, width=2)
        caption(d, cx, ky + KNOB // 2 + 18, cap)
        d.rounded_rectangle([cx - 50, ky + KNOB // 2 + 34, cx + 49, ky + KNOB // 2 + 61], 5, fill=WELL)
        p.knob(key, cx, ky, kstrip)
    d.text((350 - 64, ky + 70), "-5", font=ttf(13), fill=INK_DIM, anchor="mm")
    d.text((350 + 64, ky + 70), "+5", font=ttf(13), fill=INK_DIM, anchor="mm")
    caption(d, 570, 410, "PORTAMENTO MODE", 14)
    p.radio("porta_mode", 570 - 3 * 66 // 2 - 6, 428, 62, 40, gap=6, horizontal=True)
    d.text((350, 560), "MONO-101", font=ttf(40, "Bold"), fill=INK, anchor="mm")
    short = fader_strip("fader_short.png", short=True)
    for key, cap, cx in [("bend_vco", "VCO", 790), ("bend_vcf", "VCF", 876), ("bend_lfo", "LFO MOD", 962)]:
        top = 120
        caption(d, cx, top - 22, cap)
        fader_scale(d, cx, top, 170, numbers=key == "bend_vco")
        d.rounded_rectangle([cx - 34, top + 170 + 6, cx + 33, top + 170 + 31], 5, fill=WELL)
        p.fader(key, cx, top, short)
    d.text((876, 366), "PITCH BEND: VCO, VCF", font=ttf(13), fill=INK_DIM, anchor="mm")
    d.text((876, 386), "MOD WHEEL (CC1): LFO MOD", font=ttf(13), fill=INK_DIM, anchor="mm")
    caption(d, 876, 430, "TRANSPOSE", 14)
    p.radio("transpose", 876 - (3 * 56 + 12) // 2, 448, 56, 40, gap=6, horizontal=True)
    p.radio("quality", 1166 - 60, 120, 120, 50, gap=12)
    for i, t in enumerate(["HQ: 4x, as Lemus", "AUTO: ECO on Gen1,", "HQ on Gen2", "ECO: VCF at 2x"]):
        d.text((1166, 330 + i * 22), t, font=ttf(13), fill=INK_DIM, anchor="mm")
    p.qrows = [["volume", "tune", "portamento", "porta_mode"], ["bend_vco", "bend_vcf", "bend_lfo", "transpose"]]
    return p, save(im, "control.png")


# ---- preview (defaults, offline) ------------------------------------------------------------------------------------------
def render_preview(p, art, defaults):
    img = Image.open(os.path.join(OUT, art)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for k in p.kids:
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
        elif typ == "Label":
            st = data["textStyle"]
            d.text((x + w / 2, y + h / 2), spec.get("display", ""), font=ttf(st["font"]["height"] * DEVICE_TEXT), fill=INK, anchor="mm")
    for r in p.rects:
        d.rectangle(r, outline=(232, 60, 60), width=2)
    return img


def main():
    preview = "--preview" in sys.argv
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    pages = [panel_page(), control_page()]
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
        dump_path = os.path.join(ROOT, "build", "params.json")
        defaults = json.load(open(dump_path))["params"]
        os.makedirs(PREVIEW, exist_ok=True)
        for p, art in pages:
            render_preview(p, art, defaults).convert("RGB").save(os.path.join(PREVIEW, p.name.lower() + ".png"))
    print("wrote %s - %d tabs, %d files, %d KB" % (OUT, len(tabs), len(names), sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) // 1024))


if __name__ == "__main__":
    main()
