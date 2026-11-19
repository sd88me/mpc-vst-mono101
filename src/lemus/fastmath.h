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

inline double fastLog1p(double x) { return std::abs(x) < 1e-4 ? x * (1 - x * (0.5 - x / 3)) : std::log(1 + x); }

} // namespace sh101
