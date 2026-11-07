"""
rules.py — "which rows does this campaign want?"

A rule set has three blocks. All three are optional; an empty rule set matches everything.

    {"all":  [...],   every clause must pass
     "any":  [...],   at least one must pass
     "none": [...]}   none may pass

One clause is {"field": ..., "op": ..., "value": ...}. `field` may be an engine field
name ("employees") or a raw sheet header ("Trading Years") — see FieldMap.resolve.

Numbers: a cell may hold a range ("11-50"). Every numeric operator uses the LARGEST
number found in the cell, which is the same rule `instantly.size_band` already applies,
so "11-50" is treated as 50 and never lands in a 2-10 band by accident.

Everything here is pure. It never touches the network and never spends a credit, which
is what makes the free plan preview possible.
"""
from __future__ import annotations

import re
from datetime import datetime


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _lower(v) -> str:
    return _s(v).lower()


def _nums(v) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", _s(v).replace(",", ""))]


def _num(v):
    """The representative number in a cell: the largest one, or None."""
    ns = _nums(v)
    return max(ns) if ns else None


def _list(v) -> list[str]:
    if isinstance(v, (list, tuple, set)):
        return [_lower(x) for x in v]
    return [_lower(v)]


def _date(v):
    s = _s(v)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    return None


# op -> (needs_value, fn(cell, value) -> bool)
OPS: dict[str, tuple[bool, object]] = {
    "equals":       (True,  lambda c, v: _lower(c) == _lower(v)),
    "not_equals":   (True,  lambda c, v: _lower(c) != _lower(v)),
    "in":           (True,  lambda c, v: _lower(c) in _list(v)),
    "not_in":       (True,  lambda c, v: _lower(c) not in _list(v)),
    "contains":     (True,  lambda c, v: _lower(v) in _lower(c)),
    "not_contains": (True,  lambda c, v: _lower(v) not in _lower(c)),
    "starts_with":  (True,  lambda c, v: _lower(c).startswith(_lower(v))),
    "ends_with":    (True,  lambda c, v: _lower(c).endswith(_lower(v))),
    "is_blank":     (False, lambda c, v: _s(c) == ""),
    "is_not_blank": (False, lambda c, v: _s(c) != ""),
    "gt":           (True,  lambda c, v: _num(c) is not None and _num(c) > float(v)),
    "gte":          (True,  lambda c, v: _num(c) is not None and _num(c) >= float(v)),
    "lt":           (True,  lambda c, v: _num(c) is not None and _num(c) < float(v)),
    "lte":          (True,  lambda c, v: _num(c) is not None and _num(c) <= float(v)),
    "between":      (True,  lambda c, v: _num(c) is not None
                            and float(v[0]) <= _num(c) <= float(v[1])),
    "matches":      (True,  lambda c, v: re.search(str(v), _s(c), re.I) is not None),
    "older_than_days": (True, lambda c, v: (lambda d: d is not None
                                            and (datetime.now() - d).days > float(v))(_date(c))),
}

VALUE_LESS = {op for op, (needs, _fn) in OPS.items() if not needs}


def validate_clause(clause: dict) -> str:
    """Return '' when the clause is usable, else a plain-English reason."""
    if not isinstance(clause, dict):
        return "a rule must be an object like {field, op, value}"
    field = _s(clause.get("field"))
    op = _s(clause.get("op"))
    if not field:
        return "rule is missing 'field'"
    if op not in OPS:
        return f"unknown operator '{op}' (allowed: {', '.join(sorted(OPS))})"
    if op not in VALUE_LESS and "value" not in clause:
        return f"operator '{op}' needs a 'value'"
    if op == "between":
        v = clause.get("value")
        if not (isinstance(v, (list, tuple)) and len(v) == 2):
            return "'between' needs a value of exactly two numbers, e.g. [2, 10]"
    if op == "matches":
        try:
            re.compile(str(clause.get("value")))
        except re.error as e:
            return f"invalid regular expression: {e}"
    return ""


def validate_rules(rules) -> list[str]:
    """Every problem in a whole rule set, so they can all be fixed in one pass."""
    issues: list[str] = []
    if rules in (None, {}, []):
        return issues
    if not isinstance(rules, dict):
        return ["rules must be an object with 'all', 'any' and/or 'none'"]
    for block in ("all", "any", "none"):
        clauses = rules.get(block) or []
        if not isinstance(clauses, list):
            issues.append(f"'{block}' must be a list of rules")
            continue
        for i, c in enumerate(clauses):
            why = validate_clause(c)
            if why:
                issues.append(f"{block}[{i}]: {why}")
    unknown = set(rules) - {"all", "any", "none"}
    issues += [f"unknown rule block '{u}' (use all / any / none)" for u in sorted(unknown)]
    return issues


def test_clause(row: dict, clause: dict, fm) -> bool:
    """Evaluate ONE clause against a raw sheet row. A broken clause is False, never a crash."""
    op = _s(clause.get("op"))
    spec = OPS.get(op)
    if not spec:
        return False
    cell = fm.resolve(row, _s(clause.get("field")))
    try:
        return bool(spec[1](cell, clause.get("value")))
    except (TypeError, ValueError, re.error, IndexError):
        return False


def match(row: dict, rules, fm) -> tuple[bool, str]:
    """Does this row qualify? Returns (passed, reason) — the reason names the first
    clause that rejected it, so a preview can explain every excluded row."""
    if not rules:
        return True, ""
    for c in rules.get("all") or []:
        if not test_clause(row, c, fm):
            return False, f"{_s(c.get('field'))} {_s(c.get('op'))} {c.get('value', '')}".strip()
    any_clauses = rules.get("any") or []
    if any_clauses and not any(test_clause(row, c, fm) for c in any_clauses):
        return False, "no 'any' rule matched"
    for c in rules.get("none") or []:
        if test_clause(row, c, fm):
            return False, f"excluded by {_s(c.get('field'))} {_s(c.get('op'))} {c.get('value', '')}".strip()
    return True, ""


# ───────────────────────── ordering ─────────────────────────

def _sort_once(rows: list[dict], spec: dict, fm) -> list[dict]:
    """Sort by ONE spec. Two forms:

      {"field": "Employees", "dir": "desc"}                  numeric, else text A-Z
      {"field": "contact_source", "order": ["a","b","c"]}    explicit best-first list

    Two guarantees that stop a bad list jumping the queue:
      * a blank cell always sorts LAST, in both directions
      * a value missing from an explicit order sorts last, never first
    """
    field = _s(spec.get("field"))
    explicit = spec.get("order")
    desc = _lower(spec.get("dir")) == "desc"

    present, blank = [], []
    for r in rows:
        (present if _s(fm.resolve(r, field)) else blank).append(r)

    if explicit:
        ranks = {_lower(v): i for i, v in enumerate(explicit)}
        present.sort(key=lambda r: ranks.get(_lower(fm.resolve(r, field)), len(ranks)),
                     reverse=desc)
    else:
        def key(r):
            cell = fm.resolve(r, field)
            n = _num(cell)
            # one consistent shape for every row, so a number is never compared to a
            # tuple: numbers rank ahead of text, and text falls back to A-Z
            return (0, n, "") if n is not None else (1, 0.0, _lower(cell))
        present.sort(key=key, reverse=desc)

    return present + blank


def sort_rows(rows: list[dict], order, fm) -> list[dict]:
    """Apply the order specs, first one strongest.

    Python's sort is stable, so applying the specs in REVERSE order and sorting once per
    spec gives each spec its own direction — which a single composite key cannot do for
    text descending."""
    out = list(rows)
    for spec in reversed(order or []):
        if _s(spec.get("field")):
            out = _sort_once(out, spec, fm)
    return out
