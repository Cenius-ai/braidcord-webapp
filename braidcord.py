#!/usr/bin/env python3
"""BraidCord - Kumihimo braid reference, colour ledger and length estimator.

BraidCord is a single-file, standard-library-only command line tool. It ships a
built-in catalogue of disk braid patterns keyed by disk slot, a persistent
thread colour ledger with named braid setups, and a finished-length estimator
driven by disk turns.

    python3 braidcord.py --help
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

VERSION = "1.0.0"
SCHEMA_VERSION = 1
DISK_SLOTS = 32
SLOTS_PER_ROW = 8
STORE_FILENAME = "braidcord.json"
QUARANTINE_SUFFIX = ".bak"
USAGE_LINE = "usage: braidcord [--data-dir DIR] [--imperial] <command> [args]"
RESERVED_SETUP_NAMES = ("save", "rm")


class CliError(Exception):
    """A user-facing failure: printed as one line prefixed with ``error:``."""


class StoreFormatError(Exception):
    """The store file parsed but does not hold a BraidCord document."""


# --------------------------------------------------------------------------
# Built-in pattern catalogue (reference data, never written to the store)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    """One braid structure: where the bobbins sit and how they move."""

    id: str
    name: str
    bobbin_count: int
    slots_used: tuple[int, ...]
    moves: tuple[tuple[int, int], ...]
    advance_cm_per_turn: float
    take_up_factor: float
    description: str

    @property
    def basis_cm_per_turn(self) -> float:
        """Finished centimetres gained per disk turn (advance x take-up)."""
        return round(self.advance_cm_per_turn * self.take_up_factor, 6)


PATTERNS: dict[str, Pattern] = {
    "round-8": Pattern(
        id="round-8",
        name="Kongo round",
        bobbin_count=8,
        slots_used=(1, 5, 9, 13, 17, 21, 25, 29),
        moves=((1, 3), (9, 11), (17, 19), (25, 27)),
        advance_cm_per_turn=0.45,
        take_up_factor=1.12,
        description="Hollow round cord, the standard first braid on a disk.",
    ),
    "square-8": Pattern(
        id="square-8",
        name="Edo square",
        bobbin_count=8,
        slots_used=(2, 6, 10, 14, 18, 22, 26, 30),
        moves=((2, 4), (18, 20), (10, 12), (26, 28)),
        advance_cm_per_turn=0.40,
        take_up_factor=1.10,
        description="Crisp square profile worked in two opposing pairs per turn.",
    ),
    "spiral-8": Pattern(
        id="spiral-8",
        name="Twist spiral",
        bobbin_count=8,
        slots_used=(1, 5, 9, 13, 17, 21, 25, 29),
        moves=((1, 3), (5, 7), (9, 11), (13, 15), (17, 19), (21, 23), (25, 27), (29, 31)),
        advance_cm_per_turn=0.50,
        take_up_factor=1.15,
        description="Single-direction twist: every bobbin steps clockwise each turn.",
    ),
    "flat-16": Pattern(
        id="flat-16",
        name="Hirayaka flat",
        bobbin_count=16,
        slots_used=(1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19, 20, 21, 22, 23, 24),
        moves=((1, 10), (3, 12), (5, 14), (7, 16), (17, 26), (19, 28), (21, 30), (23, 32)),
        advance_cm_per_turn=0.35,
        take_up_factor=1.08,
        description="Flat ribbon, two banks of eight bobbins interlacing across the disk.",
    ),
    "kongo-4": Pattern(
        id="kongo-4",
        name="Kongo round mini",
        bobbin_count=4,
        slots_used=(1, 9, 17, 25),
        moves=((1, 3), (17, 19)),
        advance_cm_per_turn=0.60,
        take_up_factor=1.10,
        description="Four-bobbin round cord, the quickest first project on a disk.",
    ),
}


def pattern_inventory_problems() -> list[str]:
    """Return catalogue problems (empty when the built-in data is coherent)."""
    problems: list[str] = []
    for key, pattern in PATTERNS.items():
        if key != pattern.id:
            problems.append(f"{key}: key does not match id {pattern.id!r}")
        used = set(pattern.slots_used)
        if len(used) != len(pattern.slots_used):
            problems.append(f"{pattern.id}: duplicate slot in slots_used")
        if len(used) != pattern.bobbin_count:
            problems.append(f"{pattern.id}: {pattern.bobbin_count} bobbins but {len(used)} slots")
        out_of_range = [s for s in used if not 1 <= s <= DISK_SLOTS]
        if out_of_range:
            problems.append(f"{pattern.id}: slots out of range {out_of_range}")
        targets: set[int] = set()
        for from_slot, to_slot in pattern.moves:
            if from_slot not in used:
                problems.append(f"{pattern.id}: move from unused slot {from_slot}")
            if to_slot in used or to_slot in targets:
                problems.append(f"{pattern.id}: move target {to_slot} is not a free slot")
            if not 1 <= to_slot <= DISK_SLOTS:
                problems.append(f"{pattern.id}: move target {to_slot} is off the disk")
            targets.add(to_slot)
        if pattern.basis_cm_per_turn <= 0:
            problems.append(f"{pattern.id}: basis must be positive")
    return problems


# --------------------------------------------------------------------------
# Store: one JSON document, atomic writes, quarantine on corruption
# --------------------------------------------------------------------------


@dataclass
class Store:
    """The local JSON document: thread colours plus named braid setups."""

    path: Path
    colors: list[dict[str, Any]]
    setups: list[dict[str, Any]]
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "colors": self.colors,
            "setups": self.setups,
        }


def display_path(path: Path) -> str:
    """Render a path with ``~`` for the home directory, for readable messages."""
    try:
        return "~/" + str(path.expanduser().relative_to(Path.home()))
    except ValueError:
        return str(path)


def resolve_data_dir(raw: str | None) -> Path:
    """--data-dir wins, then $BRAIDCORD_DATA_DIR, then ~/.braidcord."""
    if raw:
        return Path(raw).expanduser()
    from_env = os.environ.get("BRAIDCORD_DATA_DIR", "").strip()
    if from_env:
        return Path(from_env).expanduser()
    return Path.home() / ".braidcord"


def _colors_from_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    colors = data.get("colors", [])
    if not isinstance(colors, list):
        raise StoreFormatError("colors must be a list")
    cleaned: list[dict[str, Any]] = []
    for entry in colors:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("name"):
            raise StoreFormatError("every colour needs an id and a name")
        cleaned.append(
            {
                "id": str(entry["id"]),
                "name": str(entry["name"]),
                "hex": str(entry.get("hex") or ""),
                "brand": str(entry.get("brand") or ""),
                "notes": str(entry.get("notes") or ""),
                "created_at": str(entry.get("created_at") or ""),
            }
        )
    return cleaned


def _setups_from_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    setups = data.get("setups", [])
    if not isinstance(setups, list):
        raise StoreFormatError("setups must be a list")
    cleaned: list[dict[str, Any]] = []
    for entry in setups:
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("pattern_id"):
            raise StoreFormatError("every setup needs a name and a pattern_id")
        slot_colors = entry.get("slot_colors", {})
        if not isinstance(slot_colors, dict):
            raise StoreFormatError("slot_colors must be an object of slot -> colour id")
        cleaned.append(
            {
                "name": str(entry["name"]),
                "pattern_id": str(entry["pattern_id"]),
                "slot_colors": {str(k): str(v) for k, v in slot_colors.items()},
                "notes": str(entry.get("notes") or ""),
                "created_at": str(entry.get("created_at") or ""),
                "updated_at": str(entry.get("updated_at") or ""),
            }
        )
    return cleaned


def _quarantine(path: Path, reason: BaseException) -> None:
    """Move an unreadable store aside with exactly one warning line."""
    backup = path.parent / (path.name + QUARANTINE_SUFFIX)
    try:
        os.replace(path, backup)
        outcome = f"moved it to {display_path(backup)}"
    except OSError as exc:
        outcome = f"could not move it aside ({exc.strerror or exc})"
    print(
        f"warning: {display_path(path)} is unreadable ({reason}); {outcome} and started a fresh one",
        file=sys.stderr,
    )


def save_store(store: Store) -> None:
    """Write the store through a temp file plus rename so a crash cannot tear it."""
    path = store.path
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise CliError(
            f"cannot create the data directory {display_path(path.parent)}: {exc.strerror or exc}"
        )
    payload = json.dumps(store.to_json(), indent=2) + "\n"
    temp_path: Path | None = None
    try:
        handle_fd, temp_name = tempfile.mkstemp(
            prefix=".braidcord-", suffix=".tmp", dir=str(path.parent)
        )
        temp_path = Path(temp_name)
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise CliError(
            f"cannot write the store at {display_path(path)}: {exc.strerror or exc}"
        )
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def open_store(data_dir: Path) -> Store:
    """Load the store, creating it on first use and quarantining bad files."""
    path = data_dir / STORE_FILENAME
    if not path.exists():
        store = Store(path=path, colors=[], setups=[])
        save_store(store)
        return store
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise StoreFormatError("the document is not an object")
        version = document.get("schema_version", SCHEMA_VERSION)
        if not isinstance(version, int):
            raise StoreFormatError("schema_version must be a whole number")
        return Store(
            path=path,
            colors=_colors_from_json(document),
            setups=_setups_from_json(document),
            schema_version=version,
        )
    except (OSError, ValueError, StoreFormatError) as exc:
        _quarantine(path, exc)
        store = Store(path=path, colors=[], setups=[])
        save_store(store)
        return store


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# Lookups and validation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    data_dir: Path
    imperial: bool


def find_pattern(pattern_id: str) -> Pattern:
    pattern = PATTERNS.get(str(pattern_id).strip().lower())
    if pattern is None:
        available = ", ".join(PATTERNS) or "none"
        raise CliError(f"unknown pattern {pattern_id!r}; available patterns: {available}")
    return pattern


def find_color(store: Store, name_or_id: str) -> dict[str, Any] | None:
    key = str(name_or_id).strip().casefold()
    for color in store.colors:
        if color["id"].casefold() == key or color["name"].casefold() == key:
            return color
    return None


def find_setup(store: Store, name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    for setup in store.setups:
        if setup["name"].casefold() == key:
            return setup
    saved = ", ".join(s["name"] for s in store.setups) or "none yet"
    raise CliError(f"unknown setup {name!r}; saved setups: {saved}")


def unknown_colour_message(store: Store, name: str) -> str:
    if not store.colors:
        return (
            f"unknown colour {name!r}; the ledger is empty, "
            f"add one with: braidcord colors add {name}"
        )
    known = ", ".join(color["name"] for color in store.colors)
    return f"unknown colour {name!r}; ledger colours: {known}"


def parse_positive_int(raw: Any, label: str) -> int:
    text = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise CliError(f"{label} must be a positive whole number, got {raw!r}")
    value = int(text)
    if value < 1:
        raise CliError(f"{label} must be a positive whole number, got {value}")
    return value


def parse_positive_number(raw: Any, label: str) -> float:
    text = str(raw).strip()
    try:
        value = float(text)
    except ValueError:
        raise CliError(f"{label} must be a positive number, got {raw!r}")
    if not math.isfinite(value) or value <= 0:
        raise CliError(f"{label} must be a positive number, got {raw!r}")
    return value


def parse_slot_assignments(
    raw_values: Sequence[str], pattern: Pattern, store: Store
) -> dict[str, str]:
    """Turn repeated --slot SLOT=COLOUR into {slot: colour id}, fully validated."""
    assignments: dict[str, str] = {}
    for raw in raw_values:
        match = re.fullmatch(r"\s*(\d+)\s*=\s*(.+?)\s*", str(raw))
        if not match:
            raise CliError(
                f"--slot expects SLOT=COLOUR, got {raw!r} (for example --slot 1=Crimson)"
            )
        slot = int(match.group(1))
        colour_name = match.group(2)
        if not 1 <= slot <= DISK_SLOTS:
            raise CliError(f"slot {slot} is off the disk: slots run from 1 to {DISK_SLOTS}")
        if slot not in pattern.slots_used:
            raise CliError(
                f"slot {slot} is not used by pattern {pattern.id}; "
                f"it uses slots {format_slot_list(pattern.slots_used)}"
            )
        if str(slot) in assignments:
            raise CliError(f"slot {slot} is assigned twice; give one colour per slot")
        color = find_color(store, colour_name)
        if color is None:
            raise CliError(unknown_colour_message(store, colour_name))
        assignments[str(slot)] = color["id"]
    missing = [slot for slot in pattern.slots_used if str(slot) not in assignments]
    if missing:
        raise CliError(
            f"pattern {pattern.id} uses {len(pattern.slots_used)} slots; "
            f"slots {format_slot_list(missing)} still need a colour "
            f"(add --slot {missing[0]}=Colour)"
        )
    return assignments


# --------------------------------------------------------------------------
# Presentation helpers (plain ASCII, aligned columns, no ANSI escapes)
# --------------------------------------------------------------------------


def format_slot_list(slots: Sequence[int]) -> str:
    return ", ".join(str(slot) for slot in slots)


def plural(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append(
            "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        )
    return "\n".join(lines)


def render_disk_grid(labels: dict[int, str], empty: str = ".") -> str:
    """Draw the 32-slot disk as four rows of eight cells."""
    cells = [labels.get(slot, empty) for slot in range(1, DISK_SLOTS + 1)]
    width = max(3, max(len(cell) for cell in cells))
    border = "+" + "+".join(["-" * (width + 2)] * SLOTS_PER_ROW) + "+"
    lines = [border]
    for row_index in range(DISK_SLOTS // SLOTS_PER_ROW):
        row = cells[row_index * SLOTS_PER_ROW : (row_index + 1) * SLOTS_PER_ROW]
        body = "|" + "|".join(f" {cell:^{width}} " for cell in row) + "|"
        first = row_index * SLOTS_PER_ROW + 1
        last = first + SLOTS_PER_ROW - 1
        lines.append(f"{body}   slots {first}-{last}")
        lines.append(border)
    return "\n".join(lines)


def format_cm(value_cm: float) -> str:
    return f"{value_cm:.1f} cm"


def format_inches(value_cm: float) -> str:
    """Whole inches plus fractional eighths, the way a braider measures."""
    total_eighths = int(round(value_cm / 2.54 * 8))
    whole, fraction_eighths = divmod(total_eighths, 8)
    if fraction_eighths == 0:
        return f"{whole} in"
    fraction = str(Fraction(fraction_eighths, 8))
    return f"{fraction} in" if whole == 0 else f"{whole} {fraction} in"


def format_length(value_cm: float, imperial: bool) -> str:
    return format_inches(value_cm) if imperial else format_cm(value_cm)


def basis_line(pattern: Pattern, imperial: bool) -> str:
    text = (
        f"{pattern.advance_cm_per_turn:.4f} cm/turn advance x "
        f"{pattern.take_up_factor:.2f} take-up = {pattern.basis_cm_per_turn:.4f} cm/turn"
    )
    if imperial:
        text += f" ({pattern.basis_cm_per_turn / 2.54:.4f} in/turn)"
    return text


def turns_needed(pattern: Pattern, target_cm: float) -> int:
    exact = target_cm / pattern.basis_cm_per_turn
    return max(1, math.ceil(exact - 1e-9))


def estimate_line(
    pattern: Pattern,
    imperial: bool,
    turns: int | None = None,
    target_cm: float | None = None,
) -> str:
    if turns is not None:
        finished = turns * pattern.basis_cm_per_turn
        return (
            f"{turns} turns -> {format_length(finished, imperial)}"
            f"   (basis {pattern.basis_cm_per_turn:.4f} cm/turn)"
        )
    if target_cm is None:
        raise CliError("estimate needs either a turn count or a target length")
    needed = turns_needed(pattern, target_cm)
    return (
        f"{format_length(target_cm, imperial)} needs {needed} turns"
        f"   (basis {pattern.basis_cm_per_turn:.4f} cm/turn)"
    )

# --------------------------------------------------------------------------
# Commands: pattern reference
# --------------------------------------------------------------------------


def cmd_patterns(options: Options) -> int:
    if not PATTERNS:
        print("error: no braid patterns are built in to this copy of BraidCord", file=sys.stderr)
        return 2
    rows = [
        (
            pattern.id,
            pattern.name,
            str(pattern.bobbin_count),
            f"{pattern.advance_cm_per_turn:.2f} cm",
        )
        for pattern in PATTERNS.values()
    ]
    print(f"Built-in braid patterns ({len(rows)})")
    print()
    print(render_table(("id", "name", "bobbins", "advance/turn"), rows))
    print()
    print("hint: run braidcord pattern <id> for its disk slot map and turn sequence")
    return 0


def cmd_pattern(options: Options, pattern_id: str) -> int:
    pattern = find_pattern(pattern_id)
    print(f"pattern  {pattern.id}  {pattern.name}")
    print(f"         {pattern.description}")
    print(
        f"         {pattern.bobbin_count} bobbins on slots "
        f"{format_slot_list(pattern.slots_used)}"
    )
    print()
    print("Disk slot map (32 slots, slot 1 at the top, numbered clockwise)")
    print()
    print(render_disk_grid({slot: str(slot) for slot in pattern.slots_used}))
    print()
    print(f"Turn sequence ({len(pattern.moves)} moves, worked in this order)")
    for index, (from_slot, to_slot) in enumerate(pattern.moves, start=1):
        print(f" {index:2d}. slot {from_slot:2d} to slot {to_slot:2d}")
    print()
    print("Basis for the length estimator")
    print(f" advance  {pattern.advance_cm_per_turn:.4f} cm per turn")
    print(f" take-up  {pattern.take_up_factor:.2f} (allowance for the braid tightening)")
    print(f" basis    {pattern.basis_cm_per_turn:.4f} cm per turn")
    print()
    print(f"hint: braidcord estimate --pattern {pattern.id} --turns 40")
    return 0


# --------------------------------------------------------------------------
# Commands: length estimator
# --------------------------------------------------------------------------


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def cmd_estimate(options: Options, args: argparse.Namespace) -> int:
    if args.turns is None and args.length is None:
        print("estimate: pick one of the two forms", file=sys.stderr)
        print("  braidcord estimate --pattern round-8 --turns 40", file=sys.stderr)
        print("  braidcord estimate --pattern round-8 --length 60", file=sys.stderr)
        print("hint: add --imperial for inches as whole inches plus eighths", file=sys.stderr)
        return 2
    if args.turns is not None and args.length is not None:
        raise CliError("give either --turns or --length, not both")
    if not args.pattern:
        raise UsageError("estimate needs --pattern, for example --pattern round-8")

    pattern = find_pattern(args.pattern)
    turns = parse_positive_int(args.turns, "--turns") if args.turns is not None else None
    target_value = (
        parse_positive_number(args.length, "--length") if turns is None else None
    )
    print(
        f"estimate  pattern {pattern.id} "
        f"({pattern.name}, {pattern.bobbin_count} bobbins)"
    )
    print(f"basis     {basis_line(pattern, options.imperial)}")
    if turns is not None:
        finished = turns * pattern.basis_cm_per_turn
        print(f"turns     {turns}")
        print(f"finished  {format_length(finished, options.imperial)}")
        return 0

    assert target_value is not None  # guarded by the checks above
    target_cm = target_value * 2.54 if options.imperial else target_value
    exact = target_cm / pattern.basis_cm_per_turn
    if options.imperial:
        print(f"target    {format_number(target_value)} in = {target_cm:.1f} cm")
    else:
        print(f"target    {format_cm(target_cm)}")
    print(f"turns     {turns_needed(pattern, target_cm)} (rounded up from {exact:.2f})")
    return 0


# --------------------------------------------------------------------------
# Commands: thread colour ledger
# --------------------------------------------------------------------------


def cmd_colors(options: Options, args: argparse.Namespace) -> int:
    store = open_store(options.data_dir)
    action = getattr(args, "colors_command", None)
    if action == "add":
        return colors_add(store, args)
    if action == "rm":
        return colors_remove(store, args.color_id)
    return colors_list(store)


def colors_list(store: Store) -> int:
    if not store.colors:
        print(
            "No threads yet, add your first with: "
            "braidcord colors add Crimson --hex B3122E"
        )
        print(f"store: {display_path(store.path)}")
        return 0
    rows = [
        (color["id"], color["name"], color["hex"] or "-", color["brand"] or "-")
        for color in store.colors
    ]
    print(f"Colour ledger ({plural(len(rows), 'thread')})")
    print()
    print(render_table(("id", "name", "hex", "brand"), rows))
    print()
    print("hint: remove one with: braidcord colors rm <id>")
    print(f"store: {display_path(store.path)}")
    return 0


def normalise_hex(raw: str) -> str:
    text = raw.strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{3}|[0-9A-F]{6}", text):
        raise CliError(f"hex must be 3 or 6 hex digits, got {raw!r} (for example B3122E)")
    return text


def make_color_id(name: str, existing_ids: set[str]) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "colour"
    for _ in range(50):
        candidate = f"{slug}-{secrets.token_hex(2)}"
        if candidate not in existing_ids:
            return candidate
    raise CliError("could not generate a unique colour id; try a different name")


def colors_add(store: Store, args: argparse.Namespace) -> int:
    name = str(args.name).strip()
    if not name:
        raise CliError("a colour needs a name, for example: braidcord colors add Crimson")
    if len(name) > 40:
        raise CliError(f"colour name {name!r} is longer than 40 characters")
    existing = find_color(store, name)
    if existing is not None:
        raise CliError(
            f"colour {existing['name']!r} ({existing['id']}) is already in the ledger"
        )
    hex_value = normalise_hex(args.hex_value) if args.hex_value else ""
    color = {
        "id": make_color_id(name, {c["id"] for c in store.colors}),
        "name": name,
        "hex": hex_value,
        "brand": str(args.brand).strip(),
        "notes": str(args.notes).strip(),
        "created_at": now_iso(),
    }
    store.colors.append(color)
    save_store(store)
    print(f"added colour {color['name']} ({color['id']})")
    return 0


def colors_remove(store: Store, name_or_id: str) -> int:
    color = find_color(store, name_or_id)
    if color is None:
        if not store.colors:
            raise CliError(
                f"unknown colour {name_or_id!r}; the ledger is empty, "
                "add one with: braidcord colors add Crimson --hex B3122E"
            )
        known = ", ".join(c["id"] for c in store.colors)
        raise CliError(f"unknown colour {name_or_id!r}; ledger ids: {known}")
    users = [
        setup["name"]
        for setup in store.setups
        if color["id"] in setup["slot_colors"].values()
    ]
    if users:
        raise CliError(
            f"colour {color['name']} ({color['id']}) is used by setup "
            f"{', '.join(users)}; re-save or delete those setups first"
        )
    store.colors = [c for c in store.colors if c["id"] != color["id"]]
    save_store(store)
    print(f"deleted colour {color['name']} ({color['id']})")
    return 0

# --------------------------------------------------------------------------
# Commands: named braid setups
# --------------------------------------------------------------------------


def cmd_setups(options: Options) -> int:
    store = open_store(options.data_dir)
    if not store.setups:
        print(
            "No setups yet, save one with: "
            "braidcord setup save belt --pattern round-8 --slot 1=Crimson"
        )
        print(f"available patterns: {', '.join(PATTERNS) or 'none'}")
        print(f"store: {display_path(store.path)}")
        return 0
    rows: list[tuple[str, str, str, str]] = []
    for setup in store.setups:
        slot_colors = setup["slot_colors"]
        rows.append(
            (
                setup["name"],
                setup["pattern_id"],
                str(len(slot_colors)),
                str(len(set(slot_colors.values()))),
            )
        )
    print(f"Braid setups ({len(rows)} saved)")
    print()
    print(render_table(("name", "pattern", "slots", "colours"), rows))
    print()
    print("hint: view one with: braidcord setup <name>")
    print(f"store: {display_path(store.path)}")
    return 0


def setup_save(store: Store, args: argparse.Namespace) -> int:
    name = str(args.setup_name or "").strip()
    if not name:
        raise CliError(
            "setup save needs a name, for example: "
            "braidcord setup save belt --pattern round-8 --slot 1=Crimson"
        )
    if len(name) > 40:
        raise CliError(f"setup name {name!r} is longer than 40 characters")
    if name.casefold() in RESERVED_SETUP_NAMES:
        raise CliError(f"setup name {name!r} is reserved; pick another name")
    if not args.pattern:
        raise CliError("setup save needs --pattern, for example --pattern round-8")
    if not args.slot:
        raise CliError(
            "setup save needs at least one --slot SLOT=COLOUR, for example --slot 1=Crimson"
        )
    pattern = find_pattern(args.pattern)
    slot_colors = parse_slot_assignments(args.slot, pattern, store)
    existing = next(
        (s for s in store.setups if s["name"].casefold() == name.casefold()), None
    )
    if existing is not None and not args.overwrite:
        raise CliError(
            f"setup {existing['name']!r} already exists; pass --overwrite to replace it"
        )
    timestamp = now_iso()
    record = {
        "name": name,
        "pattern_id": pattern.id,
        "slot_colors": slot_colors,
        "notes": str(args.notes).strip(),
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": timestamp,
    }
    if existing is None:
        store.setups.append(record)
        verb = "saved"
    else:
        existing.update(record)
        verb = "overwrote"
    save_store(store)
    print(
        f"{verb} setup {record['name']} ({pattern.id}, "
        f"{plural(len(slot_colors), 'slot')}, "
        f"{plural(len(set(slot_colors.values())), 'colour')})"
    )
    return 0


def setup_remove(store: Store, name: str) -> int:
    setup = find_setup(store, name)
    store.setups = [s for s in store.setups if s["name"] != setup["name"]]
    save_store(store)
    print(f"deleted setup {setup['name']}")
    return 0


def setup_show(store: Store, args: argparse.Namespace, imperial: bool) -> int:
    setup = find_setup(store, args.setup_action)
    if args.turns is not None and args.length is not None:
        raise CliError("give either --turns or --length, not both")
    turns = parse_positive_int(args.turns, "--turns") if args.turns is not None else None
    target_value = (
        parse_positive_number(args.length, "--length") if turns is None and args.length else None
    )
    target_cm = None if target_value is None else (
        target_value * 2.54 if imperial else target_value
    )
    pattern = PATTERNS.get(setup["pattern_id"])
    slot_colors: dict[str, str] = setup["slot_colors"]
    resolved: dict[int, dict[str, Any]] = {}
    missing: list[str] = []
    for slot_text, color_id in sorted(slot_colors.items(), key=lambda item: int(item[0])):
        slot = int(slot_text)
        color = find_color(store, color_id)
        if color is None:
            missing.append(f"slot {slot} references colour id {color_id}, which is not in the ledger")
        else:
            resolved[slot] = color

    print(f"setup    {setup['name']}")
    if pattern is None:
        print(
            f"pattern  {setup['pattern_id']} (not in the catalogue; showing the saved slots only)"
        )
    else:
        print(f"pattern  {setup['pattern_id']}  {pattern.name}")
    print(
        f"         {plural(len(slot_colors), 'slot')}, "
        f"{plural(len(set(slot_colors.values())), 'colour')}"
    )
    if setup["notes"]:
        print(f"notes    {setup['notes']}")
    for problem in missing:
        print(f"warning  {problem}")

    print()
    print("Disk slot map (32 slots, slot 1 at the top, numbered clockwise)")
    print()
    label_width = 10
    labels: dict[int, str] = {}
    for slot, color in resolved.items():
        name = color["name"]
        labels[slot] = name if len(name) <= label_width else name[: label_width - 1] + "."
    print(render_disk_grid(labels, empty="."))

    if resolved:
        print()
        print("Slot colours")
        rows = [
            (str(slot), color["name"], color["hex"] or "-", color["brand"] or "-")
            for slot, color in sorted(resolved.items())
        ]
        print(render_table(("slot", "colour", "hex", "brand"), rows))

    if pattern is not None:
        print()
        print(f"Turn sequence ({len(pattern.moves)} moves, worked in this order)")
        for index, (from_slot, to_slot) in enumerate(pattern.moves, start=1):
            print(f" {index:2d}. slot {from_slot:2d} to slot {to_slot:2d}")
        print()
        print(f"basis    {basis_line(pattern, imperial)}")

    estimate = _setup_estimate_line(pattern, imperial, turns, target_cm)
    if estimate:
        print()
        print(f"estimate {estimate}")
    return 0


def _setup_estimate_line(
    pattern: Pattern | None,
    imperial: bool,
    turns: int | None,
    target_cm: float | None,
) -> str:
    if turns is None and target_cm is None:
        return ""
    if pattern is None:
        raise CliError("cannot estimate: this setup's pattern is not in the catalogue")
    return estimate_line(pattern, imperial, turns=turns, target_cm=target_cm)


# --------------------------------------------------------------------------
# Command line surface
# --------------------------------------------------------------------------

HELP_EPILOG = """\
commands
  patterns                     list the built-in braid patterns
  pattern <pattern_id>         32-slot disk map, turn sequence and estimator basis
  colors                       list the thread colour ledger
  colors add <name>            add a colour (--hex, --brand, --notes optional)
  colors rm <id>               remove a colour by id (refused while a setup uses it)
  setups                       list the saved braid setups
  setup <name>                 one setup as a colour-labelled disk map (--turns/--length)
  setup save <name>            save a setup (--pattern, repeated --slot SLOT=COLOUR, --overwrite)
  setup rm <name>              delete a saved setup
  estimate                     finished length from turns, or turns for a target length

examples
  python3 braidcord.py patterns
  python3 braidcord.py pattern round-8
  python3 braidcord.py colors add Crimson --hex B3122E --brand Silk
  python3 braidcord.py colors
  python3 braidcord.py setup save belt --pattern round-8 --slot 1=Crimson --slot 5=Navy ...
  python3 braidcord.py setup belt --turns 40
  python3 braidcord.py setup rm belt
  python3 braidcord.py estimate --pattern round-8 --turns 40 --imperial
  python3 braidcord.py estimate --pattern round-8 --length 60

store
  ~/.braidcord/braidcord.json   (override with --data-dir DIR or BRAIDCORD_DATA_DIR)
"""


class UsageError(CliError):
    """A bad command line: printed with the usage line and exit code 2."""


class BraidCordParser(argparse.ArgumentParser):
    """Argument parser that turns its own errors into one-line failures."""

    def error(self, message: str) -> None:  # noqa: D401 - argparse hook
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = BraidCordParser(
        prog="braidcord",
        description=(
            "Kumihimo braid reference by disk slot, thread colour ledger and "
            "finished-length estimator. Standard library only, no network."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        metavar="DIR",
        default=None,
        help="directory holding braidcord.json (default: ~/.braidcord)",
    )
    parser.add_argument(
        "--imperial",
        action="store_true",
        help="report lengths in inches as whole inches plus eighths (default: centimetres)",
    )
    parser.add_argument(
        "--version", action="version", version=f"braidcord {VERSION}"
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("patterns", help="list the built-in braid patterns")

    pattern_parser = sub.add_parser(
        "pattern", help="show one pattern as a disk map, turn sequence and basis"
    )
    pattern_parser.add_argument("pattern_id", metavar="pattern_id", help="e.g. round-8")

    colors_parser = sub.add_parser("colors", help="list the thread colour ledger")
    colors_sub = colors_parser.add_subparsers(dest="colors_command", metavar="<action>")
    colors_add = colors_sub.add_parser("add", help="add a thread colour")
    colors_add.add_argument("name", help="colour name, e.g. Crimson")
    colors_add.add_argument("--hex", dest="hex_value", metavar="RRGGBB", default="")
    colors_add.add_argument("--brand", default="", metavar="NAME")
    colors_add.add_argument("--notes", default="", metavar="TEXT")
    colors_remove = colors_sub.add_parser("rm", help="remove a colour by id")
    colors_remove.add_argument("color_id", metavar="color_id")

    sub.add_parser("setups", help="list the saved braid setups")

    setup_parser = sub.add_parser(
        "setup", help="show, save or delete a named braid setup"
    )
    setup_parser.add_argument(
        "setup_action",
        nargs="?",
        metavar="<name|save|rm>",
        help="a setup name to view, or 'save' / 'rm'",
    )
    setup_parser.add_argument("setup_name", nargs="?", metavar="name", help=argparse.SUPPRESS)
    setup_parser.add_argument("--pattern", metavar="ID", default=None)
    setup_parser.add_argument(
        "--slot",
        action="append",
        default=[],
        metavar="SLOT=COLOUR",
        help="assign a ledger colour to a disk slot (repeat per slot)",
    )
    setup_parser.add_argument("--notes", default="", metavar="TEXT")
    setup_parser.add_argument(
        "--overwrite", action="store_true", help="replace an existing setup of the same name"
    )
    setup_parser.add_argument("--turns", metavar="N", default=None)
    setup_parser.add_argument("--length", metavar="LENGTH", default=None)

    estimate_parser = sub.add_parser(
        "estimate", help="finished length from turns, or turns for a target length"
    )
    estimate_parser.add_argument("--pattern", metavar="ID", default=None)
    estimate_parser.add_argument("--turns", metavar="N", default=None)
    estimate_parser.add_argument(
        "--length", metavar="LENGTH", default=None, help="target length (cm, or inches with --imperial)"
    )
    return parser

# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def split_global_args(argv: Sequence[str]) -> tuple[dict[str, Any], list[str]]:
    """Pull --data-dir/--imperial out of argv so they work after a subcommand."""
    settings: dict[str, Any] = {"data_dir": None, "imperial": False}
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            remaining.extend(argv[index:])
            break
        if argument == "--imperial":
            settings["imperial"] = True
        elif argument == "--data-dir":
            if index + 1 >= len(argv):
                raise UsageError("--data-dir needs a directory, e.g. --data-dir ./braidcord-data")
            settings["data_dir"] = argv[index + 1]
            index += 1
        elif argument.startswith("--data-dir="):
            value = argument.split("=", 1)[1]
            if not value:
                raise UsageError("--data-dir needs a directory, e.g. --data-dir ./braidcord-data")
            settings["data_dir"] = value
        else:
            remaining.append(argument)
        index += 1
    return settings, remaining


def cmd_setup(options: Options, args: argparse.Namespace) -> int:
    store = open_store(options.data_dir)
    action = args.setup_action
    if action is None:
        raise UsageError(
            "setup needs a name, 'save' or 'rm', e.g. braidcord setup belt "
            "or braidcord setup save belt --pattern round-8 --slot 1=Crimson"
        )
    if action == "save":
        return setup_save(store, args)
    if action == "rm":
        if not args.setup_name:
            raise UsageError("setup rm needs a name, e.g. braidcord setup rm belt")
        return setup_remove(store, args.setup_name)
    return setup_show(store, args, options.imperial)


def dispatch(parser: argparse.ArgumentParser, args: argparse.Namespace, options: Options) -> int:
    command = args.command
    if command is None:
        parser.print_help()
        return 0
    if command == "patterns":
        return cmd_patterns(options)
    if command == "pattern":
        return cmd_pattern(options, args.pattern_id)
    if command == "colors":
        return cmd_colors(options, args)
    if command == "setups":
        return cmd_setups(options)
    if command == "setup":
        return cmd_setup(options, args)
    if command == "estimate":
        return cmd_estimate(options, args)
    raise UsageError(f"unknown command {command!r}")


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        settings, remaining = split_global_args(raw_args)
        options = Options(
            data_dir=resolve_data_dir(settings["data_dir"]),
            imperial=bool(settings["imperial"]),
        )
        parser = build_parser()
        args = parser.parse_args(remaining)
        return dispatch(parser, args, options)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(USAGE_LINE, file=sys.stderr)
        return 2
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # last resort: never show a traceback to the braider
        if os.environ.get("BRAIDCORD_DEBUG"):
            raise
        print(f"error: internal failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        print("hint: re-run with BRAIDCORD_DEBUG=1 for the full traceback", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
