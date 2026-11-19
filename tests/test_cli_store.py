"""End-to-end tests of the BraidCord ledger, setups and local store."""

from __future__ import annotations

import json
import os
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


def run_cli(*args: str, data_dir: Path | None = None, env: dict | None = None):
    command = [sys.executable, str(SCRIPT)]
    if data_dir is not None:
        command += ["--data-dir", str(data_dir)]
    command += list(args)
    environment = dict(os.environ)
    environment.pop("BRAIDCORD_DATA_DIR", None)
    if env:
        environment.update(env)
    return subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False, env=environment
    )


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="braidcord-store-"))
        self.addCleanup(shutil.rmtree, self.data_dir, True)

    def cli(self, *args: str, env: dict | None = None):
        return run_cli(*args, data_dir=self.data_dir, env=env)

    def assertCleanFailure(self, result) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stderr.strip().startswith("error:"))

    def add_colour(self, name: str, *extra: str) -> str:
        result = self.cli("colors", "add", name, *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def read_store(self) -> dict:
        return json.loads((self.data_dir / "braidcord.json").read_text(encoding="utf-8"))

    def full_setup_args(self, name: str = "belt", pattern: str = "round-8") -> list[str]:
        slots = braidcord.PATTERNS[pattern].slots_used
        colours = ["Crimson", "Navy", "Gold", "Slate"]
        args = ["setup", "save", name, "--pattern", pattern]
        for index, slot in enumerate(slots):
            args += ["--slot", f"{slot}={colours[index % len(colours)]}"]
        return args


class ColourLedgerTests(BaseCase):
    def test_empty_state_invites_the_first_colour(self) -> None:
        result = self.cli("colors")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No threads yet", result.stdout)
        self.assertIn("braidcord colors add Crimson --hex B3122E", result.stdout)
        self.assertEqual(self.read_store()["schema_version"], 1)

    def test_add_then_list_then_remove(self) -> None:
        confirmation = self.add_colour("Crimson", "--hex", "B3122E", "--brand", "Silk")
        self.assertIn("added colour Crimson", confirmation)
        colour_id = self.read_store()["colors"][0]["id"]
        self.assertIn(colour_id, confirmation)

        listing = self.cli("colors")
        self.assertIn("Crimson", listing.stdout)
        self.assertIn("B3122E", listing.stdout)
        self.assertIn("Silk", listing.stdout)

        removal = self.cli("colors", "rm", colour_id)
        self.assertEqual(removal.returncode, 0)
        self.assertIn("deleted colour Crimson", removal.stdout)
        self.assertNotIn(colour_id, self.cli("colors").stdout)

    def test_hex_and_hash_are_normalised(self) -> None:
        self.add_colour("Crimson", "--hex", "#b3122e")
        self.assertEqual(self.read_store()["colors"][0]["hex"], "B3122E")

    def test_bad_hex_is_refused(self) -> None:
        result = self.cli("colors", "add", "Crimson", "--hex", "zzz")
        self.assertCleanFailure(result)
        self.assertEqual(self.read_store()["colors"], [])

    def test_duplicate_name_is_refused_in_any_case(self) -> None:
        self.add_colour("Crimson")
        result = self.cli("colors", "add", "crimson")
        self.assertCleanFailure(result)
        self.assertIn("already in the ledger", result.stderr)
        self.assertEqual(len(self.read_store()["colors"]), 1)

    def test_unknown_colour_removal(self) -> None:
        result = self.cli("colors", "rm", "nope")
        self.assertCleanFailure(result)

    def test_referenced_colour_cannot_be_removed(self) -> None:
        self.add_colour("Crimson")
        self.add_colour("Navy")
        self.add_colour("Gold")
        self.add_colour("Slate")
        saved = self.cli(*self.full_setup_args())
        self.assertEqual(saved.returncode, 0, saved.stderr)
        colour_id = self.read_store()["colors"][0]["id"]

        result = self.cli("colors", "rm", colour_id)
        self.assertCleanFailure(result)
        self.assertIn("used by setup belt", result.stderr)
        self.assertEqual(len(self.read_store()["colors"]), 4)


class SetupTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        for name in ("Crimson", "Navy", "Gold", "Slate"):
            self.add_colour(name)

    def test_empty_state_shows_example_and_patterns(self) -> None:
        result = self.cli("setups")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No setups yet", result.stdout)
        self.assertIn("braidcord setup save belt --pattern round-8", result.stdout)
        self.assertIn("round-8", result.stdout)

    def test_save_list_show_and_remove(self) -> None:
        saved = self.cli(*self.full_setup_args())
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertIn("saved setup belt", saved.stdout)

        listing = self.cli("setups")
        self.assertIn("belt", listing.stdout)
        self.assertIn("round-8", listing.stdout)

        detail = self.cli("setup", "belt")
        self.assertEqual(detail.returncode, 0)
        self.assertIn("Crimson", detail.stdout)
        self.assertIn("Navy", detail.stdout)
        self.assertIn("slot  1 to slot  3", detail.stdout)
        rows = [line for line in detail.stdout.splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 4)

        removal = self.cli("setup", "rm", "belt")
        self.assertEqual(removal.returncode, 0)
        self.assertIn("deleted setup belt", removal.stdout)
        self.assertIn("No setups yet", self.cli("setups").stdout)

    def test_partial_slots_are_refused_and_nothing_is_written(self) -> None:
        result = self.cli(
            "setup",
            "save",
            "belt",
            "--pattern",
            "round-8",
            "--slot",
            "1=Crimson",
            "--slot",
            "5=Navy",
        )
        self.assertCleanFailure(result)
        self.assertIn("17", result.stderr)
        self.assertIn("29", result.stderr)
        self.assertEqual(self.read_store()["setups"], [])

    def test_unknown_colour_in_slot_names_the_ledger(self) -> None:
        result = self.cli(
            "setup",
            "save",
            "belt",
            "--pattern",
            "round-8",
            "--slot",
            "1=Chartreuse",
        )
        self.assertCleanFailure(result)
        self.assertIn("Chartreuse", result.stderr)
        self.assertIn("Crimson", result.stderr)

    def test_slot_outside_the_disk_is_refused(self) -> None:
        result = self.cli(
            "setup", "save", "belt", "--pattern", "round-8", "--slot", "40=Crimson"
        )
        self.assertCleanFailure(result)
        self.assertIn("1 to 32", result.stderr)

    def test_slot_not_used_by_the_pattern_is_refused(self) -> None:
        result = self.cli(
            "setup", "save", "belt", "--pattern", "round-8", "--slot", "2=Crimson"
        )
        self.assertCleanFailure(result)
        self.assertIn("not used by pattern round-8", result.stderr)

    def test_malformed_slot_assignment_is_refused(self) -> None:
        result = self.cli(
            "setup", "save", "belt", "--pattern", "round-8", "--slot", "Crimson"
        )
        self.assertCleanFailure(result)
        self.assertIn("SLOT=COLOUR", result.stderr)

    def test_unknown_pattern_is_refused(self) -> None:
        result = self.cli(
            "setup", "save", "belt", "--pattern", "hex-9", "--slot", "1=Crimson"
        )
        self.assertCleanFailure(result)
        self.assertIn("unknown pattern", result.stderr)

    def test_overwrite_needs_the_flag(self) -> None:
        self.assertEqual(self.cli(*self.full_setup_args()).returncode, 0)
        again = self.cli(*self.full_setup_args())
        self.assertCleanFailure(again)
        self.assertIn("--overwrite", again.stderr)
        self.assertEqual(len(self.read_store()["setups"]), 1)

        replaced = self.cli(*self.full_setup_args(), "--overwrite")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertIn("overwrote setup belt", replaced.stdout)
        self.assertEqual(len(self.read_store()["setups"]), 1)

    def test_show_with_turns_and_length(self) -> None:
        self.assertEqual(self.cli(*self.full_setup_args()).returncode, 0)
        turns = self.cli("setup", "belt", "--turns", "40")
        self.assertIn("40 turns -> 20.2 cm", turns.stdout)
        length = self.cli("setup", "belt", "--length", "60")
        self.assertIn("120 turns", length.stdout)
        imperial = self.cli("setup", "belt", "--turns", "40", "--imperial")
        self.assertIn("7 7/8 in", imperial.stdout)

    def test_show_with_bad_turns_prints_nothing_but_the_error(self) -> None:
        self.assertEqual(self.cli(*self.full_setup_args()).returncode, 0)
        result = self.cli("setup", "belt", "--turns", "0")
        self.assertCleanFailure(result)
        self.assertNotIn("Disk slot map", result.stdout)

    def test_unknown_setup_lists_saved_names(self) -> None:
        self.assertEqual(self.cli(*self.full_setup_args()).returncode, 0)
        result = self.cli("setup", "nope")
        self.assertCleanFailure(result)
        self.assertIn("belt", result.stderr)

    def test_setup_with_missing_colour_reference_still_renders(self) -> None:
        self.assertEqual(self.cli(*self.full_setup_args()).returncode, 0)
        store_path = self.data_dir / "braidcord.json"
        document = json.loads(store_path.read_text(encoding="utf-8"))
        document["colors"] = [c for c in document["colors"] if c["name"] != "Crimson"]
        store_path.write_text(json.dumps(document), encoding="utf-8")

        result = self.cli("setup", "belt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stdout)
        self.assertIn("not in the ledger", result.stdout)


class StorePersistenceTests(BaseCase):
    def test_data_dir_is_created_on_demand(self) -> None:
        nested = self.data_dir / "nested" / "deeper"
        result = run_cli("colors", "add", "Crimson", data_dir=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((nested / "braidcord.json").exists())

    def test_state_survives_between_runs(self) -> None:
        self.add_colour("Crimson")
        self.assertEqual(len(self.read_store()["colors"]), 1)
        listing = self.cli("colors")
        self.assertIn("Crimson", listing.stdout)

    def test_environment_variable_selects_the_store(self) -> None:
        env_dir = self.data_dir / "from-env"
        env_dir.mkdir()
        command = [sys.executable, str(SCRIPT), "colors", "add", "Navy"]
        environment = dict(os.environ)
        environment["BRAIDCORD_DATA_DIR"] = str(env_dir)
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=False, env=environment
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((env_dir / "braidcord.json").exists())

    def test_corrupt_store_is_quarantined_with_one_warning(self) -> None:
        store_path = self.data_dir / "braidcord.json"
        store_path.write_text("{not json", encoding="utf-8")
        result = self.cli("colors")
        self.assertEqual(result.returncode, 0)
        warnings = [line for line in result.stderr.splitlines() if line.startswith("warning:")]
        self.assertEqual(len(warnings), 1)
        self.assertTrue((self.data_dir / "braidcord.json.bak").exists())
        self.assertEqual(self.read_store()["schema_version"], 1)

    def test_global_flags_after_the_subcommand_work(self) -> None:
        result = run_cli(
            "estimate", "--pattern", "round-8", "--turns", "40", "--imperial",
            data_dir=self.data_dir,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("in", result.stdout)


if __name__ == "__main__":
    unittest.main()
