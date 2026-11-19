"""Unit tests for the BraidCord model layer (imported in process)."""

from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import braidcord  # noqa: E402  (path set up above)


class CatalogueTests(unittest.TestCase):
    def test_catalogue_is_coherent(self) -> None:
        self.assertEqual(braidcord.pattern_inventory_problems(), [])

    def test_required_patterns_are_present(self) -> None:
        for pattern_id in ("round-8", "square-8", "spiral-8", "flat-16"):
            self.assertIn(pattern_id, braidcord.PATTERNS)

    def test_every_pattern_fits_the_disk(self) -> None:
        for pattern in braidcord.PATTERNS.values():
            self.assertEqual(len(set(pattern.slots_used)), pattern.bobbin_count)
            for slot in pattern.slots_used:
                self.assertTrue(1 <= slot <= braidcord.DISK_SLOTS)
            for from_slot, to_slot in pattern.moves:
                self.assertIn(from_slot, pattern.slots_used)
                self.assertNotIn(to_slot, pattern.slots_used)

    def test_basis_is_advance_times_take_up(self) -> None:
        pattern = braidcord.PATTERNS["round-8"]
        self.assertAlmostEqual(pattern.basis_cm_per_turn, 0.45 * 1.12, places=6)


class LengthMathTests(unittest.TestCase):
    def test_metric_rounding_to_one_decimal(self) -> None:
        self.assertEqual(braidcord.format_cm(20.16), "20.2 cm")
        self.assertEqual(braidcord.format_cm(0.504), "0.5 cm")

    def test_inches_use_whole_inches_and_eighths(self) -> None:
        self.assertEqual(braidcord.format_inches(2.54), "1 in")
        self.assertEqual(braidcord.format_inches(2.54 * 2.5), "2 1/2 in")
        self.assertEqual(braidcord.format_inches(20.16), "7 7/8 in")
        self.assertEqual(braidcord.format_inches(2.54 * 0.75), "3/4 in")

    def test_turns_needed_rounds_up(self) -> None:
        pattern = braidcord.PATTERNS["round-8"]
        self.assertEqual(braidcord.turns_needed(pattern, 60.0), 120)
        self.assertEqual(braidcord.turns_needed(pattern, 0.1), 1)

    def test_estimate_line_states_the_basis(self) -> None:
        pattern = braidcord.PATTERNS["round-8"]
        line = braidcord.estimate_line(pattern, imperial=False, turns=40)
        self.assertIn("40 turns", line)
        self.assertIn("20.2 cm", line)
        self.assertIn("0.5040 cm/turn", line)
        reverse = braidcord.estimate_line(pattern, imperial=False, target_cm=60.0)
        self.assertIn("120 turns", reverse)


class ValidationTests(unittest.TestCase):
    def test_positive_int_rejects_bad_values(self) -> None:
        for raw in ("0", "-3", "abc", "1.5", ""):
            with self.assertRaises(braidcord.CliError):
                braidcord.parse_positive_int(raw, "--turns")
        self.assertEqual(braidcord.parse_positive_int("40", "--turns"), 40)

    def test_positive_number_rejects_bad_values(self) -> None:
        for raw in ("0", "-2", "nan", "inf", "sixty"):
            with self.assertRaises(braidcord.CliError):
                braidcord.parse_positive_number(raw, "--length")
        self.assertEqual(braidcord.parse_positive_number("60.5", "--length"), 60.5)

    def test_disk_grid_is_four_rows_of_eight(self) -> None:
        grid = braidcord.render_disk_grid({1: "1", 5: "5"})
        rows = [line for line in grid.splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row.count("|"), 9)
        self.assertIn("|  1  |", grid)
        self.assertIn("  .  ", grid)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="braidcord-test-"))
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def test_first_read_creates_a_versioned_store(self) -> None:
        store = braidcord.open_store(self.temp_dir)
        self.assertEqual(store.colors, [])
        self.assertEqual(store.setups, [])
        document = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["colors"], [])

    def test_save_is_atomic_and_leaves_no_temp_files(self) -> None:
        store = braidcord.open_store(self.temp_dir)
        store.colors.append(
            {
                "id": "crimson-0001",
                "name": "Crimson",
                "hex": "B3122E",
                "brand": "Silk",
                "notes": "",
                "created_at": braidcord.now_iso(),
            }
        )
        braidcord.save_store(store)
        reloaded = braidcord.open_store(self.temp_dir)
        self.assertEqual([c["name"] for c in reloaded.colors], ["Crimson"])
        leftovers = [p.name for p in self.temp_dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupt_store_is_quarantined_and_replaced(self) -> None:
        store_path = self.temp_dir / braidcord.STORE_FILENAME
        store_path.write_text("this is not json", encoding="utf-8")
        store = braidcord.open_store(self.temp_dir)
        self.assertEqual(store.colors, [])
        backup = self.temp_dir / (braidcord.STORE_FILENAME + braidcord.QUARANTINE_SUFFIX)
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "this is not json")
        self.assertEqual(json.loads(store_path.read_text(encoding="utf-8"))["schema_version"], 1)

    def test_store_with_wrong_shape_is_quarantined(self) -> None:
        store_path = self.temp_dir / braidcord.STORE_FILENAME
        store_path.write_text('{"colors": "nope"}', encoding="utf-8")
        store = braidcord.open_store(self.temp_dir)
        self.assertEqual(store.colors, [])
        self.assertTrue((self.temp_dir / "braidcord.json.bak").exists())


class PackagingTests(unittest.TestCase):
    def test_only_standard_library_imports(self) -> None:
        source = (ROOT / "braidcord.py").read_text(encoding="utf-8")
        modules = set(
            re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", source, re.MULTILINE)
        )
        self.assertTrue(modules)
        for module in modules:
            if module == "__future__":
                continue
            self.assertIn(module.split(".")[0], sys.stdlib_module_names, module)

    def test_the_tool_is_a_single_source_file(self) -> None:
        self.assertEqual(sorted(p.name for p in ROOT.glob("*.py")), ["braidcord.py"])

    def test_source_parses_as_python(self) -> None:
        tree = ast.parse((ROOT / "braidcord.py").read_text(encoding="utf-8"))
        self.assertIsInstance(tree, ast.Module)

    def test_catalogue_problems_helper_is_clean(self) -> None:
        self.assertEqual(braidcord.pattern_inventory_problems(), [])


if __name__ == "__main__":
    unittest.main()
