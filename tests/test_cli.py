"""End-to-end tests of the BraidCord command line: reference and estimator."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "braidcord.py"

sys.path.insert(0, str(ROOT))
import braidcord  # noqa: E402


def run_cli(*args: str, data_dir: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT)]
    if data_dir is not None:
        command += ["--data-dir", str(data_dir)]
    command += list(args)
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="braidcord-cli-"))
        self.addCleanup(shutil.rmtree, self.data_dir, True)

    def assertCleanFailure(self, result: subprocess.CompletedProcess) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        first_line = result.stderr.strip().splitlines()[0]
        self.assertTrue(first_line.startswith("error:"), first_line)


class HelpTests(BaseCase):
    def test_help_lists_every_command_and_global_flag(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for token in ("patterns", "pattern", "colors", "setups", "setup", "estimate"):
            self.assertIn(token, result.stdout)
        self.assertIn("--data-dir", result.stdout)
        self.assertIn("--imperial", result.stdout)
        self.assertIn("~/.braidcord", result.stdout)

    def test_bare_invocation_prints_usage_and_exits_zero(self) -> None:
        result = run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: braidcord", result.stdout)

    def test_version(self) -> None:
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn(braidcord.VERSION, result.stdout)

    def test_unknown_command_is_one_error_line_plus_usage(self) -> None:
        result = run_cli("frobnicate")
        self.assertEqual(result.returncode, 2)
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("error:"))
        self.assertTrue(lines[1].startswith("usage: braidcord"))
        self.assertNotIn("Traceback", result.stderr)


class PatternTests(BaseCase):
    def test_patterns_table(self) -> None:
        result = run_cli("patterns", data_dir=self.data_dir)
        self.assertEqual(result.returncode, 0)
        for pattern_id in ("round-8", "square-8", "spiral-8", "flat-16"):
            self.assertIn(pattern_id, result.stdout)
        self.assertIn("bobbins", result.stdout)
        self.assertIn("advance/turn", result.stdout)
        self.assertIn("braidcord pattern <id>", result.stdout)

    def test_pattern_detail_has_grid_moves_and_basis(self) -> None:
        result = run_cli("pattern", "round-8", data_dir=self.data_dir)
        self.assertEqual(result.returncode, 0)
        rows = [line for line in result.stdout.splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row.count("|"), 9)
        self.assertIn("slot  1 to slot  3", result.stdout)
        self.assertIn("take-up", result.stdout)
        self.assertIn(f"{braidcord.PATTERNS['round-8'].basis_cm_per_turn:.4f}", result.stdout)

    def test_every_built_in_pattern_renders(self) -> None:
        for pattern_id in braidcord.PATTERNS:
            result = run_cli("pattern", pattern_id, data_dir=self.data_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"pattern  {pattern_id}", result.stdout)

    def test_unknown_pattern_names_the_catalogue(self) -> None:
        result = run_cli("pattern", "nope", data_dir=self.data_dir)
        self.assertCleanFailure(result)
        self.assertIn("round-8", result.stderr)
        self.assertIn("unknown pattern", result.stderr)


class EstimateTests(BaseCase):
    def test_metric_estimate(self) -> None:
        result = run_cli("estimate", "--pattern", "round-8", "--turns", "40", data_dir=self.data_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("20.2 cm", result.stdout)
        self.assertIn("0.5040 cm/turn", result.stdout)
        self.assertIn("40", result.stdout)

    def test_imperial_estimate_replaces_centimetres(self) -> None:
        result = run_cli(
            "estimate",
            "--pattern",
            "round-8",
            "--turns",
            "40",
            "--imperial",
            data_dir=self.data_dir,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("7 7/8 in", result.stdout)
        self.assertNotIn("finished  20.2 cm", result.stdout)

    def test_target_length_rounds_up_to_a_whole_turn(self) -> None:
        result = run_cli("estimate", "--pattern", "round-8", "--length", "60", data_dir=self.data_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("120 (rounded up from", result.stdout)
        self.assertIn("0.5040 cm/turn", result.stdout)

    def test_imperial_target_length_is_in_inches(self) -> None:
        result = run_cli(
            "estimate",
            "--pattern",
            "round-8",
            "--length",
            "8",
            "--imperial",
            data_dir=self.data_dir,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("target    8 in", result.stdout)
        self.assertIn("41 (rounded up from", result.stdout)

    def test_invalid_turns_fail_cleanly(self) -> None:
        for bad in ("0", "-4", "abc", "3.5"):
            result = run_cli("estimate", "--pattern", "round-8", "--turns", bad, data_dir=self.data_dir)
            self.assertCleanFailure(result)
            self.assertNotIn("estimate  pattern", result.stdout)

    def test_invalid_target_length_fails_cleanly(self) -> None:
        result = run_cli("estimate", "--pattern", "round-8", "--length", "much", data_dir=self.data_dir)
        self.assertCleanFailure(result)

    def test_both_inputs_are_refused(self) -> None:
        result = run_cli(
            "estimate",
            "--pattern",
            "round-8",
            "--turns",
            "40",
            "--length",
            "60",
            data_dir=self.data_dir,
        )
        self.assertCleanFailure(result)

    def test_no_arguments_prints_the_two_forms(self) -> None:
        result = run_cli("estimate", data_dir=self.data_dir)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--turns 40", result.stderr)
        self.assertIn("--length 60", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_pattern_flag_is_explained(self) -> None:
        result = run_cli("estimate", "--turns", "40", data_dir=self.data_dir)
        self.assertCleanFailure(result)


if __name__ == "__main__":
    unittest.main()
