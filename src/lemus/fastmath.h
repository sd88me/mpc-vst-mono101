#pragma once
// 1x1: inline exp and what is built on it, for the circuit solvers' per-sample calls (from Acid-303,
// src/lemus/voice.cpp). glibc's exp is an out-of-line call with full special-case handling, and on
// armhf its tanh/expm1/log1p are the old fdlibm routines, several times slower.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace sh101 {

// 2^(k/64) from a table times a 4th-order polynomial on |r| < ln2/128: relative error ~4e-14.
// Arguments are clamped to +/-700.
struct FastExpTable {
	double t[64];
	FastExpTable()
	{
		for (int i = 0; i < 64; ++i)
			t[i] = std::exp2(i / 64.0);
	}
};
inline const FastExpTable kFastExpTable;

inline double fastExp(double x)
{
	constexpr double kN = 64 / 0.69314718055994530942, kLn2HiN = 0.69314718055994530942 / 64;
	x = std::clamp(x, -700.0, 700.0);
	const double xn = x * kN;
	const int k = int(xn + (xn >= 0 ? 0.5 : -0.5)); // round (nearbyint is a libm call on armhf)
	const double r = x - double(k) * kLn2HiN;
	const double p = 1 + r * (1 + r * (0.5 + r * (1.0 / 6 + r * (1.0 / 24))));
	const uint64_t bits = uint64_t(int64_t(k >> 6) + 1023) << 52;
	double scale;
	std::memcpy(&scale, &bits, sizeof scale);
	return scale * kFastExpTable.t[k & 63] * p;
}

// expm1 without cancellation near 0 (a series under 1e-2), else through fastExp.
inline double fastExpm1(double x)
{
	if (std::abs(x) < 1e-2)
		return x * (1 + x * (0.5 + x * (1.0 / 6 + x * (1.0 / 24 + x * (1.0 / 120)))));
	return fastExp(x) - 1;
}

inline double fastTanh(double x)
{
	if (std::abs(x) > 19)
		return x > 0 ? 1.0 : -1.0;
	const double e = fastExpm1(2 * x);
	return e / (e + 2);
}

// log for x > 0 (normal doubles): x = m 2^e with m in [sqrt(1/2), sqrt(2)), then
// log m = 2 atanh(s), s = (m - 1) / (m + 1), |s| < 0.172, by its series to s^21: relative error ~1e-16.
// 0 or negative gives -745 (as log of the smallest denormal), not -inf or NaN.
inline double fastLog(double x)
{
	if (!(x >= 2.2250738585072014e-308))
		return x > 0 ? std::log(x) : -745.0;
	uint64_t bits;
	std::memcpy(&bits, &x, sizeof bits);
	int e = int(bits >> 52) - 1023;
	bits = (bits & 0x000fffffffffffffull) | 0x3ff0000000000000ull; // m in [1, 2)
	double m;
	std::memcpy(&m, &bits, sizeof m);
	if (m > 1.4142135623730951) {
		m *= 0.5;
		++e;
	}
	const double s = (m - 1) / (m + 1), z = s * s;
	const double p = 1 + z * (1.0 / 3 + z * (1.0 / 5 + z * (1.0 / 7 + z * (1.0 / 9 + z * (1.0 / 11 + z * (1.0 / 13 +
	                 z * (1.0 / 15 + z * (1.0 / 17 + z * (1.0 / 19 + z * (1.0 / 21))))))))));
	return e * 0.69314718055994530942 + 2 * s * p;
}

inline double fastLog1p(double x) { return std::abs(x) < 1e-4 ? x * (1 - x * (0.5 - x / 3)) : fastLog(1 + x); }

// asinh for the junction-limiting steps (large |x|; exact enough near 0 through the series).
inline double fastAsinh(double x)
{
	const double a = std::abs(x);
	const double r = a < 1e-3 ? a * (1 - a * a / 6) : fastLog(a + std::sqrt(a * a + 1));
	return x < 0 ? -r : r;
}

// tan(w) / w for 0 <= w < pi/2: halved until under 0.1, the series there (to w^12, error ~1e-16),
// then the double-angle formula back up. The prewarps call it every sample as the cutoff moves.
inline double fastTanOverX(double w)
{
	int halvings = 0;
	double v = w;
	while (v > 0.1 && halvings < 6) {
		v *= 0.5;
		++halvings;
	}
	const double z = v * v;
	double t = v * (1 + z * (1.0 / 3 + z * (2.0 / 15 + z * (17.0 / 315 + z * (62.0 / 2835 + z * (1382.0 / 155925 +
	           z * (21844.0 / 6081075)))))));
	for (int i = 0; i < halvings; ++i)
		t = 2 * t / (1 - t * t);
	return w > 0 ? t / w : 1.0;
}

// cbrt for x > 0: a bit-level first guess, then Newton (three steps from ~5 % to full precision,
// a fourth to be safe).
inline double fastCbrt(double x)
{
	if (!(x > 0))
		return std::cbrt(x);
	uint64_t bits;
	std::memcpy(&bits, &x, sizeof bits);
	bits = bits / 3 + (uint64_t(715094163) << 32); // fdlibm's B1 on the whole word
	double y;
	std::memcpy(&y, &bits, sizeof y);
	for (int i = 0; i < 4; ++i)
		y -= (y - x / (y * y)) / 3;
	return y;
}

} // namespace sh101
