# Incremental Index Recovery Tests

Tests for the incremental index recovery feature (`ltfsck -x`).

## Directory Structure

```
tests/inc-index/
├── README.md
├── run_all.sh               Run all scenarios (parallel by default)
└── scenario1/               Scenario 1: Foundation
    ├── gen.sh               Generate test data (requires FUSE)
    ├── run.sh               Run recovery and verify result
    ├── clean.sh             Remove all generated test data
    └── .gitignore           Excludes tape/, tape-crashed/, expected/
```

Each scenario directory is self-contained.  Generated test data is gitignored
and must be created locally before running tests.

## Prerequisites

- Project built and installed under `/workspaces/ltfs-oss`:
  ```bash
  ./autogen.sh && ./configure --prefix=/workspaces/ltfs-oss
  make && make install
  ```
- FUSE available (`/dev/fuse`) and `attr` package installed (for `gen.sh` only)

## Quick Start

```bash
cd tests/inc-index

# Generate test data and run all scenarios
bash run_all.sh --gen

# Run all scenarios without regenerating (parallel)
bash run_all.sh

# Clean all generated data
bash run_all.sh --clean
```

## Running a Single Scenario

```bash
cd tests/inc-index/scenario1

# Generate test data
bash gen.sh

# Run recovery and verify
bash run.sh

# Clean generated data
bash clean.sh
```

`run.sh` also accepts `--gen` and `--clean` as shortcuts:

```bash
bash run.sh --gen    # gen.sh + run
bash run.sh --clean  # same as clean.sh
```

## Scenarios

### Scenario 1: Foundation

Covers the basic incremental index operations against a single full index.

| Case | Description                             |
|------|-----------------------------------------|
| L01  | File unchanged after full index         |
| L02  | File modified after full index          |
| L03  | File deleted after full index           |
| L06  | New file created after full index       |
| D02  | New directory created after full index  |
| D03  | Directory (with child) deleted          |

**Crash state**: system crashed after `IncrementalSync` but before clean unmount.

**Expected filesystem after recovery**:

| Path                 | State              |
|----------------------|--------------------|
| `/baseline.txt`      | present, unchanged |
| `/modify_me.txt`     | present, modified  |
| `/delete_me.txt`     | deleted            |
| `/new_dir/`          | present (new)      |
| `/new_dir/child.txt` | present (new)      |
| `/old_dir/`          | deleted            |

## Adding a New Scenario

1. Create `tests/inc-index/scenarioN/`
2. Add `gen.sh`, `run.sh`, `clean.sh`, `.gitignore` following the same
   conventions as `scenario1/`
3. `run_all.sh` will automatically discover and run it

Key conventions:
- Mount point: `/tmp/ltfs-mnt-scenarioN` (unique per scenario for parallel runs)
- Generated directories: `tape/`, `tape-crashed/`, `expected/`
- `run.sh` exits 0 on PASS, 1 on FAIL, 2 on setup error
