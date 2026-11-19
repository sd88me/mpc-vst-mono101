# Vendored: Lemus SH-101 synth board

From [Lemus](https://github.com/lemus-dev/lemus), commit 7575df4 (2026-11-18, "ro-mono-101 0.1.3"),
`machines/sh101/core/`, AGPL-3.0 (`LICENSE` at the repo root).

Taken: the synth board only (oscillator section, MODULATOR, VCF, ENV, VCA, jack board, oversampler) and
`voice_keys.h` (Lemus's ROM-free voice mode: MIDI straight to the board's lines).

Left out: the CPU board (`mcs48.*`, `machine.*`) and its MIDI keyboard driver (`midi.h`): the firmware,
sequencer and arpeggio. 1x1 is the voice only and needs no ROM.

The first commit has these files unmodified; every later change is its own commit.
