"""Versioned, JSON-only canonical serialization for this runtime profile."""
import hashlib
import json
import math

PROFILE = 'mg8-runtime-json/1'


def _check(value, depth=0):
    if depth > 64:
        raise ValueError('JSON nesting exceeds 64 levels')
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        if abs(value) >= 2 ** 256:
            raise ValueError('integer exceeds profile bound')
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('non-finite number')
        return
    if type(value) is list:
        for item in value:
            _check(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _check(item, depth + 1)
        return
    raise ValueError('only JSON values with string object keys are supported')


def dumps(value):
    _check(value)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 4_000_000:
        raise ValueError('JSON document exceeds 4 MB')
    return encoded


def digest(value):
    return hashlib.sha256((PROFILE + '\n' + dumps(value)).encode('utf-8')).hexdigest()


def clone(value):
    return json.loads(dumps(value))
