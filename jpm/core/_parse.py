import re

# Supports key:"value" format with \" escaping for literal quotes.
# Falls back to key:value (no quotes) for backward compatibility.
_PARSE_KV_RE = re.compile(r'(\w+):"((?:[^"\\]|\\.)*)"|(\w+):(\S+)')


def parse_kv(text: str) -> dict:
    pairs = _PARSE_KV_RE.findall(text)
    result = {}
    for k_quoted, v_quoted, k_unquoted, v_unquoted in pairs:
        if k_quoted:
            val = v_quoted.replace('\\"', '"').replace('\\\\', '\\')
            result[k_quoted] = val
        elif k_unquoted:
            result[k_unquoted] = v_unquoted.strip()
    return result