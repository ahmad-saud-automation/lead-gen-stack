"""
eval_rules.py - offline test for the campaign rule engine (no network, no keys).
    python eval_rules.py   /   pytest eval_rules.py
"""
from __future__ import annotations

import sys

from core.fieldmap import FieldMap
from core.rules import match, sort_rows, test_clause, validate_rules, OPS

FM = FieldMap({"employees": "Employees", "status": "Status", "send_gate": "send_ready",
               "seniority_rank": "seniority_label", "trading_years": "Trading Years"})

ROW = {"Employees": "7", "Status": "", "send_ready": "yes", "seniority_label": "owner",
       "Trading Years": "12", "trigger_family": "A5_departure", "fabrikam_contacted": "no"}


def _c(field, op, value=None):
    c = {"field": field, "op": op}
    if value is not None:
        c["value"] = value
    return c


def check_every_operator_has_a_working_case():
    """A silently broken operator would quietly drop leads out of a campaign."""
    cases = {
        "equals": (_c("send_gate", "equals", "YES"), True),          # case-insensitive
        "not_equals": (_c("send_gate", "not_equals", "no"), True),
        "in": (_c("seniority_rank", "in", ["owner", "leadership"]), True),
        "not_in": (_c("seniority_rank", "not_in", ["partner"]), True),
        "contains": (_c("trigger_family", "contains", "departure"), True),
        "not_contains": (_c("trigger_family", "not_contains", "hiring"), True),
        "starts_with": (_c("trigger_family", "starts_with", "A5"), True),
        "ends_with": (_c("trigger_family", "ends_with", "ure"), True),
        "is_blank": (_c("status", "is_blank"), True),
        "is_not_blank": (_c("send_gate", "is_not_blank"), True),
        "gt": (_c("employees", "gt", 5), True),
        "gte": (_c("employees", "gte", 7), True),
        "lt": (_c("employees", "lt", 10), True),
        "lte": (_c("employees", "lte", 7), True),
        "between": (_c("employees", "between", [2, 10]), True),
        "matches": (_c("trigger_family", "matches", r"^A\d_"), True),
        "older_than_days": (_c("mv_date", "older_than_days", 30), False),   # no date -> False
    }
    missing = set(OPS) - set(cases)
    assert not missing, f"operators with no test: {missing}"
    for name, (clause, want) in cases.items():
        got = test_clause(ROW, clause, FM)
        assert got is want, f"{name}: got {got}, wanted {want}"


def check_a_range_cell_uses_its_largest_number():
    """Apollo writes bands like '11-50'. Treating that as 11 would drop it into the
    2-10 lane. It must read as 50, the same rule instantly.size_band uses."""
    band = {"Employees": "11-50"}
    assert test_clause(band, _c("employees", "between", [2, 10]), FM) is False
    assert test_clause(band, _c("employees", "between", [11, 50]), FM) is True
    assert test_clause({"Employees": "2-10"}, _c("employees", "between", [2, 10]), FM) is True


def check_all_any_none_blocks():
    rules = {"all": [_c("status", "is_blank"), _c("send_gate", "equals", "yes")],
             "any": [_c("seniority_rank", "equals", "owner"),
                     _c("seniority_rank", "equals", "leadership")],
             "none": [_c("fabrikam_contacted", "equals", "yes")]}
    ok, why = match(ROW, rules, FM)
    assert ok is True, why
    ok, why = match({**ROW, "fabrikam_contacted": "yes"}, rules, FM)   # excluded
    assert ok is False and "excluded" in why, why
    ok, why = match({**ROW, "seniority_label": "partner"}, rules, FM)   # no 'any' hit
    assert ok is False and "any" in why, why
    ok, why = match({**ROW, "send_ready": "no"}, rules, FM)        # fails 'all'
    assert ok is False and "send_gate" in why, why


def check_empty_rules_match_everything():
    for empty in (None, {}, {"all": []}):
        assert match(ROW, empty, FM)[0] is True, empty


def check_a_broken_clause_is_false_not_a_crash():
    """One bad rule must exclude that row, never kill the whole run."""
    assert test_clause(ROW, _c("employees", "between", [1]), FM) is False       # short list
    assert test_clause(ROW, _c("employees", "gte", "abc"), FM) is False         # not a number
    assert test_clause(ROW, {"field": "x", "op": "nonsense"}, FM) is False
    assert test_clause({"Employees": ""}, _c("employees", "gte", 1), FM) is False


def check_validate_rules_catches_bad_config():
    issues = validate_rules({"all": [{"field": "x"}, _c("y", "banana", 1),
                                     _c("z", "between", [1]), _c("q", "matches", "(")],
                             "wrong_block": []})
    joined = " | ".join(issues)
    assert "missing 'field'" not in joined                      # field IS present
    assert "unknown operator 'banana'" in joined, joined
    assert "two numbers" in joined, joined
    assert "regular expression" in joined, joined
    assert "unknown rule block" in joined, joined
    assert validate_rules(None) == []


def check_sort_explicit_order_and_unlisted_last():
    rows = [{"src": "pattern_mv"}, {"src": "apollo_reveal"}, {"src": "mystery"},
            {"src": "icypeas"}]
    out = sort_rows(rows, [{"field": "src",
                            "order": ["apollo_reveal", "icypeas", "pattern_mv"]}], FieldMap({}))
    assert [r["src"] for r in out] == ["apollo_reveal", "icypeas", "pattern_mv", "mystery"], out


def check_sort_blanks_always_last_in_both_directions():
    rows = [{"n": "5"}, {"n": ""}, {"n": "20"}]
    asc = [r["n"] for r in sort_rows(rows, [{"field": "n", "dir": "asc"}], FieldMap({}))]
    desc = [r["n"] for r in sort_rows(rows, [{"field": "n", "dir": "desc"}], FieldMap({}))]
    assert asc == ["5", "20", ""], asc
    assert desc == ["20", "5", ""], desc


def check_sort_mixes_numbers_and_text_without_crashing():
    """The bug this guards: one row yields a number and another yields text for the same
    key, so a naive composite key compares a float with a tuple and raises."""
    rows = [{"v": "10"}, {"v": "unknown"}, {"v": "3"}, {"v": "alpha"}]
    out = [r["v"] for r in sort_rows(rows, [{"field": "v", "dir": "asc"}], FieldMap({}))]
    assert out[:2] == ["3", "10"], out            # numbers first, in order
    assert set(out[2:]) == {"alpha", "unknown"}, out


def check_sort_is_stable_and_first_spec_is_strongest():
    rows = [{"a": "1", "b": "z", "id": 1}, {"a": "1", "b": "a", "id": 2},
            {"a": "0", "b": "m", "id": 3}]
    out = sort_rows(rows, [{"field": "a", "dir": "asc"}, {"field": "b", "dir": "asc"}],
                    FieldMap({}))
    assert [r["id"] for r in out] == [3, 2, 1], out


def check_text_descending_works():
    rows = [{"t": "alpha"}, {"t": "zulu"}, {"t": "mike"}]
    out = [r["t"] for r in sort_rows(rows, [{"field": "t", "dir": "desc"}], FieldMap({}))]
    assert out == ["zulu", "mike", "alpha"], out


CHECKS = [check_every_operator_has_a_working_case, check_a_range_cell_uses_its_largest_number,
          check_all_any_none_blocks, check_empty_rules_match_everything,
          check_a_broken_clause_is_false_not_a_crash, check_validate_rules_catches_bad_config,
          check_sort_explicit_order_and_unlisted_last,
          check_sort_blanks_always_last_in_both_directions,
          check_sort_mixes_numbers_and_text_without_crashing,
          check_sort_is_stable_and_first_spec_is_strongest, check_text_descending_works]


def test_operators(): check_every_operator_has_a_working_case()
def test_range(): check_a_range_cell_uses_its_largest_number()
def test_blocks(): check_all_any_none_blocks()
def test_empty(): check_empty_rules_match_everything()
def test_broken(): check_a_broken_clause_is_false_not_a_crash()
def test_validate(): check_validate_rules_catches_bad_config()
def test_order(): check_sort_explicit_order_and_unlisted_last()
def test_blanks(): check_sort_blanks_always_last_in_both_directions()
def test_mixed(): check_sort_mixes_numbers_and_text_without_crashing()
def test_stable(): check_sort_is_stable_and_first_spec_is_strongest()
def test_desc(): check_text_descending_works()


def main() -> int:
    failed = 0
    for c in CHECKS:
        try:
            c(); print(f"PASS  {c.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {c.__name__}: {e}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
