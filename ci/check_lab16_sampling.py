#!/usr/bin/env python3
"""Focused numerical regression checks for the Lab 16 sampling notebook.

Run from the course-site checkout with NumPy and Matplotlib installed:
    python3 ci/check_lab16_sampling.py [labs/lab16/lab16.ipynb]

Only imports, function definitions, and uppercase constants are executed; the
notebook's plotting demonstration and large event-generation call are omitted.
"""

import ast
import inspect
import json
from pathlib import Path
import sys
import unittest

import numpy as np


NOTEBOOK = (
    Path(sys.argv.pop(1))
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
    else Path(__file__).resolve().parents[1] / "labs/lab16/lab16.ipynb"
)


def is_constant_target(target):
    if isinstance(target, ast.Name):
        return target.id.isupper()
    if isinstance(target, (ast.Tuple, ast.List)):
        return all(is_constant_target(item) for item in target.elts)
    return False


def load_functions():
    namespace = {"__name__": "lab16_under_test"}
    notebook = json.loads(NOTEBOOK.read_text())
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        tree = ast.parse(source)
        statements = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
                statements.append(node)
            elif isinstance(node, ast.Assign) and all(
                is_constant_target(target)
                for target in node.targets
            ):
                statements.append(node)
        module = ast.Module(body=statements, type_ignores=[])
        exec(compile(module, f"{NOTEBOOK}:cell{index}", "exec"), namespace)
    return namespace


# Unequal axes and separated peaks expose errors masked by the original
# concentric Gaussians on a square domain.
ASYMMETRIC = {
    "A1": 1.3,
    "A2": 2.1,
    "MU1X": -1.8,
    "MU1Y": -0.9,
    "MU2X": 2.7,
    "MU2Y": 1.8,
    "SIGMA1X": 0.7,
    "SIGMA1Y": 0.45,
    "SIGMA2X": 0.3,
    "SIGMA2Y": 0.9,
    "XMIN": -3.0,
    "XMAX": 4.0,
    "YMIN": -2.0,
    "YMAX": 2.5,
}


def reference_density(namespace, x, y):
    """The two standard Gaussians stated in the lab, independent of its f()."""
    result = np.zeros(np.broadcast_shapes(np.shape(x), np.shape(y)))
    for component in (1, 2):
        result += namespace[f"A{component}"] * np.exp(
            -0.5
            * (
                ((x - namespace[f"MU{component}X"]) / namespace[f"SIGMA{component}X"]) ** 2
                + ((y - namespace[f"MU{component}Y"]) / namespace[f"SIGMA{component}Y"]) ** 2
            )
        )
    return result


def quadrature(namespace, integrand):
    """Independent deterministic tensor Gauss-Legendre quadrature."""
    nodes, weights = np.polynomial.legendre.leggauss(160)
    width_x = namespace["XMAX"] - namespace["XMIN"]
    width_y = namespace["YMAX"] - namespace["YMIN"]
    x = namespace["XMIN"] + 0.5 * width_x * (nodes[:, None] + 1)
    y = namespace["YMIN"] + 0.5 * width_y * (nodes[None, :] + 1)
    return float(0.25 * width_x * width_y * np.sum(weights[:, None] * weights[None, :] * integrand(x, y)))


class Lab16SamplingTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_functions()

    def function(self, name):
        function = self.ns.get(name)
        self.assertTrue(callable(function), f"Notebook must define {name}()")
        return function

    def use_asymmetric_target(self):
        self.ns.update(ASYMMETRIC)

    def assert_moments(self, x, y):
        x, y = np.asarray(x), np.asarray(y)
        density = lambda xx, yy: reference_density(self.ns, xx, yy)
        normalization = quadrature(self.ns, density)
        for name, observed, moment in (
            ("x", x, lambda xx, yy: xx),
            ("y", y, lambda xx, yy: yy),
            ("x squared", x**2, lambda xx, yy: xx**2),
            ("y squared", y**2, lambda xx, yy: yy**2),
            ("xy", x * y, lambda xx, yy: xx * yy),
        ):
            expected = quadrature(self.ns, lambda xx, yy: density(xx, yy) * moment(xx, yy)) / normalization
            second = quadrature(self.ns, lambda xx, yy: density(xx, yy) * moment(xx, yy) ** 2) / normalization
            uncertainty = np.sqrt(max(0.0, second - expected**2) / len(observed))
            self.assertLessEqual(abs(np.mean(observed) - expected), 6 * uncertainty, name)

    def test_gaussian_sigma_matches_stated_equation(self):
        self.ns.update(A1=1.0, A2=0.0, MU1X=-0.7, MU1Y=1.2, SIGMA1X=0.4, SIGMA1Y=1.7)
        f = self.function("f")
        self.assertAlmostEqual(float(f(-0.7, 1.2)), 1.0, places=14)
        self.assertAlmostEqual(float(f(-0.3, 1.2)), np.exp(-0.5), places=14)
        self.assertAlmostEqual(float(f(-0.7, 2.9)), np.exp(-0.5), places=14)
        self.assertAlmostEqual(float(f(-0.3, 2.9)), np.exp(-1), places=14)

    def test_lego_histogram_keeps_x_and_y_at_their_actual_coordinates(self):
        from unittest.mock import patch
        from mpl_toolkits.mplot3d import Axes3D
        import matplotlib.pyplot as plt

        self.ns.update(XMIN=0.0, XMAX=5.0, YMIN=0.0, YMAX=5.0)
        with patch.object(Axes3D, "bar3d") as bars, patch.object(plt, "show"):
            self.function("lego_plot")([4.1, 4.2], [1.1, 1.2], 5, "x", "y", "Test")
        x, y, _, _, _, counts = bars.call_args.args[:6]
        peak = np.argmax(counts)
        self.assertEqual(counts[peak], 2)
        self.assertEqual(x[peak], 4.0)
        self.assertEqual(y[peak], 1.0)
        plt.close("all")

    def test_grid_covers_negative_nonsquare_domain_before_and_after_training(self):
        self.use_asymmetric_target()
        setup = self.function("setup_intervals")
        for iterations in (0, 4):
            with self.subTest(iterations=iterations):
                grid = setup(NN=12, KK=1200, nIterations=iterations, seed=521)
                repeated = setup(NN=12, KK=1200, nIterations=iterations, seed=521)
                for axis, edges, widths in (("X", grid[0], grid[2]), ("Y", grid[1], grid[3])):
                    self.assertEqual(len(edges), 13)
                    self.assertEqual(edges[0], self.ns[axis + "MIN"])
                    self.assertEqual(edges[-1], self.ns[axis + "MAX"])
                    self.assertTrue(np.all(np.isfinite(edges)))
                    self.assertTrue(np.all(np.diff(edges) > 0))
                    np.testing.assert_allclose(widths, np.diff(edges), rtol=2e-14, atol=0)
                for first, second in zip(grid, repeated):
                    np.testing.assert_array_equal(first, second)

    def test_unequal_interval_proposals_have_correct_support_and_density(self):
        draw = self.function("draw_proposals")
        x_edges = np.array([-3.0, -2.9, -0.8, 4.0])
        y_edges = np.array([-5.0, -4.0, 1.0, 2.0])
        size = 60_000
        x, y, q = map(np.asarray, draw(x_edges, y_edges, size, np.random.default_rng(934)))
        for values, edges in ((x, x_edges), (y, y_edges)):
            self.assertEqual(values.shape, (size,))
            self.assertTrue(np.all((values >= edges[0]) & (values < edges[-1])))
            counts, _ = np.histogram(values, edges)
            self.assertTrue(np.all(abs(counts - size / 3) < 6 * np.sqrt(size * (1 / 3) * (2 / 3))))
        ix = np.searchsorted(x_edges, x, side="right") - 1
        iy = np.searchsorted(y_edges, y, side="right") - 1
        expected_q = 1 / (9 * np.diff(x_edges)[ix] * np.diff(y_edges)[iy])
        np.testing.assert_allclose(q, expected_q, rtol=2e-15, atol=0)

    def test_rejection_bound_covers_every_cell_with_separated_peaks(self):
        self.use_asymmetric_target()
        bound = self.function("rejection_bound")
        x_edges = np.array([-3.0, -2.5, -0.5, 4.0])
        y_edges = np.array([-2.0, -1.9, 0.5, 2.5])
        actual = bound(x_edges, y_edges)
        self.assertTrue(np.isscalar(actual) and np.isfinite(actual) and actual > 0)
        expected = 0.0
        for x0, x1 in zip(x_edges[:-1], x_edges[1:]):
            for y0, y1 in zip(y_edges[:-1], y_edges[1:]):
                cell_maximum = 0.0
                for component in (1, 2):
                    # Each independent Gaussian reaches its cell maximum at the
                    # coordinatewise closest point to its center.
                    cx = np.clip(self.ns[f"MU{component}X"], x0, x1)
                    cy = np.clip(self.ns[f"MU{component}Y"], y0, y1)
                    dx = (cx - self.ns[f"MU{component}X"]) / self.ns[f"SIGMA{component}X"]
                    dy = (cy - self.ns[f"MU{component}Y"]) / self.ns[f"SIGMA{component}Y"]
                    cell_maximum += self.ns[f"A{component}"] * np.exp(-0.5 * (dx**2 + dy**2))
                expected = max(expected, cell_maximum * 9 * (x1 - x0) * (y1 - y0))
                x = np.linspace(x0, x1, 31)[:, None]
                y = np.linspace(y0, y1, 31)[None, :]
                weights = self.ns["f"](x, y) * 9 * (x1 - x0) * (y1 - y0)
                self.assertLessEqual(float(np.max(weights)), actual * (1 + 1e-14))
        self.assertAlmostEqual(actual / expected, 1.0, places=12)

    def test_uniform_event_sampler_matches_target_and_reproduces_seed(self):
        self.use_asymmetric_target()
        # The second peak exceeds the original default bound, exposing a stale
        # bound after the parameter changes requested in the lab exercise.
        self.ns["A2"] = 8.0
        brute_force = self.function("brute_force")
        try:
            first = brute_force(6000, seed=710)
            repeated = brute_force(6000, seed=710)
        except SystemExit as error:
            self.fail(f"Uniform sampler terminated for valid changed peak parameters: {error}")
        for key in ("yy1", "yy2"):
            self.assertEqual(len(first[key]), 6000)
            np.testing.assert_array_equal(first[key], repeated[key])
        self.assertEqual(first["nFunEval"], repeated["nFunEval"])
        self.assertGreaterEqual(first["nFunEval"], 6000)
        # Both samplers report f/q. For a uniform proposal, q = 1/area,
        # so the amplitude bound on f must be multiplied by the box area.
        area = (self.ns["XMAX"] - self.ns["XMIN"]) * (self.ns["YMAX"] - self.ns["YMIN"])
        self.assertLessEqual(first["maxWeightEncountered"], (self.ns["A1"] + self.ns["A2"]) * area)
        self.assert_moments(first["yy1"], first["yy2"])

    def test_adaptive_event_sampler_matches_target_seed_and_evaluation_counts(self):
        self.use_asymmetric_target()
        vegas = self.function("vegas")
        self.assertNotIn("vegasRatioFactor", inspect.signature(vegas).parameters)
        raw_f = self.ns["f"]
        evaluations = [0]

        def counted_f(x, y):
            evaluations[0] += np.broadcast_arrays(x, y)[0].size
            return raw_f(x, y)

        self.ns["f"] = counted_f
        first = vegas(6000, NN=12, KK=1200, nIterations=5, seed=953)
        actual_evaluations = evaluations[0]
        repeated = vegas(6000, NN=12, KK=1200, nIterations=5, seed=953)
        for key in ("yy1vegas", "yy2vegas", "yy1vrho", "yy2vrho"):
            np.testing.assert_array_equal(first[key], repeated[key])
        self.assertEqual(len(first["yy1vegas"]), 6000)
        self.assertEqual(len(first["yy2vegas"]), 6000)
        self.assertEqual(first["nFunEval"], len(first["yy1vrho"]))
        self.assertEqual(first["nFunEval"], len(first["yy2vrho"]))
        self.assertEqual(first["nTrainEval"], 6000)
        self.assertEqual(first["nTotalEval"], first["nFunEval"] + first["nTrainEval"])
        self.assertEqual(first["nTotalEval"], actual_evaluations)
        self.assertLessEqual(first["maxWeightEncountered"], first["vegasRatioMax"])
        self.assert_moments(first["yy1vegas"], first["yy2vegas"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
