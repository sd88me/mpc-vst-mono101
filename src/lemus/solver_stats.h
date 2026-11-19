#pragma once

namespace sh101 {

// What the implicit solvers did, counted since prepare() (the VCF's Newton, the jack board's, the
// VCA's control current). A solve that doesn't converge in its iterations is retried in smaller
// steps where the solver can (retried); one that still doesn't converge is accepted as it stands
// and counted (failures). tools/corners checks that failures stay at zero over the controls'
// extremes: an unconverged sample is silent in every other check, and near the top of the VCF's
// range it once turned the self-oscillation into white noise (docs/improvements.md, 2026-11-16).
struct SolverStats {
	long solves = 0, retried = 0, failures = 0;
	long iterations = 0; // 1x1: Newton iterations, retries included (the VCF's)
	SolverStats &operator+=(const SolverStats &o)
	{
		solves += o.solves;
		retried += o.retried;
		failures += o.failures;
		iterations += o.iterations;
		return *this;
	}
};

} // namespace sh101
