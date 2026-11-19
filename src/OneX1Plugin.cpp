// 1x1: the Lemus SH-101 synth board as an MPC instrument (Akai MPC Plugin SDK). The voice only:
// MIDI drives the board through Lemus's voice mode (src/onex1/engine.h); no CPU board, firmware,
// sequencer or arpeggio, and no ROM.
//
// Parameter order is frozen in params.lock (index = VST parameter = skin binding): append only.
#include "mpc_plugin.h"

#include "onex1/engine.h"

#include <atomic>
#include <algorithm>
#include <cstring>
#include <memory>

#if defined(__aarch64__)
#include <cstdint>
#endif

#ifndef ONEX1_NAME
#define ONEX1_NAME "1x1"
#endif
#ifndef ONEX1_UID
#define ONEX1_UID 'S', '1', 'x', '1'
#endif

namespace {

enum ParamIndex {
	kLfoRate = 0, // parameter 0: the host nudges it on every prepare, harmless here
	kLfoWave,
	kVcoMod,
	kRange,
	kPulseWidth,
	kPwmSource,
	kPulseLevel,
	kSawLevel,
	kSubLevel,
	kNoiseLevel,
	kSubMode,
	kVcfFreq,
	kVcfRes,
	kVcfEnv,
	kVcfMod,
	kVcfKybd,
	kVcaMode,
	kAttack,
	kDecay,
	kSustain,
	kRelease,
	kEnvTrigger,
	kVolume,
	kTune,
	kPortamento,
	kPortaMode,
	kBendVco,
	kBendVcf,
	kBendLfo,
	kTranspose,
	kQuality,
	kNumParams
};

// QUALITY: HQ (the original's 4x throughout), AUTO (ECO on Gen1, HQ on Gen2), ECO (the filter
// section at 2x, the oscillator at 4x).
enum Quality { kHq = 0, kAuto, kEco };

constexpr bool kGen1 =
#if defined(__arm__) && !defined(__aarch64__)
	true;
#else
	false;
#endif

constexpr int kMaxEvents = 512;

// Flush denormals to zero while rendering on aarch64 (Gen1's NEON does it by itself; without it
// the 303's sweeps spiked past 3000 % on a Live III).
struct DenormalGuard {
#if defined(__aarch64__)
	uint64_t saved;
	DenormalGuard()
	{
		asm volatile("mrs %0, fpcr" : "=r"(saved));
		asm volatile("msr fpcr, %0" ::"r"(saved | (1ull << 24)));
	}
	~DenormalGuard() { asm volatile("msr fpcr, %0" ::"r"(saved)); }
#endif
};

} // namespace

class OneX1Plugin : public mpc::Plugin {
public:
	OneX1Plugin() : mpc::Plugin(makeInfo())
	{
		// Sliders and knobs as the panel prints them, 0-10 (the engine takes travel 0-1).
		auto slider = [this](const char *id, const char *name, float def) {
			addParam(mpc::floatParam(id, name, 0.0f, 10.0f, def * 10.0f, "", 1));
		};
		slider("lfo_rate", "LFO Rate", 0.5f);
		addParam(mpc::choiceParam("lfo_wave", "LFO Wave", {"Triangle", "Square", "Random", "Noise"}, 0));
		slider("vco_mod", "VCO Mod", 0.0f);
		addParam(mpc::choiceParam("range", "Range", {"16'", "8'", "4'", "2'"}, 1));
		slider("pulse_width", "Pulse Width", 0.0f);
		addParam(mpc::choiceParam("pwm_source", "PWM Source", {"LFO", "Manual", "Env"}, 1));
		slider("pulse_level", "Pulse", 0.0f);
		slider("saw_level", "Saw", 1.0f);
		slider("sub_level", "Sub Osc", 0.4f);
		slider("noise_level", "Noise", 0.0f);
		addParam(mpc::choiceParam("sub_mode", "Sub Mode", {"1 Oct", "2 Oct", "2 Oct Pulse"}, 1));
		slider("vcf_freq", "VCF Freq", 0.35f);
		slider("vcf_res", "VCF Res", 0.3f);
		slider("vcf_env", "VCF Env", 0.5f);
		slider("vcf_mod", "VCF Mod", 0.0f);
		slider("vcf_kybd", "VCF Kybd", 0.5f);
		addParam(mpc::choiceParam("vca_mode", "VCA Mode", {"Env", "Gate"}, 0));
		slider("attack", "Attack", 0.0f);
		slider("decay", "Decay", 0.4f);
		slider("sustain", "Sustain", 0.3f);
		slider("release", "Release", 0.2f);
		addParam(mpc::choiceParam("env_trigger", "Env Trigger", {"Gate+Trig", "Gate", "LFO"}, 0));
		slider("volume", "Volume", 0.7f);
		addParam(mpc::floatParam("tune", "Tune", -5.0f, 5.0f, 0.0f, "", 1));
		slider("portamento", "Portamento", 0.0f);
		addParam(mpc::choiceParam("porta_mode", "Porta Mode", {"On", "Auto", "Off"}, 2));
		slider("bend_vco", "Bend VCO", 0.2f);
		slider("bend_vcf", "Bend VCF", 0.0f);
		slider("bend_lfo", "Bend LFO", 0.5f);
		addParam(mpc::choiceParam("transpose", "Transpose", {"L", "M", "H"}, 1));
		addParam(mpc::choiceParam("quality", "Quality", {"HQ", "Auto", "ECO"}, 1));
	}

	void prepare(double sampleRate, int maxBlockSize) override
	{
		// Both qualities prepared here (they allocate), so QUALITY switches without allocating on
		// the audio thread; only the one in use renders.
		rate_ = sampleRate;
		maxBlock_ = maxBlockSize > 0 ? maxBlockSize : 512;
		for (int q = 0; q < 2; ++q) {
			engines_[q].eco = q == 1;
			engines_[q].setControls(controls());
			engines_[q].prepare(sampleRate, maxBlock_);
		}
		mono_.assign(size_t(maxBlock_), 0.0f);
		current_ = wantEco() ? 1 : 0;
	}

	void reset() override
	{
		for (auto &e : engines_)
			e.allNotesOff();
	}

	void process(mpc::ProcessContext &ctx) override
	{
		DenormalGuard guard;
		const int n = ctx.numFrames;
		if (n > int(mono_.size()))
			return; // the host promised maxBlockSize; never allocate here
		const int want = wantEco() ? 1 : 0;
		if (want != current_) {
			engines_[current_].allNotesOff();
			current_ = want;
		}
		onex1::Engine &e = engines_[current_];
		e.setControls(controls());
		e.range = sh101::Range(getInt(kRange));
		e.transpose = sh101::Transpose(getInt(kTranspose));

		int nev = 0;
		for (int i = 0; i < ctx.numMidiEvents && nev < kMaxEvents; ++i) {
			const mpc::MidiEvent &m = ctx.midi[i];
			if (m.size < 2 || m.status() < 0x80 || m.status() == 0xF0)
				continue;
			onex1::Event &ev = events_[nev++];
			ev.frame = std::min(std::max(m.sampleOffset, 0), n - 1);
			ev.b[0] = m.data[0];
			ev.b[1] = m.data[1];
			ev.b[2] = m.size > 2 ? m.data[2] : 0;
		}
		e.render(mono_.data(), n, events_, nev);
		for (int c = 0; c < ctx.numOutputs; ++c)
			std::memcpy(ctx.outputs[c], mono_.data(), sizeof(float) * size_t(n));
	}

private:
	static mpc::PluginInfo makeInfo()
	{
		mpc::PluginInfo info;
		info.name = ONEX1_NAME;
		info.vendor = "sd88me";
		static constexpr char uid[4] = {ONEX1_UID};
		info.uniqueId = MPC_FOURCC(uid[0], uid[1], uid[2], uid[3]);
		info.version = 100; // 0.1.0.0
		info.isInstrument = true;
		info.numInputs = 0;
		info.numOutputs = 2;
		info.tailSamples = 0;
		return info;
	}

	bool wantEco()
	{
		const int q = getInt(kQuality);
		return q == kEco || (q == kAuto && kGen1);
	}

	sh101::Controls controls()
	{
		auto s = [this](int i) { return double(get(i)) / 10.0; };
		sh101::Controls c;
		c.lfoRate = s(kLfoRate);
		c.lfoWave = sh101::LfoWave(getInt(kLfoWave));
		c.vcoMod = s(kVcoMod);
		c.pulseWidth = s(kPulseWidth);
		c.pwmSource = sh101::PwmSource(getInt(kPwmSource));
		c.pulseLevel = s(kPulseLevel);
		c.sawLevel = s(kSawLevel);
		c.subLevel = s(kSubLevel);
		c.noiseLevel = s(kNoiseLevel);
		c.subMode = sh101::SubMode(getInt(kSubMode));
		c.vcfFreq = s(kVcfFreq);
		c.vcfRes = s(kVcfRes);
		c.vcfEnv = s(kVcfEnv);
		c.vcfMod = s(kVcfMod);
		c.vcfKybd = s(kVcfKybd);
		c.vcaMode = sh101::VcaMode(getInt(kVcaMode));
		c.attack = s(kAttack);
		c.decay = s(kDecay);
		c.sustain = s(kSustain);
		c.release = s(kRelease);
		c.trigger = sh101::Trigger(getInt(kEnvTrigger));
		c.volume = s(kVolume);
		c.tune = 0.5 + double(get(kTune)) / 10.0;
		c.portamento = s(kPortamento);
		c.portaMode = sh101::PortaMode(getInt(kPortaMode));
		c.bendVco = s(kBendVco);
		c.bendVcf = s(kBendVcf);
		c.lfoModDepth = s(kBendLfo);
		return c;
	}

	onex1::Engine engines_[2]; // HQ, ECO
	int current_ = 0;
	double rate_ = 44100;
	int maxBlock_ = 512;
	std::vector<float> mono_;
	onex1::Event events_[kMaxEvents];
};

MPC_PLUGIN_ENTRY(OneX1Plugin)
