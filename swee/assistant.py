import re

MENTION_RE = re.compile(r'^@swee\b\s*(.*)', re.IGNORECASE)


def parse_mention(chat_text):
    m = MENTION_RE.match(chat_text.strip())
    if not m:
        return None
    question = m.group(1).strip()
    return question or None


def is_on_cooldown(name, last_answered, cooldown_sec, now):
    last = last_answered.get(name)
    return last is not None and now - last < cooldown_sec


def record_answered(name, last_answered, now):
    last_answered[name] = now
