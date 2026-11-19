# Installing and running BraidCord

BraidCord is a single standard-library Python file. There is no package to
download, no database to provision and no service to start.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.9 or newer (`python3`) | System interpreter is fine; no virtualenv needed |
| A writable home directory *or* `--data-dir` | Holds `~/.braidcord/braidcord.json` |

Nothing is installed with `apt`, `brew` or any other system package manager, and
no third-party Python packages are used.

## Step 1 - install (checks the toolchain, installs nothing)

```bash
cd braidcord
bash install.sh
```

`install.sh` verifies the Python version, compiles `braidcord.py`, imports it,
and runs a throw-away smoke test in a temp directory. It **exits** when done; it
never starts anything in the foreground. It is safe to re-run.

If `requirements.txt` ever gains a real dependency the script installs it with
`python3 -m pip install -r requirements.txt`; today the file is comments only.

## Step 2 - seed the demo store (optional, one command)

```bash
bash demo.sh
```

This creates `./demo-data/braidcord.json` with a five-colour ledger and three
saved setups, then prints every command's output so you can see the whole tool
in one screen. It removes and recreates `./demo-data` each run, so it is
idempotent. Your real store at `~/.braidcord` is never touched.

## Step 3 - run it

There is no server; you invoke the tool:

```bash
python3 braidcord.py --help
python3 braidcord.py patterns
python3 braidcord.py --data-dir ./demo-data setups
```

Use `--data-dir ./demo-data` to look at the demo store, and no flag to work with
your own ledger at `~/.braidcord/braidcord.json`.

## Step 4 - run the tests

```bash
python3 -m unittest discover -s tests -t .
# or, if pytest is available:
python3 -m pytest
```

Both commands must exit 0. The suite needs no network and no fixtures beyond the
temporary directories it creates itself.

## Uninstalling

Delete the file and the store: `rm braidcord.py` and `rm -r ~/.braidcord`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `error: cannot write the store at ...` | The data directory is not writable; pass `--data-dir ./braidcord-data` |
| `warning: ... is unreadable (...)` | The JSON store was damaged; it is kept as `braidcord.json.bak` and a fresh store was created |
| `error: unknown colour 'X'; ledger colours: ...` | Add the colour first: `python3 braidcord.py colors add X` |
| `error: pattern round-8 uses 8 slots; slots ... still need a colour` | `setup save` needs one `--slot SLOT=COLOUR` per used slot |
