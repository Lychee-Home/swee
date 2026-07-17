# CPU Usage in Stats Embed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "System CPU" field to the stats embed, showing system-wide CPU usage as a percentage.

**Architecture:** New `swee/cpu.py` module mirrors `swee/ram.py`'s pattern (a pure, testable
calculation function plus a thin I/O wrapper). `swee/embeds.py`'s `build_stats_embed` gets one
new field, wrapped in its own try/except so a CPU read failure never breaks the rest of the
embed.

**Tech Stack:** Python 3.14, stdlib only (`/proc/stat` parsing, `time.sleep`), `unittest` for
tests (matches `tests/test_palworld_settings.py`).

## Global Constraints

- System-wide CPU only — no per-process (Palworld-specific) breakdown. See
  `docs/superpowers/specs/2026-07-16-cpu-usage-design.md`.
- Display-only — no auto-restart-on-CPU-threshold behavior.
- Follow the existing one-module-per-concern pattern (CLAUDE.md).
- A CPU read failure must not prevent the rest of the stats embed from rendering (matches how
  the RAM field is already isolated with its own try/except in `build_stats_embed`).

---

### Task 1: `swee/cpu.py` — pure calculation + tests

**Files:**
- Create: `swee/cpu.py`
- Test: `tests/test_cpu.py`

**Interfaces:**
- Produces: `compute_cpu_pct(line1: str, line2: str) -> int` — pure function, takes two raw
  `/proc/stat` aggregate `cpu` lines sampled apart in time, returns busy percentage (0-100,
  rounded to nearest int).
- Produces: `read_cpu_stats() -> int` — reads `/proc/stat` twice, ~100ms apart, returns
  `compute_cpu_pct(...)` result. Used by Task 2.
- Produces: `get_cpu_usage() -> str` — formats `read_cpu_stats()` as e.g. `"12%"`. Used by
  Task 2.

The `/proc/stat` aggregate line looks like:
```
cpu  1234 56 789 100000 234 0 12 0 0 0
```
Fields after `cpu` are, in order: `user nice system idle iowait irq softirq steal guest
guest_nice`. Idle time is `idle + iowait` (index 3 and 4, 0-based after the label). Total time
is the sum of all fields. Busy percentage between two samples is:
```
idle_delta = idle2 - idle1
total_delta = total2 - total1
busy_pct = (1 - idle_delta / total_delta) * 100
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cpu.py`:

```python
import unittest

from swee.cpu import compute_cpu_pct


class ComputeCpuPctTests(unittest.TestCase):
    def test_fully_idle_between_samples(self):
        # idle grows by exactly the same amount as total -> 0% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  0 0 0 2000 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)

    def test_fully_busy_between_samples(self):
        # user time grows, idle stays flat -> 100% busy
        line1 = "cpu  1000 0 0 5000 0 0 0 0 0 0"
        line2 = "cpu  2000 0 0 5000 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 100)

    def test_partial_busy_between_samples(self):
        # total grows by 1000, idle grows by 250 -> 75% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  750 0 0 1250 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 75)

    def test_iowait_counts_as_idle(self):
        # all growth is iowait (index 4) -> counts as idle, 0% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  0 0 0 1000 500 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)

    def test_zero_total_delta_returns_zero(self):
        # identical samples (e.g. clock hasn't ticked) -> avoid division by zero
        line1 = "cpu  100 0 0 900 0 0 0 0 0 0"
        line2 = "cpu  100 0 0 900 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_cpu -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'swee.cpu'` (or `ImportError`)

- [ ] **Step 3: Write the implementation**

Create `swee/cpu.py`:

```python
import time


def _parse_cpu_line(line):
    # Aggregate "cpu" line: user nice system idle iowait irq softirq steal guest guest_nice
    values = [int(v) for v in line.split()[1:]]
    idle = values[3] + values[4]  # idle + iowait
    total = sum(values)
    return idle, total


def compute_cpu_pct(line1, line2):
    idle1, total1 = _parse_cpu_line(line1)
    idle2, total2 = _parse_cpu_line(line2)
    idle_delta = idle2 - idle1
    total_delta = total2 - total1
    if total_delta <= 0:
        return 0
    return round((1 - idle_delta / total_delta) * 100)


def _read_cpu_line():
    with open("/proc/stat") as f:
        return f.readline()


def read_cpu_stats():
    # CPU usage is a rate, not a level (unlike RAM in swee/ram.py), so it needs
    # two samples spaced apart rather than a single instantaneous read.
    line1 = _read_cpu_line()
    time.sleep(0.1)
    line2 = _read_cpu_line()
    return compute_cpu_pct(line1, line2)


def get_cpu_usage():
    return f"{read_cpu_stats()}%"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_cpu -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add swee/cpu.py tests/test_cpu.py
git commit -m "feat: add system CPU usage calculation"
```

---

### Task 2: Wire CPU usage into the stats embed

**Files:**
- Modify: `swee/embeds.py:1-11` (imports), `swee/embeds.py:75-84` (`build_stats_embed`)

**Interfaces:**
- Consumes: `get_cpu_usage() -> str` from Task 1 (`swee/cpu.py`).

Current `swee/embeds.py:75-84`:

```python
def build_stats_embed(info, metrics, players, offline_entries):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics, players, offline_entries)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed
```

- [ ] **Step 1: Add the import**

In `swee/embeds.py`, change line 9 from:

```python
from swee.ram import get_ram_usage
```

to:

```python
from swee.cpu import get_cpu_usage
from swee.ram import get_ram_usage
```

- [ ] **Step 2: Add the CPU field**

Change `build_stats_embed` (lines 75-84) to:

```python
def build_stats_embed(info, metrics, players, offline_entries):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics, players, offline_entries)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    try:
        embed.add_field(name="System CPU", value=get_cpu_usage())
    except Exception:
        log.exception("CPU read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed
```

- [ ] **Step 3: Run the full test suite**

Run: `python -m unittest discover tests -v`
Expected: all tests PASS (existing `test_palworld_settings` tests plus the new `test_cpu` tests)

- [ ] **Step 4: Manual smoke check (this module isn't covered by the Discord command test
  harness — there isn't one, per CLAUDE.md)**

Run: `python -c "from swee.cpu import get_cpu_usage; print(get_cpu_usage())"`
Expected: prints something like `7%` (a number 0-100 followed by `%`), with roughly a 100ms
pause before it prints. This confirms the module works standalone; the bot itself should only be
run/verified per the project's normal deployment flow (this repo doesn't run on Windows — see
CLAUDE.md — so the embed itself can't be exercised locally on this machine).

- [ ] **Step 5: Commit**

```bash
git add swee/embeds.py
git commit -m "feat: show system CPU usage in the stats embed"
```

---

## Self-Review Notes

- **Spec coverage:** System-wide-only ✓ (Task 1 reads `/proc/stat` aggregate line, not
  per-process). Display-only, no auto-restart ✓ (no changes to `swee/stats.py` or `RAM_RESTART_*`
  config). Failure isolation ✓ (Task 2's try/except mirrors the RAM field exactly).
- **Placeholder scan:** none found — all steps have complete code.
- **Type consistency:** `compute_cpu_pct(line1: str, line2: str) -> int`,
  `read_cpu_stats() -> int`, `get_cpu_usage() -> str` are used consistently between Task 1's
  production and Task 2's consumption.
