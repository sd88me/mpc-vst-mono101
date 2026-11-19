# 1x1: plan and status

1x1 (working name) is the Lemus SH-101 synth board as an MPC plugin: the voice only. No CPU board, firmware,
sequencer or arpeggio, and no ROM: MIDI drives the board through Lemus's own voice mode (`src/lemus/voice_keys.h`).
Same route as Acid-303 (Lemus TB-303): vendor unmodified, golden renders from the original, then speed work
commit by commit, each checked against the goldens. Build: the Akai SDK route (docs/SDK-PORTING.md in mpc-vst-plugins).

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

## Next
1. Force numbers (armhf `vtest-arm32`; FORCE unreachable today). Expect well over 100% of a core, as the 303 was.
2. Speed work, one commit per step, `vtest check golden` after each (target: the 303's HQ/ECO budget,
   at most ~0.05 dB mean spectral change):
   - IR3109 Newton: stop at an inaudible residual, better starting guess, analytic slopes, the `buffer()` tanh
     pairs as NEON vectors, fast inline exp/tanh (from Acid-303's `src/lemus/`).
   - Automation p99 spikes: find what a control change recomputes per block.
   - Adaptive control rate for ENV / portamento / bender / jack board once settled.
   - ECO: VCF/VCA at 2x with the VCO kept at 4x (the 303's split), resonance prewarp.
   - Cheaper gauss noise, skip silent mixer sources.
   - aarch64: flush denormals in render (the 303 needed it).
3. SDK plugin (`src/OneX1Plugin.cpp`, plugin.json, params.lock, skin) once the voice fits; Gen2 first if Gen1
   can't make it.
4. Name: "1x1" is a placeholder.

Not in 1x1: the firmware's RANDOM modulator step (voice mode holds RANDOM still); we could step it ourselves
on each MODULATOR clock later.
