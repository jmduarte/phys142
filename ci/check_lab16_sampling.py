#!/usr/bin/env python3
"""Focused numerical regression checks for the Lab 16 sampling notebook.

Run from the course-site checkout with NumPy and Matplotlib installed:
    python3 ci/check_lab16_sampling.py [labs/lab16/lab16.ipynb]

Numerical unit checks extract definitions independently. Presentation checks
execute the visible notebook cells in order, including plots and event generation,
from an empty namespace without executing RISE skip or notes cells.
"""

import ast
from contextlib import redirect_stdout
import inspect
import io
import json
import math
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

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


def run_visible_notebook(stop_after=None):
    """Follow a fresh RISE presentation without preloading hidden definitions."""
    import matplotlib.pyplot as plt

    namespace = {}
    notebook = json.loads(NOTEBOOK.read_text())
    # Execute plotting bodies, but release each figure at its normal show call.
    # No notebook code or numerical workload is replaced by the test harness.
    with redirect_stdout(io.StringIO()), patch.object(
        plt, "show", side_effect=lambda *args, **kwargs: plt.close("all")
    ):
        try:
            for index, cell in enumerate(notebook["cells"]):
                if cell["cell_type"] != "code":
                    continue
                slide_type = cell.get("metadata", {}).get("slideshow", {}).get("slide_type")
                if slide_type in {"skip", "notes"}:
                    continue
                source = "".join(cell["source"])
                exec(compile(source, f"{NOTEBOOK}:cell{index}", "exec"), namespace)
                if stop_after is not None and stop_after in namespace:
                    break
        finally:
            plt.close("all")
    return namespace


def presentation_function_usage():
    """Trace first calls in slide order, including the exercises' Python fences.

    Function bodies contribute dependencies when called, not when defined.
    This checks the notebook's named helper calls; fresh execution above also
    verifies Python's actual runtime behavior and numerical demonstrations.
    """
    notebook = json.loads(NOTEBOOK.read_text())
    entries, definitions = [], {}
    slide = -1
    for index, cell in enumerate(notebook["cells"]):
        slide_type = cell.get("metadata", {}).get("slideshow", {}).get("slide_type")
        if slide_type in {"slide", "subslide"}:
            slide += 1
        source = "".join(cell["source"])
        sources = [source] if cell["cell_type"] == "code" else re.findall(
            r"```python[ \t]*\n(.*?)```", source, flags=re.DOTALL,
        )
        for source in sources:
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    definitions.setdefault(node.name, []).append(node)
            if slide_type not in {"skip", "notes"}:
                entries.append((index, slide, tree))

    def calls_in(node):
        calls = []

        class Calls(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                # Defining a function does not execute its body.
                pass

            def visit_Call(self, node):
                self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id in definitions:
                    calls.append(node.func.id)

        Calls().visit(node)
        return calls

    def function_body(node):
        return ast.Module(body=node.body, type_ignores=[])

    # Plot wrappers such as plot_results count even though lego_plot creates
    # their figures. Derive this from the implementations, not helper names.
    plotters = {
        name for name, nodes in definitions.items()
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "plt"
            and call.func.attr in {"subplots", "figure"}
            for node in nodes for call in ast.walk(node)
        )
    }
    while True:
        expanded = plotters | {
            name for name, nodes in definitions.items()
            if any(set(calls_in(function_body(node))) & plotters for node in nodes)
        }
        if expanded == plotters:
            break
        plotters = expanded

    available, introduced, first_use, missing = {}, {}, {}, []

    def invoke(name, index, slide, chain=()):
        if name not in available:
            missing.append(f"cell {index}, slide {slide}: {' -> '.join((*chain, name))}")
            return
        node = available[name]
        definition_cell, definition_slide = introduced[name]
        first_use.setdefault(name, (definition_cell, definition_slide, index, slide))
        if name in chain:
            return
        for dependency in calls_in(function_body(node)):
            invoke(dependency, index, slide, (*chain, name))

    for index, slide, tree in entries:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                # Defaults/decorators do run while defining a function.
                for expression in [*node.decorator_list, *node.args.defaults,
                                   *filter(None, node.args.kw_defaults)]:
                    for name in calls_in(expression):
                        invoke(name, index, slide)
                available[node.name] = node
                introduced.setdefault(node.name, (index, slide))
            else:
                for name in calls_in(node):
                    invoke(name, index, slide)
    return plotters, first_use, missing


class Lab16PresentationTests(unittest.TestCase):
    def test_plotting_functions_are_introduced_on_or_just_before_first_use(self):
        plotters, first_use, _ = presentation_function_usage()
        self.assertIn("plot_results", first_use, "Include the exercise's Python fence.")
        for name in sorted(plotters):
            with self.subTest(function=name):
                self.assertIn(name, first_use, f"Plotting function {name} is never used.")
                definition_cell, definition_slide, call_cell, call_slide = first_use[name]
                self.assertIn(
                    call_slide - definition_slide, (0, 1),
                    f"{name}: definition cell {definition_cell} / slide {definition_slide}; "
                    f"first call cell {call_cell} / slide {call_slide}",
                )

    def test_notebook_functions_are_defined_before_calls_and_transitive_uses(self):
        _, _, missing = presentation_function_usage()
        self.assertEqual(missing, [], "Calls before definition:\n" + "\n".join(missing))

    def test_first_toy_runs_from_visible_setup_in_a_fresh_namespace(self):
        # This follows the short path to the reported missing-helper failure:
        # visible setup, toy definition, and the first show_toy_samples call.
        namespace = run_visible_notebook(stop_after="x_uniform")
        self.assertEqual(namespace["x_uniform"].shape, (100,))
        self.assertTrue(np.all(np.isfinite(namespace["values"])))
        self.assertTrue(np.isfinite(namespace["estimate"]))
        self.assertTrue(np.isfinite(namespace["error"]))

    def test_visible_walkthrough_runs_through_integrals_events_and_final_demos(self):
        source_before = NOTEBOOK.read_bytes()
        namespace = run_visible_notebook()
        self.assertEqual(NOTEBOOK.read_bytes(), source_before)

        # The real demonstration results must exist: preloading definitions
        # alone or executing only an early prefix cannot satisfy these checks.
        self.assertEqual(namespace["x_uniform"].shape, (100,))
        for name, expected_size in (
            ("production", 2000), ("uniform_2d", 5000), ("adaptive_2d", 5000),
        ):
            with self.subTest(result=name):
                result = namespace[name]
                self.assertEqual(result["nFunEval"], expected_size)
                self.assertEqual(result["weights"].shape, (expected_size,))
                for key in ("estimate", "error", "weights"):
                    self.assertTrue(np.all(np.isfinite(result[key])), f"{name}.{key}")
                self.assertGreaterEqual(result["error"], 0)

        for name, coordinates in (("bf", ("yy1", "yy2")), ("vg", ("yy1vegas", "yy2vegas"))):
            with self.subTest(result=name):
                result = namespace[name]
                self.assertEqual(result["events"].shape, (100_000, 2))
                for key in coordinates:
                    self.assertEqual(result[key].shape, (100_000,))
                for key, value in result.items():
                    self.assertTrue(np.all(np.isfinite(value)), f"{name}.{key}")
                self.assertEqual(result["nFunEval"], len(result["proposals"]))
                self.assertEqual(result["nTotalEval"], result["nTrainEval"] + result["nFunEval"])

        self.assertTrue(callable(namespace["smooth_and_compress"]))
        self.assertTrue(callable(namespace["show_offset_target"]))

    def test_source_notebook_has_no_saved_outputs(self):
        notebook = json.loads(NOTEBOOK.read_text())
        for index, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                with self.subTest(cell=index):
                    self.assertIsNone(cell["execution_count"])
                    self.assertEqual(cell["outputs"], [])


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

    def test_weight_summary_reports_uncertainty_on_the_mean(self):
        summarize = self.function("summarize_weights")
        estimate, uncertainty = summarize(np.array([1.0, 2.0, 4.0, 8.0]))
        self.assertAlmostEqual(estimate, 15 / 4, places=14)
        # The four squared deviations sum to 115/4. The variance of the
        # sample mean therefore uses both the n-1 and n denominators.
        self.assertAlmostEqual(uncertainty, np.sqrt(115 / 48), places=14)

    def test_one_dimensional_proposal_has_equal_bin_mass_and_correct_density(self):
        edges = np.array([-3.0, -2.9, -0.8, 4.0])
        size = 60_000
        x, q, indices = map(
            np.asarray,
            self.function("draw_1d")(edges, size, np.random.default_rng(934)),
        )
        for values in (x, q, indices):
            self.assertEqual(values.shape, (size,))
        self.assertTrue(np.issubdtype(indices.dtype, np.integer))
        self.assertTrue(np.all((indices >= 0) & (indices < 3)))
        self.assertTrue(np.all((x >= edges[indices]) & (x < edges[indices + 1])))
        counts, _ = np.histogram(x, edges)
        self.assertTrue(np.all(abs(counts - size / 3) < 6 * np.sqrt(size * 2 / 9)))
        np.testing.assert_allclose(q, 1 / (3 * np.diff(edges)[indices]), rtol=2e-15, atol=0)

    def test_constant_integral_has_zero_error_and_exact_evaluation_count(self):
        estimate = self.function("estimate_1d")
        calls = [0]

        def constant(x):
            calls[0] += np.asarray(x).size
            return np.full_like(x, 2.5)

        edges = np.array([-3.0, 4.0])
        result = estimate(constant, edges, 577, seed=29)
        self.assertEqual(calls[0], 577)
        self.assertEqual(result["nFunEval"], 577)
        self.assertAlmostEqual(result["estimate"], 17.5, places=13)
        self.assertAlmostEqual(result["error"], 0.0, places=13)
        np.testing.assert_allclose(result["weights"], 17.5, rtol=2e-15, atol=0)
        np.testing.assert_allclose(result["q"], 1 / 7, rtol=2e-15, atol=0)
        repeated = estimate(constant, edges, 577, seed=29)
        np.testing.assert_array_equal(result["x"], repeated["x"])

    def test_importance_integral_matches_independent_polynomial_quadrature(self):
        # Unequal bins on a non-unit interval detect both missing f/q weights
        # and an erroneous extra factor of the domain width.
        edges = np.array([-2.0, -1.75, 0.5, 3.0])
        saved_edges = edges.copy()
        target = lambda x: x**2 + 2 * x + 4
        result = self.function("estimate_1d")(target, edges, 60_000, seed=712)
        # Integral of x^2 + 2x + 4 over [-2,3] is 110/3. Its squared
        # integrand has this elementary antiderivative.
        primitive = lambda x: x**5 / 5 + x**4 + 4 * x**3 + 8 * x**2 + 16 * x
        exact = 110 / 3
        second_moment = np.sum(3 * np.diff(edges) * np.diff(primitive(edges)))
        exact_uncertainty = np.sqrt((second_moment - exact**2) / 60_000)
        self.assertLess(abs(result["estimate"] - exact), 6 * exact_uncertainty)
        self.assertGreater(result["error"], 0.9 * exact_uncertainty)
        self.assertLess(result["error"], 1.1 * exact_uncertainty)
        np.testing.assert_array_equal(edges, saved_edges)
        for key in ("x", "q", "weights"):
            self.assertEqual(np.asarray(result[key]).shape, (60_000,))
        np.testing.assert_allclose(result["weights"], target(result["x"]) / result["q"], rtol=2e-15)

    def test_one_dimensional_training_preserves_support_and_counts_every_evaluation(self):
        train = self.function("train_1d")
        calls = [0]

        def target(x):
            calls[0] += np.asarray(x).size
            return 0.1 + 0.9 * np.exp(-0.5 * ((x - 0.63) / 0.003)**2) / (0.003 * np.sqrt(2 * np.pi))

        result = train(target, bins=20, batch=1000, iterations=6, seed=142)
        self.assertEqual(calls[0], 6000)
        self.assertEqual(result["nTrainEval"], 6000)
        self.assertIn("history", result)
        edges = np.asarray(result["edges"])
        self.assertEqual(edges.shape, (21,))
        self.assertEqual(edges[0], 0.0)
        self.assertEqual(edges[-1], 1.0)
        self.assertTrue(np.all(np.isfinite(edges)))
        self.assertTrue(np.all(np.diff(edges) > 0))
        repeated = train(target, bins=20, batch=1000, iterations=6, seed=142)
        np.testing.assert_array_equal(edges, repeated["edges"])

        # Analytic Gaussian integrals evaluate the *true* production variance
        # of the learned proposal, independently of its sampled error bar.
        def true_weight_variance(grid):
            width = np.diff(grid)
            erf1 = np.array([math.erf((edge - 0.63) / (np.sqrt(2) * 0.003)) for edge in grid])
            erf2 = np.array([math.erf((edge - 0.63) / 0.003) for edge in grid])
            gaussian_area = np.diff(erf1) / 2
            gaussian_square_area = np.diff(erf2) / (4 * np.sqrt(np.pi) * 0.003)
            target_square_area = 0.01 * width + 0.18 * gaussian_area + 0.81 * gaussian_square_area
            integral = 0.1 + 0.9 * gaussian_area.sum()
            return np.sum(len(width) * width * target_square_area) - integral**2

        uniform_variance = true_weight_variance(np.array([0.0, 1.0]))
        self.assertLess(true_weight_variance(edges), uniform_variance / 4)

    def test_zero_damping_freezes_the_grid(self):
        target = lambda x: 0.1 + np.exp(-200 * (x - 0.63)**2)
        result = self.function("train_1d")(
            target, bins=20, batch=1000, iterations=3, alpha_damp=0.0, seed=41,
        )
        np.testing.assert_allclose(result["edges"], np.linspace(0, 1, 21), rtol=0, atol=2e-15)
        self.assertEqual(result["nTrainEval"], 3000)

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
