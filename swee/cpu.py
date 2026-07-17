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
