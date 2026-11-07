"""
pipeline.py — the per-firm cascade.

TWO paths, chosen per campaign:

A) NO RECIPE — today's fixed order, a faithful port of V7's decision spine. Unchanged.
   Every existing campaign takes this path, byte for byte:
     1. Security-gateway guard      -> hold_security_gateway
     2. Endole email (existing)     -> optional MillionVerifier
     3. Pattern guess               -> MillionVerifier   (skipped on no-website leads)
     4. Icypeas fallback            -> optional MillionVerifier
     5. Anymailfinder fallback      -> optional MillionVerifier
     6. Found  -> build icebreaker ; else no_website / email_not_found

B) A RECIPE (`cfg["recipe"]`, see core/recipe.py) — the order is HIS setting, not code:
     1. Security-gateway guard      (locked first, before any spend)
     2. skip the row?               -> skipped_by_rule
     3. for each PERSON in his ladder, in his order
          for each WAY to find them, in his order
            -> check -> keep / mark / drop, by his rule
     4. his stop rule               -> the best candidate
     5. result -> build icebreaker

Emits a structured event at every step (live feed + Log) and returns one result row. The
recipe path deliberately reuses the SAME stage names as path A ("endole" for an address
already on the row, "verify" for a guess, "icypeas" for a search), so Activity reads the
same on both and no screen had to change for this.

The caller injects the tools so tests + no-spend mode work:
  verify_email(email)  -> {accepted, verification, tier}
  find_icypeas(firm)   -> {email, certainty}   (credit charged by caller only if email)
  find_anymail(firm)   -> {email}
  make_icebreaker(firm, email) -> {text, style}

⛔ Locked here, a recipe cannot change them (docs/RECIPE-BUILDER.md §3):
  * catch-all stays off — `accepted` comes from the verifier, never from the recipe
  * nothing unverified is pushed — every marked outcome carries send_ready = "no", which
    is the gate webapp/server.py `_is_send_ready` reads first
  * the security guard runs first, before a recipe gets a say
"""
from __future__ import annotations

import re

from . import emailgen
from . import gateway
from . import icebreaker as icebreaker_mod
from . import recipe as recipe_mod

STAGES = ["organize", "gateway", "endole", "pattern", "verify", "icypeas", "anymail",
          "icebreaker", "result"]


def _row(firm: dict, *, status: str, found_email: str = "", source: str = "", verification: str = "",
         tries=None, verifs: int = 0, icebreaker: str = "", ice_style: str = "",
         director: str | None = None) -> dict:
    if director is None:
        director = firm.get("lead_director", "") or firm.get("Oldest Director Name", "")
    got = bool(found_email)
    return {
        "company_key": firm.get("company_key") or firm.get("Company Name", ""),
        "company": firm.get("Company Name", ""), "domain": firm.get("lead_domain", ""),
        "phone": firm.get("lead_phone", ""), "city": firm.get("lead_city", ""),
        "gateway_provider": firm.get("email_security_gateway_provider", ""),
        "selected_director": director, "found_email": found_email, "email_source": source,
        "verification": verification, "status": status, "verifications_used": verifs,
        "icebreaker": icebreaker, "ice_style": ice_style, "tries": tries or [],
        "Oldest Director Name": firm.get("Oldest Director Name", ""),
        "Youngest Director Name": firm.get("Youngest Director Name", ""),
        "Director 1 Name": firm.get("Director 1 Name", ""),
        "Director 2 Name": firm.get("Director 2 Name", ""),
        "Director 3 Name": firm.get("Director 3 Name", ""),
        "Oldest Director Email": found_email if got else "",
        "Director 1 Email": found_email if got else "",
        "Oldest Director Verification": verification if got else "",
        "Director 1 Verification": verification if got else "",
    }


def _finder_stage(firm, cfg, stage, use_key, verify_key, source, finder, check, emit):
    """Run one external finder (Icypeas / Anymailfinder). Returns a `found` dict or None."""
    company = firm.get("Company Name", "")
    if not (cfg.get(use_key, False) and finder):
        return None
    emit(company, stage, "info", "searching…")
    r = finder(firm)
    em = r.get("email", "")
    if not em:
        emit(company, stage, "fail", r.get("error") or "not found")
        return None
    if cfg.get(verify_key, False):
        v = check(em)
        if v["accepted"]:
            emit(company, stage, "success", f"{em} · {v['verification']}", em)
            return {"email": em, "source": source, "verification": v["verification"]}
        emit(company, stage, "fail", f"{em} · {v['verification']}", em)
        return None
    cert = r.get("certainty", "")
    emit(company, stage, "success", f"{em} · accepted (no MF{', ' + cert if cert else ''})", em)
    return {"email": em, "source": source, "verification": f"verified_by_{stage}_no_mf{('_' + cert) if cert else ''}"}


def process_firm(firm: dict, cfg: dict, verify_email, emit,
                 find_icypeas=None, find_anymail=None, make_icebreaker=None,
                 fm=None, seen_person=None, remember_person=None) -> dict:
    """One firm -> one result row.

    `cfg["recipe"]` picks path B. Without it this is exactly V1's cascade, which is what
    keeps every existing campaign untouched by the recipe work."""
    rec = cfg.get("recipe")
    if rec:
        return _process_firm_recipe(
            firm, cfg, verify_email, emit, rec, fm=fm,
            find_icypeas=find_icypeas, make_icebreaker=make_icebreaker,
            seen_person=seen_person, remember_person=remember_person)
    return _process_firm_fixed(firm, cfg, verify_email, emit,
                               find_icypeas=find_icypeas, find_anymail=find_anymail,
                               make_icebreaker=make_icebreaker)


# ───────────────────── path A: today's fixed order (unchanged) ─────────────────────

def _process_firm_fixed(firm: dict, cfg: dict, verify_email, emit,
                        find_icypeas=None, find_anymail=None, make_icebreaker=None) -> dict:
    company = firm.get("Company Name", "")
    domain = firm.get("lead_domain", "")
    state = {"verifs": 0}

    def check(email):
        state["verifs"] += 1
        return verify_email(email)

    # 1) security gateway
    gw = gateway.guard(firm.get("email_security_gateway_provider", ""),
                       block=bool(cfg.get("block_security_gateways", False)))
    if gw["held"]:
        emit(company, "gateway", "held", f"held · {gw['provider']}")
        return _row(firm, status="hold_security_gateway", verification="hold_security_gateway")

    found, tries = None, []

    # 2) existing Endole email
    endole = str(firm.get("lead_endole_email", "") or "").strip()
    if cfg.get("use_endole", True) and endole:
        if firm.get("endole_generic"):
            emit(company, "endole", "skip", f"generic mailbox skipped · {endole}")
        elif cfg.get("verify_endole_with_mf", True):
            v = check(endole)
            if v["accepted"]:
                emit(company, "endole", "success", f"{endole} · {v['verification']}", endole)
                found = {"email": endole, "source": "endole", "verification": v["verification"]}
            else:
                emit(company, "endole", "fail", f"{endole} · {v['verification']}", endole)
        else:
            emit(company, "endole", "success", f"{endole} · accepted (no verify)", endole)
            found = {"email": endole, "source": "endole", "verification": "accepted_no_mf"}

    no_web = bool(firm.get("is_no_website_path"))

    # 3) pattern guess (needs a domain)
    if not found and not no_web and cfg.get("use_patterns", True) and domain:
        for c in emailgen.candidates_for_firm(firm, mode=cfg.get("pattern_mode", "lean")):
            v = check(c["email"])
            tries.append({"email": c["email"], "accepted": v["accepted"],
                          "verification": v["verification"], "pattern": c.get("pattern", "")})
            if v["accepted"]:
                emit(company, "verify", "success", f"{c['email']} · {v['verification']}", c["email"])
                found = {"email": c["email"], "source": f"pattern_{c.get('pattern', '')}", "verification": v["verification"]}
                break
            emit(company, "verify", "fail", f"{c['email']} · {v['verification']}", c["email"])
    elif not found and no_web:
        emit(company, "pattern", "skip", "no website — patterns skipped")

    # 4) Icypeas fallback  5) Anymailfinder fallback
    if not found:
        found = _finder_stage(firm, cfg, "icypeas", "use_icypeas", "verify_icypeas_with_mf",
                              "icypeas_director", find_icypeas, check, emit)
    if not found:
        found = _finder_stage(firm, cfg, "anymail", "use_anymailfinder", "verify_anymailfinder_with_mf",
                              "anymailfinder_director", find_anymail, check, emit)

    # 6) result (+ icebreaker on a hit)
    if found:
        ib = {"text": "", "style": ""}
        if cfg.get("use_icebreaker", True):
            fw = dict(firm); fw["found_email"] = found["email"]
            ib = (make_icebreaker(fw, found["email"]) if make_icebreaker else icebreaker_mod.build(fw, found["email"]))
            if ib.get("text"):
                emit(company, "icebreaker", "success", f"[{ib.get('style', '')}] {ib['text'][:60]}…")
        return _row(firm, status="email_found", found_email=found["email"], source=found["source"],
                    verification=found["verification"], tries=tries, verifs=state["verifs"],
                    icebreaker=ib.get("text", ""), ice_style=ib.get("style", ""))

    if no_web:
        return _row(firm, status="no_website", verification="no_website", tries=tries, verifs=state["verifs"])
    emit(company, "result", "fail", "email_not_found · all sources exhausted")
    return _row(firm, status="email_not_found", verification="not_found", tries=tries, verifs=state["verifs"])


# ───────────────────── path B: his recipe ─────────────────────

# a candidate's quality, best first. The ladder's own order breaks a tie, so "1st
# director" always beats "2nd director" at the same quality.
RANK_PASSED = 0          # MillionVerifier said yes
RANK_UNCHECKED = 1       # the way said do not check — still never sendable
RANK_CHECK_BY_HAND = 2   # passed, but the domain does not look like this firm
RANK_FAILED = 3          # the check failed; only written when last_resort is on

RANK_STATUS = {
    RANK_PASSED: recipe_mod.STATUS_FOUND,
    RANK_UNCHECKED: recipe_mod.STATUS_FOUND,
    RANK_CHECK_BY_HAND: recipe_mod.STATUS_CHECK_BY_HAND,
    RANK_FAILED: recipe_mod.STATUS_FAILED_CHECK,
}

# a pass is what the stop rule means by "an email that passes"
STOPPING_RANKS = (RANK_PASSED, RANK_UNCHECKED)

def _domain_looks_like_company(email: str, company: str) -> bool:
    """A rough "is this address even at the right firm?" check for icypeas_company.

    Icypeas is asked by company NAME when a firm has no website, so it can answer with
    an address at a completely different business. This is deliberately generous — its
    only consequence is that a human looks at the row, never that an address is dropped.
    """
    dom = str(email or "").split("@")[-1].strip().lower()
    label = re.sub(r"[^a-z0-9]", "", dom.split(".")[0])
    words = recipe_mod.company_words(company)
    if not label or not words:
        return True                                   # nothing to compare -> do not nag
    joined = "".join(words)
    if label in joined or joined in label:
        return True
    if label == "".join(w[0] for w in words):         # smithjonesco -> sjc
        return True
    return any(w in label or (len(w) >= 4 and w[:4] in label) for w in words)


def _person_view(firm: dict, person: dict, *, use_domain: bool) -> dict:
    """The firm as this ONE person, for a finder that reads `lead_firstname` etc.

    `use_domain=False` is how "ask by company name" is expressed: finders.py falls back
    from lead_domain to the company name on its own, so clearing it is the whole trick —
    no finder had to change for this."""
    view = dict(firm)
    view["lead_director"] = person["name"]
    view["lead_firstname"] = person["first"]
    view["lead_lastname"] = person["last"]
    if not use_domain:
        view["lead_domain"] = ""
        view["lead_website"] = ""
    return view


def _process_firm_recipe(firm: dict, cfg: dict, verify_email, emit, rec, *, fm=None,
                         find_icypeas=None, make_icebreaker=None,
                         seen_person=None, remember_person=None) -> dict:
    r = rec if isinstance(rec, recipe_mod.Recipe) else recipe_mod.Recipe(rec)
    company = firm.get("Company Name", "")
    state = {"verifs": 0}
    tries: list[dict] = []

    def check(email):
        state["verifs"] += 1
        return verify_email(email)

    # 1) the security guard, first and locked — a recipe never gets to spend before it
    gw = gateway.guard(firm.get("email_security_gateway_provider", ""),
                       block=bool(cfg.get("block_security_gateways", False)))
    if gw["held"]:
        emit(company, "gateway", "held", f"held · {gw['provider']}")
        return _recipe_row(firm, r, status="hold_security_gateway",
                           verification="hold_security_gateway")

    # 2) who does this row offer, in his order
    row = firm.get("_raw") or firm
    plan = recipe_mod.plan_for_row(r, row, firm, fm)

    if plan["skip"]:
        emit(company, "organize", "skip", plan["skip_reason"])
        return _recipe_row(firm, r, status=recipe_mod.STATUS_SKIPPED,
                           verification="skipped_by_rule", plan=plan)
    for d in plan["dropped"]:
        emit(company, "organize", "skip", f"{d['label']}: {d['why']}")
    if not plan["people"]:
        emit(company, "result", "fail", plan["skip_reason"])
        return _recipe_row(firm, r, status=recipe_mod.STATUS_NO_PERSON,
                           verification="no_person", plan=plan)

    emit(company, "organize", "info",
         "trying " + ", ".join(f"{p['label']} ({p['name'] or p['address']})"
                               for p in plan["people"]))

    # 3) his ladder: each person, each way
    candidates: list[dict] = []
    searched: list[str] = []
    attempted: list[str] = []
    stop = False

    for person in plan["people"]:
        if stop:
            break
        # the same person at the same firm is searched once, even across tabs
        pkey = recipe_mod.person_cache_key(plan["company"], person["name"])
        if r.search_same_person_once and person["name"] and seen_person and seen_person(pkey):
            emit(company, "organize", "skip",
                 f"{person['label']}: {person['name']} was already searched")
            plan["dropped"].append({"label": person["label"],
                                    "why": f"{person['name']} was already searched"})
            continue
        if person["name"]:
            searched.append(pkey)
        attempted.append(person["label"])

        for way in person["ways"]:
            if stop:
                break
            if not way["ok"]:
                emit(company, _stage_of(way["method"]), "skip",
                     f"{person['label']}: {way['why']}")
                continue
            got = _run_way(firm, person, way, company, check, emit, tries,
                           find_icypeas=find_icypeas)
            for cand in got:
                cand["person_idx"] = person["idx"]
                cand["label"] = person["label"]
                cand["person"] = person["name"]        # blank for an address-only rung
                candidates.append(cand)
                if cand["rank"] in STOPPING_RANKS and r.stop_when == "first_pass":
                    stop = True
                    break

    if r.search_same_person_once and remember_person:
        for pkey in searched:
            remember_person(pkey)

    # 4) his stop rule picks the winner. A failed address survives if its own way said
    # "write it anyway", or if "maximum leads filled" is on AND it is a real address
    # rather than a guess nobody has ever confirmed exists.
    usable = [c for c in candidates
              if c["rank"] != RANK_FAILED or c["keep_on_fail"]
              or (r.last_resort and not c["guessed"])]
    if not usable:
        if not attempted:
            # nobody was actually searched (everyone was already done on another tab).
            # "not found" would be a lie, and it is retryable — this lead is finished.
            emit(company, "result", "skip", "nobody left to try on this row")
            return _recipe_row(firm, r, status=recipe_mod.STATUS_NO_PERSON,
                               verification="no_person", plan=plan, attempted=attempted)
        if candidates:
            # something was found but every one of them failed its check, and he has not
            # switched "maximum leads filled" on
            emit(company, "result", "fail",
                 f"{len(candidates)} address(es) found, none passed the check")
        else:
            emit(company, "result", "fail", "email_not_found · nobody on this row worked")
        status = ("no_website" if firm.get("is_no_website_path")
                  else recipe_mod.STATUS_NOT_FOUND)
        return _recipe_row(firm, r, status=status,
                           verification=("no_website" if status == "no_website" else "not_found"),
                           tries=tries, verifs=state["verifs"], plan=plan,
                           candidates=candidates, attempted=attempted)

    usable.sort(key=lambda c: (c["rank"], c["person_idx"]))
    best = usable[0]
    status = RANK_STATUS[best["rank"]]
    if best["rank"] == RANK_FAILED:
        emit(company, "result", "info",
             f"nothing passed — writing {best['email']} marked as failed, never sent")
    elif best["rank"] == RANK_CHECK_BY_HAND:
        emit(company, "result", "info", f"{best['email']} · {best['note']}")

    # 5) the icebreaker, on an address, exactly as path A does it
    ib = {"text": "", "style": ""}
    if cfg.get("use_icebreaker", True):
        fw = dict(firm)
        fw["found_email"] = best["email"]
        fw["lead_director"] = best["person"]
        ib = (make_icebreaker(fw, best["email"]) if make_icebreaker
              else icebreaker_mod.build(fw, best["email"]))
        if ib.get("text"):
            emit(company, "icebreaker", "success", f"[{ib.get('style', '')}] {ib['text'][:60]}…")

    return _recipe_row(firm, r, status=status, found_email=best["email"],
                       source=best["source"], verification=best["verification"],
                       tries=tries, verifs=state["verifs"],
                       icebreaker=ib.get("text", ""), ice_style=ib.get("style", ""),
                       plan=plan, candidates=candidates, best=best, attempted=attempted)


def _stage_of(method: str) -> str:
    """The existing stage name for a way, so Activity reads the same on both paths."""
    return {"guess_patterns": "verify", "icypeas_domain": "icypeas",
            "icypeas_company": "icypeas", "use_as_is": "endole"}.get(method, "result")


def _candidate(email, source, verification, rank, note="", keep_on_fail=False):
    return {"email": email, "source": source, "verification": verification,
            "rank": rank, "note": note,
            # a guess that failed its check is noise, not a fallback: nobody ever said
            # that mailbox exists. A real address that failed is still a real address.
            "guessed": str(source).startswith("pattern_"),
            "keep_on_fail": keep_on_fail}


def _judge(email, way, check, *, source, found_note="") -> list[dict]:
    """One address through his check rule. Returns exactly one candidate.

    This is the only place `accepted` is read, and it comes from the verifier — which is
    how "catch-all stays off" stays true no matter what a recipe says."""
    mode = way["verify"]
    if mode == "no_check":
        return [_candidate(email, source, "accepted_no_check", RANK_UNCHECKED, found_note)]
    v = check(email)
    if v["accepted"]:
        if found_note:
            return [_candidate(email, source, v["verification"], RANK_CHECK_BY_HAND, found_note)]
        return [_candidate(email, source, v["verification"], RANK_PASSED)]
    # it failed. "write but mark as failed" keeps it whatever happens; with "must pass"
    # it survives only as a last_resort candidate, and only if it is a real address.
    return [_candidate(email, source, v["verification"], RANK_FAILED,
                       note=("written, marked as failed" if mode == "write_failed"
                             else "failed the check"),
                       keep_on_fail=(mode == "write_failed"))]


def _run_way(firm, person, way, company, check, emit, tries, *, find_icypeas=None) -> list[dict]:
    """One way to find one person. Returns the candidates it produced (0, 1, or many)."""
    stage = _stage_of(way["method"])
    label = person["label"]
    out: list[dict] = []

    if way["method"] == "use_as_is":
        em = person["address"]
        emit(company, stage, "info", f"{label}: using {em} from '{person['address_column']}'")
        out = _judge(em, way, check, source="endole")

    elif way["method"] == "guess_patterns":
        cands = emailgen.generate(person["first"], person["last"], firm.get("lead_domain", ""),
                                  mode=way["pattern_mode"], middle=person.get("middle", ""))
        for c in cands:
            cand = _judge(c["email"], way, check, source=f"pattern_{c.get('pattern', '')}")[0]
            tries.append({"email": c["email"], "accepted": cand["rank"] == RANK_PASSED,
                          "verification": cand["verification"], "pattern": c.get("pattern", ""),
                          "person": person["name"], "label": label, "method": way["method"]})
            if cand["rank"] in STOPPING_RANKS:
                emit(company, stage, "success", f"{label}: {c['email']} · {cand['verification']}", c["email"])
                return [cand]                        # good enough — stop guessing for this person
            emit(company, stage, "fail", f"{label}: {c['email']} · {cand['verification']}", c["email"])
            out.append(cand)
        # only the failures are left: keep the first, it is the likeliest shape
        out = out[:1]

    elif way["method"] in ("icypeas_domain", "icypeas_company"):
        by_domain = way["method"] == "icypeas_domain"
        if not find_icypeas:
            emit(company, stage, "skip", f"{label}: Icypeas is not switched on")
            return []
        emit(company, stage, "info",
             f"{label}: asking Icypeas by {'website' if by_domain else 'company name'}…")
        res = find_icypeas(_person_view(firm, person, use_domain=by_domain)) or {}
        em = str(res.get("email") or "").strip()
        if not em:
            emit(company, stage, "fail", f"{label}: {res.get('error') or 'not found'}")
            return []
        note = ""
        if (not by_domain and way["note_if_domain_mismatch"]
                and not _domain_looks_like_company(em, company)):
            note = f"{em.split('@')[-1]} does not look like {company} — check by hand"
        out = _judge(em, way, check,
                     source=f"icypeas_{'domain' if by_domain else 'company'}", found_note=note)
        if out and out[0]["rank"] == RANK_PASSED:
            emit(company, stage, "success", f"{label}: {em} · {out[0]['verification']}", em)
        elif out:
            emit(company, stage, "fail" if out[0]["rank"] == RANK_FAILED else "info",
                 f"{label}: {em} · {out[0]['note'] or out[0]['verification']}", em)
        tries.append({"email": em, "accepted": bool(out and out[0]["rank"] == RANK_PASSED),
                      "verification": out[0]["verification"] if out else "",
                      "pattern": "", "person": person["name"], "label": label,
                      "method": way["method"]})

    return out


def _recipe_row(firm, r, *, status, found_email="", source="", verification="", tries=None,
                verifs=0, icebreaker="", ice_style="", plan=None, candidates=None,
                best=None, attempted=None) -> dict:
    """A result row from path B.

    Built on top of path A's row so everything downstream (the ledger, the labels, the
    write-back) keeps working, then four things added:
      * `found_for` / `found_by` — his two new sheet columns
      * `send_ready` — "yes" ONLY on a real pass. webapp/server.py's send gate reads
        this first, so a marked address can never be pushed, whatever its verification
        string happens to say.
      * `accepted` — the same answer, for core/sheets.py build_writeback_row
      * the plan, so Activity can say who was tried and who was dropped
    """
    passed = status == recipe_mod.STATUS_FOUND and bool(found_email) and \
        (best or {}).get("rank") == RANK_PASSED
    person = (best or {}).get("person", "") or ""
    label = (best or {}).get("label", "") or ""

    out = _row(firm, status=status, found_email=found_email, source=source,
               verification=verification, tries=tries, verifs=verifs,
               icebreaker=icebreaker, ice_style=ice_style, director=person)
    out.update({
        "recipe": r.id or r.name,
        # "Ian Smith (1st director)". A rung that only had an address has no name to
        # show, so the rung's own label is all there is to say.
        "found_for": (f"{person} ({label})" if person and label else (person or label)),
        "found_by": _found_by_words(source, verification, (best or {}).get("note", "")),
        # the winning rung's own label, on its own. `found_for` buries it in brackets
        # next to the name; a recipe that writes his sheet's final_contact_index /
        # final_email_source needs it whole and unparsed.
        "found_rung": label,
        "contact_name": person,
        "send_ready": "yes" if passed else "no",
        "accepted": bool(passed),
        "needs_check": status == recipe_mod.STATUS_CHECK_BY_HAND,
        "people_tried": list(attempted or []),
        "people_dropped": list((plan or {}).get("dropped", [])),
        "alternate_emails": ", ".join(
            dict.fromkeys(c["email"] for c in (candidates or [])
                          if c["email"] and c["email"] != found_email)),
    })
    return out


def _found_by_words(source: str, verification: str, note: str) -> str:
    """The `Found By` column: how it was found, plus what the check said."""
    how = {"endole": "the address on the row",
           "icypeas_domain": "Icypeas (by website)",
           "icypeas_company": "Icypeas (by company name)"}.get(source, "")
    if not how:
        how = (f"guessed ({source[8:]}@)" if source.startswith("pattern_") else source) or "—"
    bits = [how]
    if verification:
        bits.append(str(verification))
    if note:
        bits.append(note)
    return " · ".join(bits)


# ───────────────────── the run ─────────────────────

def run(firms, cfg, verify_email, emit, should_cancel=None, **tools) -> list[dict]:
    """Every firm, in order.

    "Search the same person once" is kept for the length of THIS run when the caller has
    not injected a store, so a recipe honours it today without a cache file. A test run
    must pass no store at all: its finds are invented and may never be remembered."""
    results = []
    seen: set[str] = set()
    if cfg.get("recipe") and "seen_person" not in tools:
        tools = {**tools, "seen_person": seen.__contains__, "remember_person": seen.add}
    for firm in firms:
        if should_cancel and should_cancel():
            break
        results.append(process_firm(firm, cfg, verify_email, emit, **tools))
    return results
