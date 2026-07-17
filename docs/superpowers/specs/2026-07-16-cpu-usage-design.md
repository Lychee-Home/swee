# CPU usage in stats embed — design

## Problem

The stats embed shows system RAM usage (`swee/ram.py`) but nothing about CPU. There's no
visibility into how loaded the box is from CPU alone.

## Decision

Show **system-wide total CPU usage**, not Palworld-process-specific usage.

Rationale: the box is dedicated to running the Palworld server, so system-wide is a good proxy
for "is the game struggling" without the extra complexity of locating the Palworld PID and
computing per-process CPU deltas. This mirrors the existing RAM field, which is also
system-wide (`/proc/meminfo`), not per-process.

Explicitly out of scope: no auto-restart-on-CPU-threshold. RAM has
`RAM_RESTART_THRESHOLD_PCT`/cooldown/warning logic in `swee/stats.py`; CPU gets none of that.
This is display-only.

## Design

New module `swee/cpu.py`, following the same one-concern-per-module pattern as `swee/ram.py`:

- `read_cpu_stats()` — reads the aggregate `cpu` line from `/proc/stat`, takes two samples
  ~100ms apart, and computes busy percentage as `(1 - idle_delta / total_delta) * 100`. Unlike
  RAM (an instantaneous level, single read of `/proc/meminfo`), CPU usage is a rate and requires
  a delta between two samples.
- `get_cpu_usage()` — formats the result as a string (e.g. `"12%"`), matching
  `get_ram_usage()`'s return-a-formatted-string convention.

In `swee/embeds.py`: add a `"System CPU"` field to `build_stats_embed`, next to `"System RAM"`,
wrapped in the same try/except-log pattern already used for the RAM field so a CPU read failure
doesn't break the whole embed.

## Cost / trade-offs

The two-sample read introduces a ~100ms blocking delay inside `update_stats_message`, which runs
on a 1-minute ticker plus on join/leave events. Negligible at that frequency.

## Non-goals

- No per-process (Palworld-specific) CPU breakdown.
- No auto-restart-on-CPU-threshold behavior.
