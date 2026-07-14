def read_ram_stats():
    # Bot runs on the same box as the game server, so read system memory
    # directly rather than via Palworld's REST API (which doesn't expose it).
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])  # kB
    total_kb = meminfo["MemTotal"]
    available_kb = meminfo["MemAvailable"]
    used_gb = (total_kb - available_kb) / 1_048_576
    total_gb = total_kb / 1_048_576
    pct = round((used_gb / total_gb) * 100)
    return used_gb, total_gb, pct


def get_ram_usage():
    used_gb, total_gb, pct = read_ram_stats()
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"


def should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min):
    if threshold_pct is None:
        return False
    if pct < threshold_pct:
        return False
    if last_restart_monotonic is None:
        return True
    return now_monotonic - last_restart_monotonic >= cooldown_min * 60
