"""
cost.py — the savings story, with two sources spelled out:

  1) Cheaper per email — Apollo charges 1 credit per REVEALED email; we instead
     run MillionVerifier checks (1 credit each, pass or fail) at a fraction of the
     price. Even at 1:1 the check is far cheaper than the reveal.
  2) Dedup before spend — the organize step removes duplicate / already-done /
     owned leads BEFORE any spend. On Apollo you'd have burned a credit revealing
     each of those; here they cost nothing.

Rates depend on your plans (set them in Settings):
  * apollo_credit_usd        — $ per Apollo credit.   e.g. $59 / 2,500 = $0.0236
                               0 / unknown → we still show CREDITS AVOIDED.
  * mv_per_verification_usd  — $ per MillionVerifier check. e.g. $89 / 50,000 = $0.00178

Pure math — no network.
"""
from __future__ import annotations

DEFAULTS = {
    "apollo_credit_usd": 0.0,           # unknown by default → show credits, not $
    "mv_per_verification_usd": 0.0005,  # overridden by config with your real plan rate
}


def summarize(*, firms_total: int, emails_found: int, verifications_used: int,
              duplicates_removed: int = 0,
              apollo_credit_usd: float | None = None,
              mv_per_verification_usd: float | None = None) -> dict:
    apollo_rate = DEFAULTS["apollo_credit_usd"] if apollo_credit_usd is None else float(apollo_credit_usd)
    mv_rate = DEFAULTS["mv_per_verification_usd"] if mv_per_verification_usd is None else float(mv_per_verification_usd)
    duplicates_removed = int(duplicates_removed or 0)

    credits_avoided = emails_found
    our_cost = round(verifications_used * mv_rate, 4)
    cost_per_found = round(our_cost / emails_found, 5) if emails_found else 0.0
    verifs_per_found = round(verifications_used / emails_found, 2) if emails_found else 0.0

    if apollo_rate and apollo_rate > 0:
        # Apollo: 1 credit per revealed email, plus the credits it would have
        # burned revealing the duplicate/skipped leads we removed first.
        apollo_reveal_cost = round(emails_found * apollo_rate, 2)
        apollo_dedup_cost = round(duplicates_removed * apollo_rate, 2)
        apollo_cost = round(apollo_reveal_cost + apollo_dedup_cost, 2)
        saved_verify = round(apollo_reveal_cost - our_cost, 2)   # source 1
        saved_dedup = apollo_dedup_cost                          # source 2
        savings = round(apollo_cost - our_cost, 2)
        savings_pct = round(savings / apollo_cost * 100, 1) if apollo_cost > 0 else 0.0
        apollo_rate_known = True

        parts = [f"${saved_verify:.2f} from cheaper checks"]
        if duplicates_removed:
            parts.append(f"${saved_dedup:.2f} from removing {duplicates_removed} duplicate/skipped leads")
        headline = (f"Got {emails_found} verified emails for ${our_cost:.2f} instead of "
                    f"~${apollo_cost:.2f} on Apollo — saved ${savings:.2f} ({savings_pct:.0f}%): "
                    + " + ".join(parts) + ".")
    else:
        apollo_reveal_cost = apollo_dedup_cost = apollo_cost = None
        saved_verify = saved_dedup = savings = savings_pct = None
        apollo_rate_known = False
        headline = (f"Got {emails_found} verified emails for ${our_cost:.4f} — and kept "
                    f"{credits_avoided} Apollo credits you'd have spent (1 per email). "
                    f"Set your Apollo $/credit in Settings to see the $ saved.")

    return {
        "firms_total": firms_total,
        "emails_found": emails_found,
        "verifications_used": verifications_used,
        "duplicates_removed": duplicates_removed,
        "credits_avoided": credits_avoided,
        "apollo_rate_known": apollo_rate_known,
        "apollo_cost_usd": apollo_cost,               # total apollo-equivalent (reveal + dedup)
        "apollo_reveal_cost_usd": apollo_reveal_cost,
        "apollo_dedup_cost_usd": apollo_dedup_cost,
        "mv_cost_usd": our_cost,
        "saved_verify_usd": saved_verify,
        "saved_dedup_usd": saved_dedup,
        "savings_usd": savings,
        "savings_pct": savings_pct,
        "cost_per_found_usd": cost_per_found,
        "verifications_per_found": verifs_per_found,
        "headline": headline,
    }


def summarize_results(results: list[dict], **rates) -> dict:
    """Totals from a list of per-firm results (each with found_email + verifications_used).
    Pass duplicates_removed=<n> and the plan rates through **rates."""
    firms = len(results)
    found = sum(1 for r in results if r.get("found_email"))
    verifs = sum(int(r.get("verifications_used", 0)) for r in results)
    return summarize(firms_total=firms, emails_found=found, verifications_used=verifs, **rates)
