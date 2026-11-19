// Golden-render check and timing for 1x1's engine (src/onex1/engine.h): the workloads of Lemus's
// sh101bench (machines/sh101/tools/bench) in voice mode, at 44.1 kHz in 128-sample blocks.
//   vtest golden DIR      render every workload, write DIR/<name>.f32
//   vtest check DIR       render and compare with DIR: max |diff| and the spectral distance
//   vtest time [NAME]     thread CPU time per workload: mean %, p99 % and worst block % of real time
#include "engine.h"

#include <chrono>
#include <complex>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <ctime>
#include <functional>
#include <memory>
#include <string>
#include <vector>

using sh101::Controls;
static const double kRate = 44100;
static const int kBlock = 128;

struct Workload {
	const char *name;
	double seconds;
	std::function<void(Controls &)> setup;
	bool midi = true;
	std::function<void(Controls &, double)> automate;
};

static std::vector<Workload> workloads()
{
	std::vector<Workload> w;
	w.push_back({"midi", 8, [](Controls &) {}, true, {}});
	w.push_back({"bright", 6, [](Controls &c) {
		             c.pulseLevel = 1; c.sawLevel = 1; c.subLevel = 1; c.noiseLevel = 0.3; c.vcfFreq = 0.8;
		             c.vcfRes = 0.7; c.vcfEnv = 0.6; c.sustain = 0.8; c.volume = 1;
	             }, true, {}});
	w.push_back({"pwm-lfo-porta", 6, [](Controls &c) {
		             c.pulseLevel = 1; c.sawLevel = 0; c.pwmSource = sh101::PwmSource::Lfo; c.pulseWidth = 0.6;
		             c.vcoMod = 0.3; c.lfoRate = 0.6; c.portaMode = sh101::PortaMode::On; c.portamento = 0.5;
		             c.trigger = sh101::Trigger::Lfo;
	             }, true, {}});
	w.push_back({"longrun-resmax", 16, [](Controls &c) {
		             c.vcfRes = 1; c.vcfFreq = 0.6; c.vcfEnv = 0.4; c.vcfKybd = 1; c.sustain = 1;
	             }, true, {}});
	w.push_back({"automation", 8, [](Controls &) {}, true, [](Controls &c, double t) {
		             c.vcfFreq = 0.5 + 0.4 * std::sin(t * 1.3); c.vcfRes = 0.5 + 0.5 * std::sin(t * 0.7 + 1);
		             c.vcfEnv = 0.5 + 0.5 * std::sin(t * 0.9 + 2); c.decay = 0.5 + 0.5 * std::sin(t * 0.5 + 3);
		             c.pulseWidth = 0.5 + 0.5 * std::sin(t * 1.1 + 4); c.tune = 0.5 + 0.1 * std::sin(t * 2.3);
		             c.volume = 0.6 + 0.4 * std::sin(t * 0.3);
	             }});
	w.push_back({"idle", 8, [](Controls &) {}, false, {}});
	return w;
}

// 16ths at 120 BPM over two octaves, some legato (overlapping) and a few rests (sh101bench's line).
// "idle" plays its first note only.
static std::vector<onex1::Event> line(double seconds, bool all)
{
	std::vector<onex1::Event> m;
	const int notes[] = {48, 48, 60, 51, -1, 53, 48, 55, 58, 48, 72, 46, -1, 50, 62, 43};
	const bool legato[] = {0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0};
	const double step = 60.0 / 120 / 4;
	for (int i = 0; i * step < seconds - step; ++i) {
		const int k = i % 16;
		if (notes[k] < 0)
			continue;
		const int on = int((0.05 + i * step) * kRate), off = int((0.05 + i * step + (legato[k] ? 1.2 : 0.5) * step) * kRate);
		m.push_back({on, {0x90, (unsigned char)notes[k], 100}});
		m.push_back({off, {0x80, (unsigned char)notes[k], 0}});
		if (!all)
			break;
	}
	std::stable_sort(m.begin(), m.end(), [](const onex1::Event &a, const onex1::Event &b) { return a.frame < b.frame; });
	return m;
}

static double threadSeconds()
{
	timespec t{};
	clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t);
	return double(t.tv_sec) + 1e-9 * double(t.tv_nsec);
}

struct Timing { double mean = 0, p99 = 0, worst = 0; };

static std::vector<float> render(const Workload &w, Timing *tm = nullptr)
{
	std::unique_ptr<onex1::Engine> e(new onex1::Engine);
	Controls c;
	w.setup(c);
	e->setControls(c);
	e->eco = getenv("VTEST_ECO") != nullptr;
	e->prepare(kRate, kBlock);
	const int total = int(w.seconds * kRate);
	const auto ev = line(w.seconds, w.midi);
	std::vector<float> out(static_cast<size_t>(total));
	std::vector<double> blocks;
	size_t ei = 0;
	std::vector<onex1::Event> be;
	const double t0 = threadSeconds();
	for (int p = 0; p < total; p += kBlock) {
		const int n = std::min(kBlock, total - p);
		be.clear();
		for (; ei < ev.size() && ev[ei].frame < p + n; ++ei)
			be.push_back({ev[ei].frame - p, {ev[ei].b[0], ev[ei].b[1], ev[ei].b[2]}});
		if (w.automate) {
			w.automate(c, p / kRate);
			e->setControls(c);
		}
		const double b0 = tm ? threadSeconds() : 0;
		e->render(out.data() + p, n, be.data(), int(be.size()));
		if (tm)
			blocks.push_back((threadSeconds() - b0) / (n / kRate));
		if (getenv("VTEST_BLOCKS") && tm) {
			const auto st = e->probe().solver;
			static long lastRetried = 0;
			if (p == 0)
				lastRetried = st.retried;
			static long lastIt = 0, lastSolves = 0; printf("%s %.4f %.1f %ld %.2f %.0f\n", w.name, p / kRate, 100 * blocks.back(), st.retried - lastRetried, double(st.iterations - lastIt) / std::max(1L, st.solves - lastSolves), e->probe().vcfHz); lastIt = st.iterations; lastSolves = st.solves;
			lastRetried = st.retried;
		}
	}
	if (tm) {
		tm->mean = (threadSeconds() - t0) / w.seconds;
		std::sort(blocks.begin(), blocks.end());
		tm->p99 = blocks[size_t(blocks.size() * 0.99)];
		tm->worst = blocks.back();
	}
	return out;
}

static bool readF32(const std::string &path, std::vector<float> &v)
{
	FILE *f = fopen(path.c_str(), "rb");
	if (!f)
		return false;
	fseek(f, 0, SEEK_END);
	v.resize(size_t(ftell(f)) / 4);
	fseek(f, 0, SEEK_SET);
	const bool ok = fread(v.data(), 4, v.size(), f) == v.size();
	fclose(f);
	return ok;
}

static double db(double x) { return 20 * std::log10(x + 1e-30); }

// Spectral comparison (as Lemus's tools/compare/dinsync.py): sixth-octave band powers over
// 1024-sample Hann frames, hop 512; per frame the log-spectral distance weighted by each band's
// share of the golden frame, over frames within 60 dB of the loudest. Also frame level error.
static void fft(std::vector<std::complex<double>> &a)
{
	const size_t n = a.size();
	for (size_t i = 1, j = 0; i < n; ++i) {
		size_t bit = n >> 1;
		for (; j & bit; bit >>= 1)
			j ^= bit;
		j ^= bit;
		if (i < j)
			std::swap(a[i], a[j]);
	}
	for (size_t len = 2; len <= n; len <<= 1) {
		const std::complex<double> w = std::polar(1.0, -2 * M_PI / len);
		for (size_t i = 0; i < n; i += len) {
			std::complex<double> wk = 1;
			for (size_t k = 0; k < len / 2; ++k, wk *= w) {
				const auto u = a[i + k], v = a[i + k + len / 2] * wk;
				a[i + k] = u + v;
				a[i + k + len / 2] = u - v;
			}
		}
	}
}

static std::vector<std::vector<double>> bandFrames(const std::vector<float> &x, std::vector<double> &energy)
{
	const int n = 1024;
	std::vector<double> edges;
	for (int i = 0; i < 49; ++i)
		edges.push_back(40 * std::pow(2.0, i / 6.0));
	std::vector<std::vector<double>> out;
	for (size_t p = 0; p + n <= x.size(); p += n / 2) {
		std::vector<std::complex<double>> a(n);
		for (int i = 0; i < n; ++i)
			a[i] = x[p + i] * (0.5 - 0.5 * std::cos(2 * M_PI * i / (n - 1)));
		fft(a);
		std::vector<double> b(edges.size() - 1, 0.0);
		double e = 0;
		for (int k = 0; k <= n / 2; ++k) {
			const double f = k * 44100.0 / n, m = std::norm(a[k]);
			e += m;
			for (size_t q = 0; q + 1 < edges.size(); ++q)
				if (f >= edges[q] && f < edges[q + 1])
					b[q] += m;
		}
		out.push_back(b);
		energy.push_back(e);
	}
	return out;
}

// Returns mean LSD (dB); prints a line.
static double spectralCompare(const char *name, const std::vector<float> &ref, const std::vector<float> &out)
{
	std::vector<double> ea, eb;
	const auto a = bandFrames(ref, ea), b = bandFrames(out, eb);
	const double emax = *std::max_element(ea.begin(), ea.end());
	double sum = 0, worst = 0, lvl = 0, lvlMax = 0, worstRel = 0;
	int cnt = 0, worstFrame = 0;
	for (size_t f = 0; f < a.size(); ++f) {
		if (ea[f] < emax * 1e-6)
			continue;
		double tot = 0, acc = 0;
		for (double v : a[f])
			tot += v;
		for (size_t q = 0; q < a[f].size(); ++q) {
			const double d = 10 * std::log10((a[f][q] + 1e-12) / (b[f][q] + 1e-12));
			acc += a[f][q] / tot * d * d;
		}
		const double l = std::sqrt(acc), le = std::abs(10 * std::log10(ea[f] / eb[f]));
		sum += l;
		if (l > worst) {
			worst = l;
			worstFrame = int(f);
			worstRel = 10 * std::log10(ea[f] / emax);
		}
		lvl += le;
		lvlMax = std::max(lvlMax, le);
		++cnt;
	}
	printf("%-12s LSD mean %.3f dB  max %.3f (at %.2f s, %.0f dB under the loudest frame)  level mean %.3f dB  max %.3f\n", name, sum / cnt,
	       worst, worstFrame * 512 / 44100.0, -worstRel, lvl / cnt, lvlMax);
	return sum / cnt;
}

// Peak frequency (parabolic on log magnitude) and RMS of 8192 samples from t0, and the lag of y against x.
static void peak(const std::vector<float> &x, double t0, double &hz, double &rms)
{
	const int n = 8192, i0 = int(t0 * kRate);
	std::vector<std::complex<double>> a(n);
	double s = 0;
	for (int i = 0; i < n; ++i) {
		const double v = x[size_t(i0 + i)];
		s += v * v;
		a[i] = v * (0.5 - 0.5 * std::cos(2 * M_PI * i / (n - 1)));
	}
	rms = std::sqrt(s / n);
	fft(a);
	int k = 5;
	for (int j = 5; j < n / 2 - 1; ++j)
		if (std::abs(a[j]) > std::abs(a[k]))
			k = j;
	const double y0 = std::log(std::abs(a[k - 1])), y1 = std::log(std::abs(a[k])), y2 = std::log(std::abs(a[k + 1]));
	hz = (k + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)) * kRate / n;
}

int main(int argc, char **argv)
{
	if (argc > 1 && std::string(argv[1]) == "selfosc") {
		// Self-oscillation pitch, HQ against ECO, over FREQ: sources off, RES 10, VCA on GATE, a held C3.
		for (double fr = 0.30; fr <= 1.0001; fr += 0.05) {
			double hz[2], rms[2];
			for (int eco = 0; eco < 2; ++eco) {
				std::unique_ptr<onex1::Engine> e(new onex1::Engine);
				Controls c;
				c.pulseLevel = c.sawLevel = c.subLevel = c.noiseLevel = 0;
				c.vcfRes = 1;
				c.vcfFreq = fr;
				c.vcfEnv = 0;
				c.vcaMode = sh101::VcaMode::Gate;
				e->setControls(c);
				e->eco = eco;
				e->prepare(kRate, kBlock);
				std::vector<float> out(size_t(1.5 * kRate) + kBlock);
				onex1::Event on = {0, {0x90, 48, 100}};
				for (size_t p = 0; p + kBlock <= out.size(); p += kBlock)
					e->render(out.data() + p, kBlock, &on, p == 0 ? 1 : 0);
				peak(out, 1.2, hz[eco], rms[eco]);
			}
			printf("FREQ %.2f: HQ %9.2f Hz  ECO %9.2f Hz  %+6.2f cents  %+5.2f dB\n", fr, hz[0], hz[1], 1200 * std::log2(hz[1] / hz[0]),
			       20 * std::log10(rms[1] / rms[0]));
		}
		return 0;
	}
	if (argc > 4 && std::string(argv[1]) == "compare") {
		// vtest compare DIR_A DIR_B WORKLOAD [t0 ...]: peak and RMS in each, cents and dB of B against A.
		std::vector<float> a, b;
		readF32(std::string(argv[2]) + "/" + argv[4] + ".f32", a);
		readF32(std::string(argv[3]) + "/" + argv[4] + ".f32", b);
		for (int k = 5; k < argc; ++k) {
			const double t0 = atof(argv[k]);
			double fa, ra, fb, rb;
			peak(a, t0, fa, ra);
			peak(b, t0, fb, rb);
			printf("%s @%.2fs: A %9.2f Hz | B %9.2f Hz | %+7.2f cents  %+6.2f dB\n", argv[4], t0, fa, fb, 1200 * std::log2(fb / fa),
			       20 * std::log10(rb / ra));
		}
		return 0;
	}
	const std::string mode = argc > 1 ? argv[1] : "time";
	const std::string dir = argc > 2 ? argv[2] : "golden";
	int bad = 0;
	double sumMean = 0;
	int playing = 0;
	for (const auto &w : workloads()) {
		if (mode == "time") {
			if (argc > 2 && dir != w.name)
				continue;
			Timing t;
			render(w, &t);
			printf("%-15s mean %6.2f %%  p99 %6.2f %%  worst %6.2f %%\n", w.name, 100 * t.mean, 100 * t.p99, 100 * t.worst);
			if (strcmp(w.name, "idle") != 0) {
				sumMean += t.mean;
				++playing;
			}
			continue;
		}
		const auto out = render(w);
		const std::string path = dir + "/" + w.name + ".f32";
		if (mode == "golden") {
			FILE *f = fopen(path.c_str(), "wb");
			fwrite(out.data(), 4, out.size(), f);
			fclose(f);
			printf("%s: %zu samples\n", path.c_str(), out.size());
		} else {
			std::vector<float> ref;
			if (!readF32(path, ref) || ref.size() != out.size()) {
				printf("%-15s missing or wrong length\n", w.name);
				++bad;
				continue;
			}
			double maxd = 0;
			for (size_t i = 0; i < ref.size(); ++i)
				maxd = std::max(maxd, double(std::abs(ref[i] - out[i])));
			printf("%-15s max|diff| %7.1f dBFS  ", w.name, db(maxd));
			if (maxd == 0)
				printf("identical\n");
			else
				spectralCompare("", ref, out);
		}
	}
	if (mode == "time" && playing)
		printf("playing workloads: mean %.2f %%\n", 100 * sumMean / playing);
	return bad ? 1 : 0;
}
