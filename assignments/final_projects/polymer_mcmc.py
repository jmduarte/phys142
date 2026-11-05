"""Starter code for the PHYS 142/242 final project
"Polymer Collapse with MCMC: A Toy Model of Protein Folding".

Bead-spring homopolymer in reduced units (epsilon = sigma = k_B = 1):

    U(x) = sum_{i=0}^{N-2} k (|r_{i+1} - r_i| - r0)^2      bonds (fixed: never formed or broken)
         + sum_{|i-j|>=2} 4 (r_ij^-12 - r_ij^-6)           Lennard-Jones between non-bonded beads

sampled from pi(x) ~ exp(-U(x)/T) with single-bead Metropolis moves.

This is a correct but deliberately simple baseline:
  * symmetric Gaussian proposal only (so no Hastings factor is needed);
  * the full O(N^2) energy is recomputed for every proposed move;
  * pure Python/NumPy.
It is fast enough for N = 2 (Problem A). For Problems B-D you will need to make
it much faster, e.g., by computing the energy change of a single-bead move in
O(N), and/or compiling the inner loop with Numba.

Run `python polymer_mcmc.py` for a short demonstration.
"""

import numpy as np

K_BOND = 50.0  # bond stiffness k
R0 = 1.0  # bond rest length r0


def straight_chain(n_beads, r0=R0):
    """Initial configuration: beads on a straight line along x, spaced by r0."""
    x = np.zeros((n_beads, 3))
    x[:, 0] = r0 * np.arange(n_beads)
    return x


def energy(x, k=K_BOND, r0=R0):
    """Total potential energy U(x) of an (N, 3) array of bead positions."""
    bond_lengths = np.linalg.norm(np.diff(x, axis=0), axis=1)
    u_bond = k * np.sum((bond_lengths - r0) ** 2)
    i, j = np.triu_indices(len(x), k=2)  # non-bonded pairs: |i - j| >= 2
    inv_r6 = 1.0 / np.sum((x[i] - x[j]) ** 2, axis=1) ** 3
    u_lj = np.sum(4.0 * (inv_r6**2 - inv_r6))
    return u_bond + u_lj


def radius_of_gyration_sq(x):
    """R_g^2 = (1/N) sum_i |r_i - r_cm|^2."""
    return np.mean(np.sum((x - x.mean(axis=0)) ** 2, axis=1))


def metropolis(x, T, n_sweeps, step, rng):
    """Single-bead Metropolis sampling at temperature T.

    One sweep is N attempted moves. Each move picks a bead uniformly at random
    and displaces it by a Gaussian with standard deviation `step` in each
    direction. This proposal is symmetric, q(x'|x) = q(x|x'), so a move is
    accepted with probability min(1, exp(-dU/T)).

    The state is recorded after every sweep. A rejected move leaves the chain
    where it is, and that repeated state is a legitimate sample: it is recorded
    like any other. Keeping only accepted states would bias every average.

    Returns (energies, rg2, acceptance_fraction, final_x), where energies and
    rg2 hold U and R_g^2 after each sweep.
    """
    x = x.copy()
    n_beads = len(x)
    u = energy(x)
    energies = np.empty(n_sweeps)
    rg2 = np.empty(n_sweeps)
    n_accepted = 0
    for sweep in range(n_sweeps):
        for _ in range(n_beads):
            i = rng.integers(n_beads)
            x_new = x.copy()
            x_new[i] += rng.normal(0.0, step, size=3)
            u_new = energy(x_new)
            du = u_new - u
            if du <= 0.0 or rng.random() < np.exp(-du / T):
                x, u = x_new, u_new
                n_accepted += 1
        energies[sweep] = u
        rg2[sweep] = radius_of_gyration_sq(x)
    return energies, rg2, n_accepted / (n_sweeps * n_beads), x


if __name__ == "__main__":
    rng = np.random.default_rng(seed=142)  # report the seed with every result

    # N = 2 equilibrates within a few sweeps.
    energies, rg2, acceptance, _ = metropolis(
        straight_chain(2), T=1.0, n_sweeps=2000, step=0.1, rng=rng
    )
    print(
        f"N = 2,  T = 1.0: acceptance {acceptance:.2f}, "
        f"sqrt<R_g^2> = {np.sqrt(rg2[500:].mean()):.3f}"
    )

    # N = 16, started from a straight chain, is still relaxing after 2000 sweeps.
    energies, rg2, acceptance, _ = metropolis(
        straight_chain(16), T=1.0, n_sweeps=2000, step=0.1, rng=rng
    )
    drift = "  ".join(f"{energies[n - 1] / 16:+.2f}" for n in (1, 500, 1000, 2000))
    print(f"N = 16, T = 1.0: acceptance {acceptance:.2f}; U/N after 1, 500, 1000, 2000 sweeps: {drift}")
    print("No error bars, and the N = 16 chain has not equilibrated: both are part of the project.")
