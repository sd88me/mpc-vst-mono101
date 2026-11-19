#pragma once
// 1x1's engine: the Lemus SH-101 synth board in voice mode, without JUCE. It does what Lemus's
// SH101Processor::processBlock does with no ROM (machines/sh101/plugin/PluginProcessor.cpp):
// MIDI -> VoiceKeys -> the board's lines, the MODULATOR at the host rate, sample-accurate line
// changes, and the voice sleeping once it is silent and settled. The plugin and the test harness
// both drive this class, so the harness hears what the plugin plays.
#include "lemus/lfo.h"
#include "lemus/voice.h"
#include "lemus/voice_keys.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace onex1 {

struct Event {
	int frame;          // sample position within the block
	unsigned char b[3]; // a MIDI channel message
};

class Engine {
public:
	sh101::Range range = sh101::Range::Ft8;
	sh101::Transpose transpose = sh101::Transpose::Mid;
	bool idleSleep = true;
	bool eco = false; // filter section at 2x (sh101::Voice::setEco), applied at prepare()

	void prepare(double rate, int maxBlock)
	{
		m_rate = rate;
		m_voice.setCalibration(sh101::Calibration::realUnit());
		m_voice.setControls(m_controls);
		m_voice.setEco(eco);
		m_voice.prepare(rate);
		m_voice.settlePower(); // a unit switched on long ago: no power-on mute
		m_lfo.prepare(rate);
		m_keys.prepare(rate);
		m_keys.reset();
		m_mod.assign(size_t(std::max(maxBlock, 1)), {});
		m_lines = {};
		m_lastSquare = false;
		m_asleep = false;
		m_quietSamples = 0;
		m_perf = {};
		m_bend = 0;
		m_modPush = 0;
	}
	double latencySamples() const { return m_voice.latencySamples(); }

	void setControls(const sh101::Controls &c)
	{
		if (!same(c, m_controls))
			m_asleep = false;
		m_controls = c;
	}
	const sh101::Controls &controls() const { return m_controls; }

	void allNotesOff() { m_keys.allNotesOff(); }

	// Renders n mono samples; events sorted by frame, all < n.
	void render(float *out, int n, const Event *ev, int nev)
	{
		if (int(m_mod.size()) < n)
			m_mod.resize(size_t(n));
		m_voice.setControls(m_controls);
		m_lfo.setRate(m_controls.lfoRate);
		m_lfo.setWave(m_controls.lfoWave);
		m_lfo.setRateScale(m_controls.mods.lfoRateScale);
		applyPerformance();
		int e = 0, done = 0;
		for (int i = 0; i < n; ++i) {
			bool perfChanged = false;
			for (; e < nev && ev[e].frame <= i; ++e)
				perfChanged |= midi(ev[e].b);
			if (perfChanged) {
				if (i > done) {
					renderVoice(out + done, i - done, m_mod.data() + done);
					done = i;
				}
				applyPerformance();
			}
			const auto lfo = m_lfo.tick();
			m_mod[size_t(i)] = {lfo.tri, lfo.square};
			// RANDOM: the firmware puts a new random code on S/H channel 2 at each MODULATOR clock
			// (Lemus's voice mode holds it still: there is no firmware). Only while RANDOM is picked,
			// so the other waves render as Lemus's voice mode does.
			bool randomStep = false;
			if (lfo.square && !m_lastSquare && m_controls.lfoWave == sh101::LfoWave::Random) {
				m_rng = m_rng * 1664525u + 1013904223u;
				m_random = int(m_rng >> 26); // 6 bits
				randomStep = true;
			}
			m_lastSquare = lfo.square;
			if (m_keys.tick(range, m_controls.trigger, transpose) || randomStep) {
				if (i > done) {
					renderVoice(out + done, i - done, m_mod.data() + done);
					done = i;
				}
				const auto &l = m_keys.lines();
				if (l.gate != m_lines.gate || l.kcv != m_lines.kcv || l.range != m_lines.range || l.portaOff != m_lines.portaOff)
					m_asleep = false;
				m_lines = l;
				m_lines.random = m_random;
				m_voice.setLines(m_lines);
				m_lfo.setClkRst(l.clkRst);
			}
		}
		if (n > done)
			renderVoice(out + done, n - done, m_mod.data() + done);
	}

	bool asleep() const { return m_asleep; }
	sh101::Voice::Probe probe() const { return m_voice.probe(); }

private:
	sh101::Voice m_voice;
	sh101::VoiceKeys m_keys;
	sh101::Lfo m_lfo;
	sh101::Controls m_controls;
	sh101::CpuLines m_lines;
	sh101::Performance m_perf;
	std::vector<sh101::ModFrame> m_mod;
	double m_rate = 44100;
	double m_bend = 0, m_modPush = 0;
	bool m_asleep = false;
	bool m_lastSquare = false;
	unsigned m_rng = 0x2545f491u;
	int m_random = 0;
	int m_quietSamples = 0;
	sh101::Voice::Probe m_quietFrom;

	// Returns true if the bender or MOD changed (the voice is split there, as Lemus does).
	bool midi(const unsigned char *b)
	{
		const int st = b[0] & 0xf0;
		if (st == 0x90 && b[2] > 0) {
			m_keys.noteOn(b[1], m_controls.trigger);
			if (m_controls.mods.lfoTrig) // the LFO TRIG mod, from the keyboard: a CLK RST on each key
				m_lfo.reset();
		} else if (st == 0x80 || st == 0x90) {
			m_keys.noteOff(b[1]);
		} else if (st == 0xb0) {
			if (b[1] == 64)
				m_keys.setPedal(b[2] >= 64);
			else if (b[1] == 1) {
				m_modPush = b[2] / 127.0;
				return true;
			} else if (b[1] == 120 || b[1] == 123)
				m_keys.allNotesOff();
		} else if (st == 0xe0) {
			const int v = (b[2] << 7 | b[1]) - 8192;
			m_bend = std::max(-1.0, v / 8191.0);
			return true;
		}
		return false;
	}
	void applyPerformance()
	{
		sh101::Performance p;
		p.bend = m_bend;
		p.modPush = m_modPush;
		if (p.bend != m_perf.bend || p.modPush != m_perf.modPush)
			m_asleep = false;
		m_perf = p;
		m_voice.setPerformance(p);
	}

	// Lemus's sleep rule: gate closed, output under -120 dB for 100 ms, and ENV, VCA and the
	// portamento settled over that time.
	void renderVoice(float *out, int n, const sh101::ModFrame *mod)
	{
		if (m_asleep) {
			std::fill(out, out + n, 0.0f);
			return;
		}
		m_voice.render(out, n, mod);
		float peak = 0;
		for (int i = 0; i < n; ++i)
			peak = std::max(peak, std::abs(out[i]));
		if (m_lines.gate || m_voice.powering() || m_voice.poweringDown() || peak > 1e-6f) {
			m_quietSamples = 0;
			return;
		}
		const auto p = m_voice.probe();
		if (m_quietSamples == 0)
			m_quietFrom = p;
		m_quietSamples += n;
		if (m_quietSamples < int(0.1 * m_rate))
			return;
		if (std::abs(p.env - m_quietFrom.env) > 1e-6 || std::abs(p.vca - m_quietFrom.vca) > 1e-8 ||
		    std::abs(p.cvVolts - m_quietFrom.cvVolts) > 1e-5) {
			m_quietFrom = p;
			m_quietSamples = n;
			return;
		}
		m_asleep = idleSleep;
	}

	static bool same(const sh101::Controls &a, const sh101::Controls &b)
	{
		return a.lfoRate == b.lfoRate && a.lfoWave == b.lfoWave && a.vcoMod == b.vcoMod && a.pulseWidth == b.pulseWidth &&
		       a.pwmSource == b.pwmSource && a.pulseLevel == b.pulseLevel && a.sawLevel == b.sawLevel &&
		       a.subLevel == b.subLevel && a.noiseLevel == b.noiseLevel && a.subMode == b.subMode && a.vcfFreq == b.vcfFreq &&
		       a.vcfRes == b.vcfRes && a.vcfEnv == b.vcfEnv && a.vcfMod == b.vcfMod && a.vcfKybd == b.vcfKybd &&
		       a.vcaMode == b.vcaMode && a.attack == b.attack && a.decay == b.decay && a.sustain == b.sustain &&
		       a.release == b.release && a.trigger == b.trigger && a.volume == b.volume && a.tune == b.tune &&
		       a.portamento == b.portamento && a.portaMode == b.portaMode && a.bendVco == b.bendVco &&
		       a.bendVcf == b.bendVcf && a.lfoModDepth == b.lfoModDepth && a.mods == b.mods;
	}
};

} // namespace onex1
