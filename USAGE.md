# Using BraidCord

Five walkthroughs, one per feature. All commands assume you are in the project
directory; add `--data-dir ./demo-data` to any of them to play against the demo
store instead of `~/.braidcord`.

## 1. Look up a braid pattern by disk slot

```bash
python3 braidcord.py patterns
```

The table lists every built-in structure with its id, bobbin count and advance
per turn. Then open one:

```bash
python3 braidcord.py pattern round-8
```

```
pattern  round-8  Kongo round
         Hollow round cord, the standard first braid on a disk.
         8 bobbins on slots 1, 5, 9, 13, 17, 21, 25, 29

Disk slot map (32 slots, slot 1 at the top, numbered clockwise)

+-----+-----+-----+-----+-----+-----+-----+-----+
|  1  |  .  |  .  |  .  |  5  |  .  |  .  |  .  |   slots 1-8
...
```

* Used slots show their slot number; every unused slot is a dot.
* The numbered list under the map is one turn, in the order the moves are
  worked: `1. slot  1 to slot  3`.
* The footer prints the advance per turn and the take-up factor, so the
  estimator's number is auditable.

Built-in ids: `round-8`, `square-8`, `spiral-8`, `flat-16`, `kongo-4`.

## 2. Keep a thread colour ledger

```bash
python3 braidcord.py colors add Crimson --hex B3122E --brand Silk
python3 braidcord.py colors add Navy --hex 1B2A4A --notes "waxed linen"
python3 braidcord.py colors
```

```
Colour ledger (2 threads)

id            name     hex     brand
------------  -------  ------  -----
crimson-3f2a  Crimson  B3122E  Silk
navy-81b0     Navy     1B2A4A  -
```

The id in the first column is what `colors rm` takes (a name works too). A
colour used by a saved setup cannot be removed - BraidCord names the setups
instead of leaving a setup pointing at nothing:

```
$ python3 braidcord.py colors rm crimson-3f2a
error: colour Crimson (crimson-3f2a) is used by setup belt; re-save or delete those setups first
```

Naming a colour twice (in any case) is refused, and the existing entry is named.

## 3. Save a named braid setup

```bash
python3 braidcord.py setup save belt --pattern round-8 \
  --slot 1=Crimson --slot 5=Navy --slot 9=Gold --slot 13=Slate \
  --slot 17=Crimson --slot 21=Gold --slot 25=Slate --slot 29=Navy
```

```
saved setup belt (round-8, 8 slots, 4 colours)
```

* One `--slot SLOT=COLOUR` per slot the pattern uses. A missing slot, a slot the
  pattern does not use, a slot outside 1-32, or a colour missing from the ledger
  is refused by name and nothing is written.
* `--overwrite` replaces an existing setup of the same name; without it the save
  is refused and the original is untouched.
* List and delete:

```bash
python3 braidcord.py setups
python3 braidcord.py setup rm belt
```

## 4. View a setup as a coloured slot map

```bash
python3 braidcord.py setup belt
```

The 32-slot map labels each assigned slot with its ledger colour name, followed
by a slot/colour/hex table, the pattern's turn sequence, and the estimator
basis. If a saved colour has since disappeared from the ledger, the map still
renders and a `warning` line names the missing reference.

Add an estimate inline:

```bash
python3 braidcord.py setup belt --turns 40
python3 braidcord.py setup belt --turns 40 --imperial
python3 braidcord.py setup belt --length 18 --imperial
```

## 5. Estimate a finished length

```bash
python3 braidcord.py estimate --pattern round-8 --turns 40
```

```
estimate  pattern round-8 (Kongo round, 8 bobbins)
basis     0.4500 cm/turn advance x 1.12 take-up = 0.5040 cm/turn
turns     40
finished  20.2 cm
```

* `--imperial` swaps the answer for whole inches plus reduced eighths
  (`7 7/8 in`) and shows the basis in inches per turn as well.
* Work backwards from a target length with `--length` (centimetres, or inches
  with `--imperial`); the turn count always rounds up:

```
$ python3 braidcord.py estimate --pattern round-8 --length 60
estimate  pattern round-8 (Kongo round, 8 bobbins)
basis     0.4500 cm/turn advance x 1.12 take-up = 0.5040 cm/turn
target    60.0 cm
turns     120 (rounded up from 119.05)
```

* `--turns 0`, `--turns abc`, `--length -2` and an unknown `--pattern` each print
  one `error:` line and exit 2. Running `estimate` with no arguments prints the
  two usage forms instead of a number.

## 6. Where the data lives

```
~/.braidcord/braidcord.json
```

Override with `--data-dir DIR` (created if missing) or the `BRAIDCORD_DATA_DIR`
environment variable. The file is written through a temp file and renamed, has a
`schema_version` of 1, and a damaged file is moved to `braidcord.json.bak` with a
single warning while a fresh store takes its place.

## Command to endpoint map

BraidCord has no HTTP surface. The plan's conceptual endpoints map to commands:

| Conceptual endpoint | Command |
| --- | --- |
| `GET /cli/help` | `braidcord --help` |
| `GET /cli/patterns` | `braidcord patterns` |
| `GET /cli/patterns/{id}` | `braidcord pattern <id>` |
| `GET /cli/colors` | `braidcord colors` |
| `POST /cli/colors` | `braidcord colors add <name>` |
| `DELETE /cli/colors/{id}` | `braidcord colors rm <id>` |
| `GET /cli/setups` | `braidcord setups` |
| `POST /cli/setups` | `braidcord setup save <name> ...` |
| `GET /cli/setups/{name}` | `braidcord setup <name>` |
| `DELETE /cli/setups/{name}` | `braidcord setup rm <name>` |
| `GET /cli/setups/{name}/estimate` | `braidcord setup <name> --turns N` |
| `GET /cli/estimate` | `braidcord estimate --pattern <id> --turns N` |
