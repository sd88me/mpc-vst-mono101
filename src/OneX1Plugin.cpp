// Mono-101 (working name 1x1): the Lemus SH-101 synth board as an MPC instrument (Akai MPC Plugin SDK). The voice only:
// MIDI drives the board through Lemus's voice mode (src/onex1/engine.h); no CPU board, firmware,
// sequencer or arpeggio, and no ROM.
//
// Parameter order is frozen in params.lock (index = VST parameter = skin binding): append only.
//
// Presets (as OTTmpc / Profit-5): the MPC's PRESET menu lists "Init", the factory presets (src/onex1/presets_factory.h: the
// SH-101 Owner's Manual's 40 sample sounds, then Mono-101's own), then 32 user presets "U01 ..". SAVE PRESET opens the drawn
// naming keyboard (kb_open = 1) on the picked preset's name and takes the sound as it is then; SAVE stores it in the first free slot,
// DELETE PRESET empties the picked user preset. Kept in <plugin folder>/mono101-presets.txt, shared by every project. A preset holds
// every synth parameter but QUALITY. The host re-picks the saved program after a project load: ignored for 2 s after a state load,
// and a re-pick of the current program is always ignored, so edits are kept. A drawn key's repeat within 250 ms is ignored (one tap
// can arrive as two presses).
#include "mpc_plugin.h"

#include "onex1/engine.h"
#include "onex1/presets_factory.h"

#include <atomic>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#if defined(__aarch64__)
#include <cstdint>
#endif

#ifndef ONEX1_NAME
#define ONEX1_NAME "Mono-101"
#endif
#ifndef ONEX1_UID
#define ONEX1_UID 'M', '1', '0', '1'
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
	// The circuitbenders mods (MODS tab), each with its own switch; off = the stock board.
	kDriveOn,
	kDrive,
	kPwmModOn,
	kPwmModSource,
	kFmOn,
	kFmSource,
	kFmAmount,
	kLfoRange,
	kLfoTrig,
	kModsMaster, // PURE: every mod bypassed, whatever its own switch says
	kFavAdd,     // the presets' controls (local: never reach the engine) from here to kLocalEnd
	kFavDel,
	kFavName,    // the name being typed: a counter the plugin bumps; its text is the name
	kKbOpen,     // the drawn keyboard is showing (set by the plugin only)
	kKbFirst,    // the keys: kKbChars, then space, delete, shift, cancel, save
};

constexpr char kKbChars[] = "1234567890QWERTYUIOPASDFGHJKLZXCVBNM-";
constexpr int kKbCount = int(sizeof kKbChars - 1) + 5;
constexpr int kLocalEnd = kKbFirst + kKbCount;
// appended after the keyboard (params.lock is append only): more of the sound's parameters
enum ParamIndex2 {
	kTriOn = kLocalEnd, // CIRCUIT BENT: TRI VCO
	kTriLevel,
	kLfoSync,           // CIRCUIT BENT: LFO SYNC to the host tempo
	kLfoDiv,
	kNumParamsE
};
constexpr int kNumParams = kNumParamsE;
constexpr bool isSynth(int i) { return i < kFavAdd || (i >= kLocalEnd && i < kNumParams); }
// LFO SYNC's divisions, in beats per LFO cycle
constexpr double kLfoDivBeats[] = {0.25, 1.0 / 3, 0.5, 2.0 / 3, 1, 2, 4, 8, 16};
constexpr int kFavSlots = 32, kFavNameMax = 20; // the MPC shows 24 characters of a program name; "U01 " takes 4
constexpr int kNumFactory = 1 + onex1::kNumFactoryPresets; // Init, the manual's 40, Mono-101's own

long long nowMs()
{
	return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

thread_local int t_pushing = -1; // the parameter the worker is telling the host about right now (its echo is ignored)

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
constexpr double kLfoScale[3] = {0.25, 1.0, 15.0}; // LFO RANGE mod: SLOW (50 s-9 Hz), NORMAL (12.5 s-36 Hz), FAST (to 550 Hz)

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
		addParam(mpc::choiceParam("drive_on", "Overdrive Mod", {"Off", "On"}, 0));
		slider("drive", "Overdrive", 0.0f);
		addParam(mpc::choiceParam("pwm_mod_on", "PWM Source Mod", {"Off", "On"}, 0));
		addParam(mpc::choiceParam("pwm_mod_source", "PWM Source", {"Off", "Triangle", "Square", "Random", "Noise", "Sub 1 Oct", "Sub 2 Oct"}, 0));
		addParam(mpc::choiceParam("fm_on", "VCF FM Mod", {"Off", "On"}, 0));
		addParam(mpc::choiceParam("fm_source", "VCF FM Source", {"Pulse", "Saw", "Sub 1 Oct", "Sub 2 Oct", "Sub 2 Oct Pulse", "Noise"}, 0));
		slider("fm_amount", "VCF FM Amount", 0.0f);
		addParam(mpc::choiceParam("lfo_range", "LFO Range Mod", {"Slow", "Normal", "Fast"}, 1));
		addParam(mpc::choiceParam("lfo_trig", "LFO Key Trig Mod", {"Off", "On"}, 0));
		addParam(mpc::choiceParam("mods", "Circuit Bent", {"Pure", "Bent"}, 1));
		auto local = [this](mpc::Param p) {
			p.automatable = false;
			addParam(p);
		};
		local(mpc::intParam("fav_add", "Save Preset", 0, 1, 0));
		local(mpc::intParam("fav_del", "Delete Preset", 0, 1, 0));
		local(mpc::intParam("fav_name", "Preset Name", 0, 1023, 0));
		local(mpc::intParam("kb_open", "Keyboard", 0, 1, 0));
		std::string ids[kKbCount], names[kKbCount]; // not static: a function-local static std::string segfaults at dlclose
		const char *extra[5][2] = {{"kb_space", "Key Space"}, {"kb_bksp", "Key Delete"}, {"kb_shift", "Key Shift"},
		                           {"kb_cancel", "Key Cancel"}, {"kb_save", "Key Save"}};
		for (int k = 0; k < kKbCount; ++k) {
			const int nchars = int(sizeof kKbChars - 1);
			if (k < nchars) {
				const char c = kKbChars[k];
				ids[k] = c == '-' ? std::string("kb_dash") : std::string("kb_") + char(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
				names[k] = std::string("Key ") + c;
			} else {
				ids[k] = extra[k - nchars][0];
				names[k] = extra[k - nchars][1];
			}
			local(mpc::intParam(ids[k].c_str(), names[k].c_str(), 0, 1, 0));
		}
		addParam(mpc::choiceParam("tri_on", "Tri VCO Mod", {"Off", "On"}, 0));
		slider("tri_level", "Tri VCO Level", 0.0f);
		addParam(mpc::choiceParam("lfo_sync", "LFO Sync Mod", {"Off", "On"}, 0));
		addParam(mpc::choiceParam("lfo_div", "LFO Sync Division", {"1/16", "1/8T", "1/8", "1/4T", "1/4", "1/2", "1 Bar", "2 Bars", "4 Bars"}, 4));
		addProgram("Init", {});
		for (int i = 0; i < onex1::kNumFactoryPresets; ++i)
			addProgram(onex1::kFactoryPresets[i].name, {});
		for (int i = 0; i < kFavSlots; ++i)
			addProgram("", {});
		for (int i = 0; i < kNumParams; ++i)
			defaults_.push_back(get(i));
		for (int i = 0; i < onex1::kNumFactoryPresets; ++i) {
			std::vector<float> v = defaults_;
			std::string body = onex1::kFactoryPresets[i].values;
			parseValues(&body[0], v);
			factory_.push_back(v);
		}
		favFile_ = mpc::detail::computePluginFolder() + "/mono101-presets.txt";
		loadFavs();
		worker_ = std::thread(&OneX1Plugin::workerMain, this);
	}

	~OneX1Plugin() override
	{
		quit_.store(true);
		if (worker_.joinable())
			worker_.join();
	}

	// ---- presets ------------------------------------------------------------------------------------------------------------
	void parameterChanged(int index, float plain) override
	{
		if (index < 0 || index >= kNumParams || isSynth(index) || t_pushing == index)
			return;
		localChanged(index, plain);
	}

	bool formatValue(int index, float plain, std::string &out) override
	{
		(void)plain;
		if (index == kFavName) {
			std::lock_guard<std::mutex> g(favMu_);
			out = kbName_ + "_";
			return true;
		}
		if (!isSynth(index) && index != kKbOpen) {
			out = "";
			return true;
		}
		return false;
	}

	void saveExtraState(std::vector<uint8_t> &out) override
	{
		char b[48];
		std::snprintf(b, sizeof b, "M101 prog=%d", currentProgram_);
		out.assign(b, b + std::strlen(b));
	}

	void loadExtraState(const uint8_t *data, size_t size) override
	{
		const std::string s(reinterpret_cast<const char *>(data), size);
		const size_t at = s.find("prog=");
		if (s.compare(0, 5, "M101 ") == 0 && at != std::string::npos) {
			const int prog = std::atoi(s.c_str() + at + 5);
			if (prog >= 0 && prog < kNumFactory + kFavSlots)
				currentProgram_ = prog;
		}
	}

	// effSetChunk (wrapped below): the program re-pick that follows a project load is ignored.
	VstIntPtr setChunk(AEffect *e, VstIntPtr value, void *ptr, VstIntPtr (*orig)(AEffect *, VstInt32, VstInt32, VstIntPtr, void *, float))
	{
		const VstIntPtr r = orig(e, effSetChunk, 0, value, ptr, 0.0f);
		if (r) {
			ignoreProgUntil_.store(nowMs() + 2000);
			stateAt_.store(nowMs());
			wantDisplay_.store(true);
		}
		return r;
	}

	// The MPC picked a program in its PRESET menu. prev = the program before the pick (the framework has stored the new one).
	void programPicked(int prev, int prog)
	{
		if (prog < 0 || prog >= kNumFactory + kFavSlots)
			return;
		if (nowMs() < ignoreProgUntil_.load() || prog == prev) {
			currentProgram_ = prev;
			return;
		}
		std::vector<float> vals;
		if (prog == 0)
			vals = defaults_;
		else if (prog < kNumFactory)
			vals = factory_[size_t(prog - 1)];
		else {
			std::lock_guard<std::mutex> g(favMu_);
			const Fav &f = favs_[size_t(prog - kNumFactory)];
			if (!f.used)
				return; // an empty slot: nothing changes, but it is the picked one
			vals = f.values;
		}
		applyValues(vals);
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
		[[maybe_unused]] DenormalGuard guard; // does nothing off aarch64
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
		// LFO SYNC: the rate from the host's tempo; while it plays, the LFO restarts on each division of the song position
		const mpc::Transport &t = ctx.transport;
		const bool sync = getInt(kModsMaster) && getInt(kLfoSync) && t.tempoValid && t.bpm > 0;
		e.setSync(sync ? kLfoDivBeats[std::min(std::max(getInt(kLfoDiv), 0), 8)] : 0.0, t.bpm, t.playing && t.ppqValid,
		          t.ppqPos, ctx.sampleRate > 0 ? ctx.sampleRate : rate_);

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
		// The mods: overdrive 1x..8x, the LFO's C9 switched (kLfoScale).
		if (getInt(kModsMaster) == 0)
			return c; // PURE: the stock board
		auto &m = c.mods;
		// Each mod is off at zero (DRIVE, AMOUNT, LEVEL at 0, PWM SOURCE at OFF); CIRCUIT's PURE turns them all off. The
		// *_on switches of the first layout are no longer read.
		m.drive = 1.0 + 7.0 * s(kDrive);
		m.pwmSource = sh101::ModPwmSource(getInt(kPwmModSource) - 1);   // 0 = OFF: the stock LFO position
		m.fmSource = sh101::ModFmSource(getInt(kFmSource));
		m.fmAmount = s(kFmAmount);
		if (m.fmAmount <= 0)
			m.fmSource = sh101::ModFmSource::Off; // nothing to add: skip the work
		m.lfoRateScale = kLfoScale[getInt(kLfoRange)];
		m.lfoTrig = getInt(kLfoTrig) != 0;
		m.triLevel = s(kTriLevel);
		return c;
	}

	// ---- presets (private) ----------------------------------------------------------------------------------------------------
	struct Fav {
		bool used = false;
		std::string name;
		std::vector<float> values; // kNumParams plain values (only the sound's are used)
	};

	static bool inPreset(int i) { return isSynth(i) && i != kQuality; }

	// Set the sound's values without calling parameterChanged; process() reads them, the worker tells the host.
	void applyValues(const std::vector<float> &v)
	{
		for (int i = 0; i < kNumParams && i < int(v.size()); ++i)
			if (inPreset(i))
				values_[size_t(i)]->store(param(i).toNormalised(v[size_t(i)]), std::memory_order_relaxed);
		tellAll_.store(true);
	}

	void pushValue(int i, float plain)
	{
		values_[size_t(i)]->store(param(i).toNormalised(plain), std::memory_order_relaxed);
		t_pushing = i;
		notifyHostParameterChanged(i);
		t_pushing = -1;
	}

	void workerMain()
	{
		while (!quit_.load()) {
			std::this_thread::sleep_for(std::chrono::milliseconds(10));
			tickOnce();
		}
	}

	void tickOnce()
	{
		const long long now = nowMs();
		for (int i = kFavAdd; i < kLocalEnd; ++i)
			if (release_[i].exchange(false)) {
				held_[i].store(false);
				pushValue(i, 0.0f);
			}
		if (tellAll_.exchange(false)) { // a program pick: every setting moved
			for (int i = 0; i < kNumParams; ++i) {
				if (!isSynth(i))
					continue;
				t_pushing = i;
				notifyHostParameterChanged(i);
				t_pushing = -1;
			}
			wantDisplay_.store(true);
		}
		// a project saved with the keyboard open: it comes back closed
		if (!kbOpen_.load() && get(kKbOpen) >= 0.5f && now - stateAt_.load() > 500)
			kbDirty_.store(true);
		if (favDirty_.exchange(false)) { // new names in the PRESET menu
			saveFavs();
			wantDisplay_.store(true);
		}
		// the keyboard opened or closed, or the typed name changed. Held for half a second after a state load: the host reads
		// the restored values back then (host_sim's round trip), and a name redraw then would look like a lost value.
		if (now - stateAt_.load() > 500 && kbDirty_.exchange(false)) {
			pushValue(kKbOpen, kbOpen_.load() ? 1.0f : 0.0f);
			counter_ = (counter_ + 1) % 1024;
			pushValue(kFavName, float(counter_));
			wantDisplay_.store(true);
		}
		// at most every 100 ms, never periodically: it re-lists the programs and closes the PRESET menu
		if (wantDisplay_.load() && now - lastDisplay_ >= 100) {
			wantDisplay_.store(false);
			lastDisplay_ = now;
			requestDisplayUpdate();
		}
	}

	// mono101-presets.txt: "M101P1", then one line per used slot: "<slot>\t<name>\t<id>=<value> ..." (plain text, by parameter id).
	void loadFavs() // stdio, not iostreams: libc++'s locale statics would outlive the library at dlclose
	{
		std::lock_guard<std::mutex> g(favMu_);
		favs_.assign(kFavSlots, Fav());
		FILE *f = std::fopen(favFile_.c_str(), "r");
		char line[2048];
		if (f && std::fgets(line, sizeof line, f) && std::strncmp(line, "M101P1", 6) == 0)
			while (std::fgets(line, sizeof line, f)) {
				line[std::strcspn(line, "\r\n")] = 0;
				char *t1 = std::strchr(line, '\t');
				char *t2 = t1 ? std::strchr(t1 + 1, '\t') : nullptr;
				const int slot = std::atoi(line) - 1;
				if (!t2 || slot < 0 || slot >= kFavSlots)
					continue;
				*t2 = 0;
				Fav v;
				v.name.assign(t1 + 1, std::min(std::strlen(t1 + 1), size_t(kFavNameMax)));
				v.values = defaults_;
				parseValues(t2 + 1, v.values);
				v.used = true;
				favs_[size_t(slot)] = v;
			}
		if (f)
			std::fclose(f);
		for (int i = 0; i < kFavSlots; ++i)
			nameProgram(i);
	}

	void saveFavs() // worker thread: a snapshot under the lock, then the file (.tmp + rename)
	{
		std::vector<Fav> snap;
		{
			std::lock_guard<std::mutex> g(favMu_);
			snap = favs_;
		}
		const std::string tmp = favFile_ + ".tmp";
		FILE *f = std::fopen(tmp.c_str(), "w");
		if (!f)
			return;
		bool ok = std::fputs("M101P1\n", f) >= 0;
		for (int s = 0; s < int(snap.size()); ++s) {
			if (!snap[size_t(s)].used)
				continue;
			ok = ok && std::fprintf(f, "%d\t%s\t", s + 1, snap[size_t(s)].name.c_str()) > 0;
			bool first = true;
			for (int i = 0; i < kNumParams; ++i) {
				if (!inPreset(i))
					continue;
				ok = ok && std::fprintf(f, "%s%s=%.6g", first ? "" : " ", param(i).id.c_str(), double(snap[size_t(s)].values[size_t(i)])) > 0;
				first = false;
			}
			ok = ok && std::fputc('\n', f) != EOF;
		}
		ok = (std::fclose(f) == 0) && ok;
		if (ok)
			std::rename(tmp.c_str(), favFile_.c_str());
		else
			std::remove(tmp.c_str());
	}

	// "id=value ..." (plain values) into v; unknown ids are skipped. Modifies text.
	void parseValues(char *text, std::vector<float> &v)
	{
		char *save = nullptr;
		for (char *tok = strtok_r(text, " ", &save); tok; tok = strtok_r(nullptr, " ", &save)) {
			char *eq = std::strchr(tok, '=');
			if (!eq)
				continue;
			*eq = 0;
			for (int i = 0; i < kNumParams; ++i)
				if (isSynth(i) && !std::strcmp(tok, param(i).id.c_str())) {
					const float x = float(std::atof(eq + 1));
					v[size_t(i)] = std::min(std::max(x, param(i).min), param(i).max);
				}
		}
	}

	void nameProgram(int i) // favMu_ held
	{
		char b[8];
		std::snprintf(b, sizeof b, "U%02d ", i + 1);
		programs_[size_t(kNumFactory + i)].name = b + (favs_[size_t(i)].used ? favs_[size_t(i)].name : std::string("--"));
	}

	std::string currentName() // the picked preset's name, without the "U01 " prefix
	{
		const int p = currentProgram_;
		if (p == 0)
			return "Init";
		if (p > 0 && p < kNumFactory)
			return onex1::kFactoryPresets[p - 1].name;
		std::lock_guard<std::mutex> g(favMu_);
		if (p >= kNumFactory && p < kNumFactory + kFavSlots && favs_[size_t(p - kNumFactory)].used)
			return favs_[size_t(p - kNumFactory)].name;
		return "";
	}

	void closeKeyboard()
	{
		if (kbOpen_.exchange(false))
			kbDirty_.store(true);
	}

	void typeKey(int k) // favMu_ held; k = 0 .. kKbCount - 1
	{
		const int nchars = int(sizeof kKbChars - 1);
		if (k <= nchars) { // a character or space
			if (int(kbName_.size()) >= kFavNameMax)
				return;
			char c = k < nchars ? kKbChars[k] : ' ';
			const bool cap = kbName_.empty() || kbName_.back() == ' ';
			if (c >= 'A' && c <= 'Z') {
				if (cap == kbShift_)
					c = char(c - 'A' + 'a'); // capital at the start and after a space; SHIFT flips the next letter
				kbShift_ = false;
			}
			kbName_ += c;
		} else if (k == nchars + 1) {
			if (!kbName_.empty())
				kbName_.pop_back();
		} else if (k == nchars + 2)
			kbShift_ = !kbShift_;
	}

	void localChanged(int index, float plain)
	{
		if (index == kFavName || index == kKbOpen)
			return; // set by the plugin only
		if (plain < 0.5f) {
			held_[index].store(false);
			return;
		}
		if (held_[index].exchange(true))
			return;
		release_[index].store(true); // a momentary: back to 0 on the next worker pass
		const long long now = nowMs();
		if (now - lastFire_[index] < 250)
			return; // the second report of one tap
		lastFire_[index] = now;
		if (index >= kKbFirst) {
			if (!kbOpen_.load())
				return;
			const int k = index - kKbFirst, nchars = int(sizeof kKbChars - 1);
			if (k == nchars + 3) { // CANCEL
				closeKeyboard();
				return;
			}
			if (k == nchars + 4) { // SAVE
				saveTyped();
				return;
			}
			{
				std::lock_guard<std::mutex> g(favMu_);
				typeKey(k);
			}
			kbDirty_.store(true);
			return;
		}
		if (index == kFavAdd) { // open the keyboard on the preset's name; the sound is taken now
			std::vector<float> vals;
			for (int i = 0; i < kNumParams; ++i)
				vals.push_back(get(i));
			std::string name = currentName();
			if (name.size() > size_t(kFavNameMax))
				name.resize(size_t(kFavNameMax));
			{
				std::lock_guard<std::mutex> g(favMu_);
				kbValues_ = vals;
				kbName_ = name;
				kbShift_ = false;
			}
			kbOpen_.store(true);
			kbDirty_.store(true);
			return;
		}
		if (index == kFavDel) { // the user preset that is picked now
			const int slot = currentProgram_ - kNumFactory;
			if (slot < 0 || slot >= kFavSlots)
				return;
			bool had;
			{
				std::lock_guard<std::mutex> g(favMu_);
				had = favs_[size_t(slot)].used;
				if (had) {
					favs_[size_t(slot)] = Fav();
					nameProgram(slot);
				}
			}
			if (had)
				favDirty_.store(true);
		}
	}

	void saveTyped()
	{
		Fav v;
		{
			std::lock_guard<std::mutex> g(favMu_);
			v.values = kbValues_;
			v.name = kbName_;
		}
		while (!v.name.empty() && v.name.back() == ' ')
			v.name.pop_back();
		if (v.name.empty())
			v.name = "User";
		v.used = true;
		closeKeyboard();
		int slot = -1;
		{
			std::lock_guard<std::mutex> g(favMu_);
			for (int i = 0; i < kFavSlots && slot < 0; ++i)
				if (!favs_[size_t(i)].used)
					slot = i;
			if (slot >= 0) {
				favs_[size_t(slot)] = v;
				nameProgram(slot);
			}
		}
		if (slot < 0)
			return; // all 32 used: nothing stored (DELETE PRESET frees one)
		currentProgram_ = kNumFactory + slot; // the new preset is the picked one
		favDirty_.store(true);
	}

	std::vector<float> defaults_; // the parameters' defaults: Init
	std::vector<std::vector<float>> factory_; // the factory presets, over Init
	std::string favFile_;
	std::mutex favMu_;
	std::vector<Fav> favs_;
	std::atomic<bool> favDirty_{false}, tellAll_{false}, wantDisplay_{false};
	std::atomic<bool> kbOpen_{false}, kbDirty_{false};
	std::string kbName_;          // favMu_: the name being typed
	std::vector<float> kbValues_; // favMu_: the sound SAVE PRESET took
	bool kbShift_ = false;
	std::atomic<bool> held_[kNumParams] = {};
	std::atomic<bool> release_[kNumParams] = {};
	long long lastFire_[kNumParams] = {0};
	std::thread worker_;
	std::atomic<bool> quit_{false};
	std::atomic<long long> ignoreProgUntil_{0}, stateAt_{0};
	int counter_ = 0;
	long long lastDisplay_ = 0;

	onex1::Engine engines_[2]; // HQ, ECO
	int current_ = 0;
	double rate_ = 44100;
	int maxBlock_ = 512;
	std::vector<float> mono_;
	onex1::Event events_[kMaxEvents];
};

// The same entry as MPC_PLUGIN_ENTRY, plus a wrapped effSetChunk and effSetProgram (presets, the re-pick rule).
namespace {
VstIntPtr (*g_origDispatcher)(AEffect *, VstInt32, VstInt32, VstIntPtr, void *, float) = nullptr;

VstIntPtr onex1Dispatcher(AEffect *e, VstInt32 opcode, VstInt32 index, VstIntPtr value, void *ptr, float opt)
{
	OneX1Plugin *p = static_cast<OneX1Plugin *>(e->object);
	if (opcode == effSetChunk && p)
		return p->setChunk(e, value, ptr, g_origDispatcher);
	if (opcode == effSetProgram && p) {
		const int prev = p->currentProgram();
		const VstIntPtr r = g_origDispatcher(e, opcode, index, value, ptr, opt);
		p->programPicked(prev, int(value));
		return r;
	}
	return g_origDispatcher(e, opcode, index, value, ptr, opt);
}
} // namespace

extern "C" MPC_EXPORT AEffect *VSTPluginMain(audioMasterCallback host)
{
	if (host != nullptr && host(nullptr, audioMasterVersion, 0, 0, nullptr, 0.0f) == 0)
		return nullptr; // host is VST1 only
	AEffect *e = mpc::detail::createEffect(new OneX1Plugin(), host);
	if (e && !g_origDispatcher)
		g_origDispatcher = e->dispatcher;
	if (e)
		e->dispatcher = onex1Dispatcher;
	return e;
}
