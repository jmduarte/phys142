"""Independent numerical checks for the Lab 12 teaching notebook.

Run with the course Python environment: python3 ci/check_lab12_statistics.py
Only function definitions are loaded; this never executes or rewrites a handout.
"""
import ast
import json
from pathlib import Path
import unittest

import numpy as np

NOTEBOOK = Path(__file__).resolve().parents[1] / "labs/lab12/lab12.ipynb"


def functions():
    namespace = {"np": np}
    notebook = json.loads(NOTEBOOK.read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            tree = ast.parse("".join(cell["source"]))
            definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
            exec(compile(ast.Module(body=definitions, type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
    return namespace


class StatisticsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = functions()

    def test_exact_mean_error_against_covariance_matrix(self):
        for rho in (0.0, 0.5, 0.9, -0.4):
            n = 21
            lag = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :])
            expected_variance = np.sum(rho ** lag) / n**2
            self.assertAlmostEqual(self.f["exact_mean_se"](n, rho)**2, expected_variance)

    def test_autocorrelation_against_direct_products(self):
        x = np.array([0., 1., -2., 3., 1., 0., -1.])
        centered = x - x.mean()
        expected = np.correlate(centered, centered, mode="full")[len(x)-1:]
        np.testing.assert_allclose(self.f["autocorrelation"](x, 4), expected[:5] / expected[0], atol=1e-14)

    def test_stationary_generator_reproducibility_and_moments(self):
        generate = self.f["stationary_ar1"]
        a = generate(20000, 0.8, 142)
        np.testing.assert_array_equal(a, generate(20000, 0.8, 142))
        self.assertLess(abs(a.mean()), 0.1)
        self.assertLess(abs(a.var() - 1.0), 0.1)

    def test_block_moments_preserve_raw_moments(self):
        x = np.arange(24, dtype=float) / 7
        blocks = self.f["block_moments"](x, 4)
        np.testing.assert_allclose(blocks.mean(axis=0), [x.mean(), (x*x).mean()])
        self.assertAlmostEqual(self.f["variance_statistic"](blocks.mean(axis=0)), x.var())

    def test_jackknife_mean_matches_standard_error(self):
        blocks = np.array([[1., 2.], [3., 10.], [7., 50.], [4., 20.]])
        estimate, error, replicates = self.f["jackknife"](blocks, lambda moments: moments[..., 0])
        self.assertEqual(estimate, blocks[:, 0].mean())
        self.assertAlmostEqual(error, blocks[:, 0].std(ddof=1) / np.sqrt(len(blocks)))

    def test_nonlinear_jackknife_against_deleting_raw_blocks(self):
        x = np.array([1., 2., 4., -1., 3., 7., 0., 2., 9., 1., 5., -2.])
        blocks = self.f["block_moments"](x, 3)
        _, _, replicates = self.f["jackknife"](blocks, self.f["variance_statistic"])
        expected = [np.delete(x, np.s_[i*3:(i+1)*3]).var() for i in range(4)]
        np.testing.assert_allclose(replicates, expected)

    def test_bootstrap_keeps_moment_pairs_together(self):
        blocks = np.array([[0., 0.], [2., 4.], [5., 25.]])
        # A separate raw-data reconstruction provides the expected replicate values.
        seed, count = 99, 250
        indexes = np.random.default_rng(seed).integers(0, 3, size=(count, 3))
        expected = np.array([blocks[index, 0].var() for index in indexes])
        actual = self.f["bootstrap"](blocks, self.f["variance_statistic"], count, seed)
        np.testing.assert_allclose(actual, expected, atol=1e-14)

    def test_variance_resampling_translation_and_scale(self):
        x = self.f["stationary_ar1"](1024, 0.8, 142)
        statistic = self.f["variance_statistic"]
        reference = self.f["block_moments"](x, 32)
        _, reference_error, _ = self.f["jackknife"](reference, statistic)
        reference_samples = self.f["bootstrap"](reference, statistic, 100, 142)
        for scale, shift in ((1., 7.), (-3., 0.), (2., 4.)):
            blocks = self.f["block_moments"](scale*x + shift, 32)
            _, error, _ = self.f["jackknife"](blocks, statistic)
            samples = self.f["bootstrap"](blocks, statistic, 100, 142)
            self.assertAlmostEqual(error, scale**2 * reference_error)
            np.testing.assert_allclose(samples, scale**2 * reference_samples, atol=1e-12)

    def test_invalid_analysis_is_rejected(self):
        for block_size in (0, 3, 12):
            with self.assertRaises(ValueError):
                self.f["block_moments"](np.arange(10.), block_size)
        with self.assertRaises(ValueError):
            self.f["autocorrelation"](np.ones(8), 4)
        with self.assertRaises(ValueError):
            self.f["stationary_ar1"](20, 1.0, 142)


if __name__ == "__main__":
    unittest.main(verbosity=2)
