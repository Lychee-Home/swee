import os
import re
import tempfile

OPTION_SETTINGS_RE = re.compile(r'OptionSettings=\((.*)\)\s*$')

REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}

NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')


def _parse_option_settings(text):
    """Split the inner content of OptionSettings=(...) into a {key: value} dict.

    Values are bare tokens (numbers, enum names, True/False), double-quoted strings
    that may contain commas (e.g. ServerDescription="Hello, world"), or parenthesized
    lists that may contain commas (e.g. CrossplayPlatforms=(Steam,Xbox,PS5,Mac)) — a
    plain comma-split would break on either, so this scans char-by-char instead.
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
        elif i < n and text[i] == '(':
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if text[j] == '(':
                    depth += 1
                elif text[j] == ')':
                    depth -= 1
                j += 1
            value = text[i:j]
            i = j
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

    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(new_content)
        try:
            original_stat = os.stat(path)
            os.chmod(tmp_path, original_stat.st_mode)
            os.chown(tmp_path, original_stat.st_uid, original_stat.st_gid)
        except (OSError, AttributeError):
            pass  # os.chown doesn't exist on Windows; permission mismatch is non-fatal elsewhere
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def visible_settings(path):
    return {k: v for k, v in parse_palworld_settings(path).items() if k not in REDACTED_SETTINGS_KEYS}


def classify_value(value):
    if value in ("True", "False"):
        return "bool"
    if NUMBER_RE.match(value):
        return "number"
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return "string"
    if len(value) >= 2 and value.startswith('(') and value.endswith(')'):
        return "list"
    return "token"


def format_new_value(current_value, raw_input):
    category = classify_value(current_value)
    stripped = raw_input.strip()

    if category == "bool":
        lowered = stripped.lower()
        if lowered not in ("true", "false"):
            raise ValueError(f'`{current_value}` is a True/False setting — got {raw_input!r}')
        return "True" if lowered == "true" else "False"

    if category == "number":
        if not NUMBER_RE.match(stripped):
            raise ValueError(f"`{current_value}` is a numeric setting — got {raw_input!r}")
        return stripped

    if category == "string":
        if '\n' in raw_input or '\r' in raw_input:
            raise ValueError('value cannot contain a newline or carriage return')
        if '"' in raw_input:
            raise ValueError('value cannot contain a literal `"` character')
        return f'"{raw_input}"'

    if category == "list":
        if '\n' in raw_input or '\r' in raw_input:
            raise ValueError('value cannot contain a newline or carriage return')
        if any(c in raw_input for c in '"()'):
            raise ValueError(
                f"expected a comma-separated list with no quotes or parens — got {raw_input!r}"
            )
        return f"({raw_input})"

    # token
    if '\n' in raw_input or '\r' in raw_input:
        raise ValueError('value cannot contain a newline or carriage return')
    if any(c in raw_input for c in ' ,"()'):
        raise ValueError(
            f"expected a plain value with no spaces, commas, quotes, or parens — got {raw_input!r}"
        )
    return raw_input


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
