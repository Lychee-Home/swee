import re

OPTION_SETTINGS_RE = re.compile(r'OptionSettings=\((.*)\)\s*$')

REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}


def _parse_option_settings(text):
    """Split the inner content of OptionSettings=(...) into a {key: value} dict.

    Values are either bare tokens (numbers, enum names, True/False) or double-quoted
    strings that may contain commas (e.g. ServerDescription="Hello, world") — a plain
    comma-split would break on those, so this scans char-by-char instead.
    """
    pairs = {}
    i, n = 0, len(text)
    while i < n:
        eq = text.index('=', i)
        key = text[i:eq]
        i = eq + 1
        if i < n and text[i] == '"':
            end = text.index('"', i + 1)
            value = text[i:end + 1]
            i = end + 1
            if i < n and text[i] == ',':
                i += 1
        else:
            comma = text.find(',', i)
            if comma == -1:
                value = text[i:]
                i = n
            else:
                value = text[i:comma]
                i = comma + 1
        pairs[key] = value
    return pairs


def parse_palworld_settings(path):
    with open(path) as f:
        content = f.read()
    m = OPTION_SETTINGS_RE.search(content)
    if not m:
        raise ValueError(f"no OptionSettings line found in {path}")
    return _parse_option_settings(m.group(1))


def diff_palworld_settings(old, new):
    changes = []
    for key in sorted(set(old) | set(new)):
        old_val, new_val = old.get(key), new.get(key)
        if old_val != new_val:
            changes.append((key, old_val, new_val))
    return changes


def render_option_settings(pairs):
    return ",".join(f"{k}={v}" for k, v in pairs.items())


def write_palworld_setting(path, key, formatted_value):
    with open(path) as f:
        content = f.read()
    m = OPTION_SETTINGS_RE.search(content)
    if not m:
        raise ValueError(f"no OptionSettings line found in {path}")
    pairs = _parse_option_settings(m.group(1))
    pairs[key] = formatted_value
    new_inner = render_option_settings(pairs)
    new_content = content[:m.start(1)] + new_inner + content[m.end(1):]
    with open(path, "w") as f:
        f.write(new_content)


def visible_settings(path):
    return {k: v for k, v in parse_palworld_settings(path).items() if k not in REDACTED_SETTINGS_KEYS}


def format_settings_change_fields(changes):
    fields = []
    # If more than 25 changes, only show 24 to leave room for the summary field
    display_limit = 24 if len(changes) > 25 else len(changes)

    for key, old_val, new_val in changes[:display_limit]:
        if key in REDACTED_SETTINGS_KEYS:
            display = "(changed)"
        else:
            display = f"{old_val if old_val is not None else '—'} → {new_val if new_val is not None else '—'}"
        fields.append((key, display))
    if len(changes) > 25:
        fields.append(("…", f"+{len(changes) - 24} more changed (see server config)"))
    return fields
