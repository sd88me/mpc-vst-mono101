# Mono-101: development notes

Mono-101 is the Lemus SH-101 synth board as an MPC plugin: the voice only. No CPU board, firmware, sequencer or
arpeggio, and no ROM: MIDI drives the board through Lemus's own voice mode (`src/lemus/voice_keys.h`). The route:
vendor the code unmodified, render golden references from it, then change it commit by commit, each checked against
the goldens. (The code's internal names, `1x1` / `onex1`, are the working name.)

## Layout
- `src/lemus/`: Lemus `machines/sh101/core` at 7575df4 minus `mcs48.*`, `machine.*`, `midi.h` (VENDORED.md).
- `src/onex1/engine.h`: JUCE-free engine = Lemus SH101Processor's voice-mode path (VoiceKeys, MODULATOR at host
  rate, sample-accurate line changes, idle sleep). The plugin and the harness both use it.
- `tools/voicetest/`: `vtest golden|check|time`, sh101bench's workloads (midi, bright, pwm-lfo-porta,
  longrun-resmax, automation, idle) at 44.1 kHz, 128-sample blocks. `golden/` = renders of the unmodified code (x86).

## Baseline (unmodified Lemus, 2026-11-19)
One voice, 44.1 kHz, 128-sample blocks, harness outside MPC, thread CPU time against real time.

| | x86 (WSL desktop) | Live III A76 (core 5) | Live III A55 (core 2) | Force / Gen1 |
|---|---|---|---|---|
| playing workloads, mean | 15.1% | 21.8% | 83.9% | not measured (Force unreachable) |
| bright, mean / p99 | 17.6 / 24.9% | 24.8 / 29.7% | 95.1 / 112% | |
| longrun-resmax, mean / p99 | 19.7 / 33.9% | 28.4 / 43.3% | 107 / 161% | |
| automation, mean / p99 | 16.5 / 50.2% | 24.6 / 66.9% | 94.1 / 249% | |
| idle (one note, then sleep) | 2.7% | 3.5% | 14.5% | |

The arm64 build matches the x86 goldens (max diff -99 dBFS on the 16 s self-oscillation run, others identical
or below -147 dBFS).

Profile (x86 gprof, all workloads): `Ir3109Vcf::solve` 45%, `Ir3109Vcf::buffer` 12%, `otaOut` 1.4%: the VCF's
Newton solve is ~60%. Then JackBoard::solve 4%, Bender 3.5%, BA662 controlCurrent 3.3%, OscSection/FilterSection
tick 3% each, EnvGen 2.7%, Portamento 2.5%, half-band decimators ~2.5%, Noise::gauss 1.6%. Everything runs at
4x (176.4 kHz).

## Speed work log
Live III A55 (core 2), playing-workload mean, one timing pass; arm64 / armhf (the Gen1 build runs on the Live III's AArch32).

| Step | arm64 | armhf | Sound against the goldens |
|---|---|---|---|
| Unmodified Lemus | 83.9% | 97.9% | (golden) |
| Inline exp/expm1/tanh/log1p | 81.0% | 89.1% | worst -121 dBFS, LSD 0.000 dB |
| Inline log, tan(w)/w, asinh, cbrt | 82.8% | 87.3% | the same |
| ECO (filter section + jack board at 2x, VCO at 4x), optional | 58.0% | 60.8% | LSD mean 0.02-0.05 dB on plain playing; 0.31-0.35 dB self-oscillating |

Findings:
- Lemus already did a CPU round on this voice (sh101 docs/improvements.md, 2026-11-14): its VCF Newton mostly takes
  one iteration a sample. The remaining cost is the arithmetic per iteration and the 4x rate.
- The p99 spikes (automation) are self-oscillation: blocks with the VCF pole at 15-30 kHz take about twice the
  iterations of those under 5 kHz; no retries. ECO makes them worse (A55 automation p99 248% -> 268%).
- ECO's pitch: plain notes within 0.02 cents; a self-oscillating filter on its own within 2.5 cents
  (`vtest selfosc`), but self-oscillation driven by the pulse (longrun-resmax) 3.6-5 cents sharp at 4.5-8 kHz,
  +0.04-0.11 dB. Probably the pulse's content above 44 kHz, which HQ keeps and ECO decimates away, intermodulating
  in the OTAs: real behaviour, no simple prewarp fix. Note starts differ by up to 1 dB in the first frame (the
  mixer half-band's 65 us against the ENV).

## Plugin

`src/OneX1Plugin.cpp` (SDK `mpc::Plugin`); parameter order frozen in `params.lock` (append only). `./build-sdk.sh test`
runs the parameter-lock check and the SDK's host simulator.

- **Skin** (`tools/make_tui.py`): three tabs (VCO, VCF, BENT) under a header with the preset buttons, drawn from Lemus's
  measured panel (`tools/panel/panel.json`) and lit as the other ports' realistic skins. Sliders are film strips dragged
  vertically; switches are film strips of their positions with a tap target on each position's legend; rotaries also
  drag. The naming keyboard is shown over the tab while `kb_open` is 1.
- **Presets:** Init, the manual's 40 and Mono-101's 15 (`tools/presets/*.json` -> `tools/gen_presets.py` ->
  `src/onex1/presets_factory.h`), then 32 user presets in `mono101-presets.txt` (plain text, by parameter id).
- **Circuit Bent:** OVERDRIVE, PWM SOURCE, VCF FM, LFO RANGE / KEY TRIG (after the circuitbenders package), TRI VCO
  (the CEM3340's triangle as a fifth mixer source) and LFO SYNC (rate from the host tempo, a CLK RST on each division
  of the song position). Each is off at zero; CIRCUIT's PURE bypasses them all. `Lfo::hz()` reads 0.82 % slow against
  the simulated circuit at every rate, so SYNC corrects for it.
- **Extras over Lemus's voice mode:** RANDOM steps on each MODULATOR clock (the firmware's job), QUALITY.
