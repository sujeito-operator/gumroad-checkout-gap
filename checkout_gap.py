#!/usr/bin/env python3
"""What a UK/EU buyer is actually charged on a Gumroad product.

Gumroad is the merchant of record. For a buyer in the UK or the EU it adds VAT at the
pay step, on top of the number the product page showed them. The seller cannot see this:
logged in, from their own country, in their own currency, the page and the dashboard both
show the pre-tax figure. The buyer sees one number on the page and a larger one at the
moment of paying.

This script measures the difference on one product. It loads two public pages -- the
product page and the checkout the page's own buy control links to -- reads what each one
says, and prints the gap. It never completes an order, never submits a form, never types
an email or a card into a checkout, and never touches an account. It is exactly what a
buyer who thinks about it and leaves does.

    pip install playwright && playwright install chromium
    python checkout_gap.py https://YOURSTORE.gumroad.com/l/YOURPRODUCT

The reading refuses rather than guesses. A page price is only quoted when the checkout
subtotal confirms it within 6%; a product whose page carries no figure the pay step
agrees with is reported as unread, not as zero and not as a finding. That gate exists
because an earlier version picked the cheapest amount on the page -- which on a storefront
is somebody else's product -- and produced a reading that overstated a real seller's own
price threefold. See `choose_page_price`.

The measuring code below is lifted byte-for-byte from the audit this is the free version
of; it is not a reimplementation, and a build gate fails if the two ever diverge.

MIT licensed. Numbers you get from it are yours; if you publish them, the method is here.
"""
import argparse
import json
import re
import sys

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

SYMBOL = {"£": "GBP", "$": "USD", "€": "EUR"}

MONEY = re.compile(r"([£$€])\s?(\d[\d,]*(?:\.\d{1,2})?)")

TAX_WORDS = ("vat", "tax", "gst", "sales tax")

def money(text):
    """[(iso, amount_float, raw), ...] in document order. Never a bare float."""
    out = []
    for sym, num in MONEY.findall(text or ""):
        try:
            out.append((SYMBOL[sym], float(num.replace(",", "")), sym + num))
        except ValueError:
            continue
    return out

def largest(items, iso=None):
    """Biggest amount, optionally within one currency. None if there is nothing to pick."""
    pool = [i for i in items if iso is None or i[0] == iso]
    return max(pool, key=lambda i: i[1]) if pool else None

def parse_checkout(text):
    """Subtotal / tax / total off the checkout, read as labelled lines.

    Returns a dict with whatever it could actually read. A missing key means the line
    was not found, NOT that the value is zero — the difference matters, because a
    silent zero would turn 'we could not read the tax' into 'there is no tax'.
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    got = {}
    for i, line in enumerate(lines):
        low = line.lower()
        # The label may carry its amount inline or on the following line.
        here = money(line)
        nxt = money(lines[i + 1]) if i + 1 < len(lines) else []
        vals = here[1:] if (here and len(here) > 1) else (here or nxt)
        if not vals:
            continue
        if low.startswith("subtotal") and "subtotal" not in got:
            got["subtotal"] = vals[0]
        elif low.startswith("total") and "total" not in got:
            got["total"] = vals[0]
        elif any(low.startswith(w) for w in TAX_WORDS) and "tax" not in got:
            got["tax"] = vals[0]
            got["tax_label"] = line.split()[0].rstrip(":")
    return got

PRICE_MATCH_TOL = 0.06

def choose_page_price(repeated, checkout):
    """The page price is the repeated amount THE CHECKOUT CONFIRMS. None if none does.

    WHY THIS REPLACED `min(repeated)`, AND IT MATTERS BECAUSE A FALSE ONE WAS RECORDED.
    walk() collects every money token on the page and keeps the ones appearing at least
    twice, on the sound reasoning that Gumroad renders the product's price in the header
    and again at the buy control. It then took the SMALLEST of them. But these pages are
    storefronts: they list the seller's other products, and a cheaper item repeats exactly
    as reliably as the walked one. So `min` did not pick the price the buy control agrees
    with — it picked the cheapest thing on the page, and the code comment claimed the
    opposite.

    It produced a false reading that was written into evidence as a sendable finding:
    `gluelab` (2026-08-12 00:47Z) advertises €24 and the checkout itemises $27.70 + $5.54
    VAT = $33.24. €24 at the implied 1.154 rate IS $27.70, so the base agreed and the only
    real findings were a EUR->USD switch and 20% VAT. `min` picked €9 — another product on
    the storefront — and the row's `why` read "page advertises €9 and the pay step charges
    $33.24". Had a batch quoted that to gluelab, it would have overstated their own price
    by more than threefold to someone who could disprove it in thirty seconds. That costs
    more than the finding is worth, and this shape's entire premise is that the stranger
    can check the number.

    So the choice is made AFTER the checkout is read, against the subtotal, and it refuses
    rather than guesses: no repeated token in the subtotal's currency within
    PRICE_MATCH_TOL means there is nothing on the page the pay step confirms, and the
    honest output is no page price at all. classify() then says only what was read.
    """
    if not repeated:
        return None
    anchor = checkout.get("subtotal") or checkout.get("total")
    if not anchor or anchor[1] <= 0:
        return None
    same = [k for k in repeated if k[0] == anchor[0]]
    if not same:
        return None
    best = min(same, key=lambda k: abs(k[1] - anchor[1]))
    if abs(best[1] - anchor[1]) / anchor[1] > PRICE_MATCH_TOL:
        return None
    return best

def classify(page_price, checkout, repeated=()):
    """What can honestly be said. Returns (verdict, delta_pct or None, why).

    Verdicts:
      `tax_on_top`   the page price and the checkout total are in the SAME currency and
                     the total is materially higher. This is the one worth an email.
      `currency`     the page advertises one currency and the pay step charges another.
      `none`         the numbers agree, or there is not enough to compare. Say nothing.

    `repeated` is walk()'s list of page amounts seen at least twice. It is only consulted
    when `page_price` is None, to tell two different silences apart: a page priced in a
    currency the pay step does not use (a real `currency` finding) and a page nothing
    could be read off at all (`none`).
    """
    total = checkout.get("total")
    if not total:
        return "none", None, "no comparable pair was read"
    if not page_price:
        # NO NUMBER IS QUOTED HERE ON PURPOSE. Without a page amount in the pay step's
        # currency there is no honest conversion to state — see choose_page_price.
        if repeated and not any(k[0] == total[0] for k in repeated):
            seen = "/".join(sorted({k[0] for k in repeated}))
            return "currency", None, (
                f"the page prices in {seen} and the pay step charges {total[2]}; no page "
                f"figure is in the pay step's currency, so no gap is quoted")
        return "none", None, "no page figure the checkout confirms"
    if page_price[0] != total[0]:
        return "currency", None, (
            f"page advertises {page_price[2]} and the pay step charges {total[2]}")
    if page_price[1] <= 0:
        return "none", None, "advertised price is zero or free"
    delta = (total[1] - page_price[1]) / page_price[1] * 100.0
    if delta < 2.0:
        return "none", round(delta, 1), "advertised and charged agree"
    return "tax_on_top", round(delta, 1), (
        f"page shows {page_price[2]}, pay step totals {total[2]}")

SETTLE_TRIES = 8
SETTLE_MS = 1500


def settle(read, done, tries=SETTLE_TRIES, pause=None):
    """Call `read()` until `done(value)`, or `tries` runs out. -> the last value read.

    A FIXED SLEEP IS A GUESS ABOUT SOMEBODY ELSE'S CONNECTION. The first published
    version waited 3.5s on the product page and 7s on the checkout, and both figures
    are rendered client-side. Measured on the box that built it, one run in three came
    back `none` against a product that was working perfectly. A seller who gets `none`
    on their own live product concludes this tool is broken, and they are not wrong to.

    Polling costs nothing when the page is quick -- the first read returns and the loop
    exits -- and it is the difference between a reading and a shrug when it is slow.
    """
    val = None
    for _ in range(tries):
        val = read()
        if done(val):
            return val
        if pause:
            pause(SETTLE_MS)
    return val


def repeated_money(body):
    """Amounts a visitor sees at least twice, sorted.

    The price is only trusted when the same amount appears twice -- Gumroad renders it
    in the header and again at the buy control. A single occurrence is prose. WHICH
    repeated amount is the price is decided later, against the checkout, not here.
    """
    counts = {}
    for iso, amt, raw in money(body):
        counts.setdefault((iso, amt, raw), 0)
        counts[(iso, amt, raw)] += 1
    return sorted((k for k, n in counts.items() if n >= 2), key=lambda k: (k[0], k[1]))


def walk(pg, url):
    """One product: page figures, the checkout the page links to, and the verdict."""
    rec = {"url": url}
    pg.goto(url, timeout=60000, wait_until="domcontentloaded")
    repeated = settle(lambda: repeated_money(pg.inner_text("body")), bool,
                      pause=pg.wait_for_timeout)
    rec["title"] = (pg.title() or "")[:140]
    rec["page_repeated"] = [list(k) for k in repeated]

    a = pg.query_selector("a[href*='gumroad.com/checkout']")
    href = a.get_attribute("href") if a else None
    rec["checkout_href"] = href
    if not href:
        rec["page_price"] = None
        rec["verdict"], rec["delta_pct"], rec["why"] = "none", None, "no buy control found"
        return rec

    pg.goto(href, timeout=60000, wait_until="domcontentloaded")
    parsed = settle(lambda: parse_checkout(pg.inner_text("body")),
                    lambda p: bool(p.get("total")), pause=pg.wait_for_timeout)
    rec["checkout_url"] = pg.url
    rec["checkout"] = {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in parsed.items()}
    rec["page_price"] = choose_page_price(repeated, parsed)
    rec["verdict"], rec["delta_pct"], rec["why"] = classify(
        rec["page_price"], parsed, repeated)
    return rec


def report(rec):
    """Three lines, in the shape the numbers were read in."""
    ck = rec.get("checkout") or {}
    out = [rec["url"], ""]
    pp = rec.get("page_price")
    if pp:
        out.append(f"  the page showed        {pp[2]}")
    if ck.get("subtotal"):
        line = f"  the checkout itemised  {ck['subtotal'][2]}"
        if ck.get("tax"):
            line += f" + {ck['tax'][2]} {ck.get('tax_label', 'tax')}"
        out.append(line)
    if ck.get("total"):
        tail = f"   -- {rec['delta_pct']}% more" if rec.get("delta_pct") else ""
        out.append(f"  the buyer pays         {ck['total'][2]}{tail}")
    out += ["", f"  verdict: {rec['verdict']} -- {rec['why']}"]
    return "\n".join(out)


FINDINGS = ("tax_on_top", "currency")


def offer(recs):
    """The closing block, or "" when this run found nothing.

    CONDITIONAL ON PURPOSE. Under a clean reading this is an advertisement and it does
    not print. Under the reader's own finding it is the answer to the question the
    finding raises -- and the free fix is named before the paid one, because the free
    fix is the one that actually helps most sellers.
    """
    hits = [r for r in recs if r.get("verdict") in FINDINGS]
    read = [r for r in recs if r.get("verdict") != "error"]
    if not hits:
        return ""
    n, of = len(hits), len(read)
    return "\n".join([
        "-" * 72,
        f"{n} of {of} product(s) read here cost the buyer more at the pay step than the",
        "page advertised.",
        "",
        "Nobody did anything wrong. Gumroad is the merchant of record; for a buyer in a",
        "VAT country it collects the tax on top of the listed price and remits it. No",
        "setting in your account switches that off, and my own product does the same",
        "thing. The only thing you control is whether the page says so -- one line in",
        "the description, which costs nothing and is what I did on mine.",
        "",
        "You can point this script at the rest of your URLs right now and read them all",
        "yourself. It takes as many as you give it, it is MIT, and it is the same code.",
        "",
        "Two things here cost money, and this is all of them.",
        "",
        "The whole storefront walked once and sent back as one table -- page figure,",
        "subtotal, tax line, total and gap on every product:",
        "",
        "  https://sujeitooperator.gumroad.com/l/xlvfeb?referrer=https://tool-cg.click.sujeito.org/",
        "",
        "Or the same walk every week, for as long as you keep it, with an email the day a",
        "product's pay step stops matching its page. That one is a subscription, billed",
        "monthly until you cancel; the first month is the table above. It exists because",
        "what this script measured is not a fixed property of your store -- one of the",
        "storefronts I watch moved its pay step by 3.2% in forty hours while its page",
        "moved 0.08%, and nothing on the page said so:",
        "",
        "  https://sujeitooperator.gumroad.com/l/zyoqbc?referrer=https://mon-cg.click.sujeito.org/",
        "",
    ])


def selftest():
    """Pure-function checks on recorded fixtures. No network."""
    ok = 0

    def eq(got, want, what):
        nonlocal ok
        assert got == want, f"{what}: {got!r} != {want!r}"
        ok += 1

    eq(money("was $9 now £7.50"), [("USD", 9.0, "$9"), ("GBP", 7.5, "£7.50")], "money")
    eq(money("€1,234.00"), [("EUR", 1234.0, "€1,234.00")], "thousands separator")
    eq(money("no money here"), [], "no money")
    eq(largest(money("$4 $19 $7"))[1], 19.0, "largest")

    ck = parse_checkout("Subtotal\n£186.52\nVAT\n£37.28\nTotal\n£223.80")
    eq(ck["subtotal"], ("GBP", 186.52, "£186.52"), "subtotal")
    eq(ck["tax"], ("GBP", 37.28, "£37.28"), "tax")
    eq(ck["tax_label"], "VAT", "tax label")
    eq(ck["total"], ("GBP", 223.8, "£223.80"), "total")
    eq(parse_checkout("Total: £40.00")["total"], ("GBP", 40.0, "£40.00"), "inline amount")
    eq("tax" in parse_checkout("Subtotal\n£10\nTotal\n£10"), False, "missing != zero")

    rep = [("GBP", 9.0, "£9"), ("GBP", 184.34, "£184.34")]
    eq(choose_page_price(rep, ck), ("GBP", 184.34, "£184.34"), "confirmed price wins")
    eq(choose_page_price([("GBP", 9.0, "£9")], ck), None, "unconfirmed refuses")
    eq(choose_page_price(rep, {}), None, "no checkout, no price")
    eq(choose_page_price([], ck), None, "nothing repeated")

    v, d, _ = classify(("GBP", 184.34, "£184.34"), ck)
    eq((v, d), ("tax_on_top", 21.4), "tax_on_top")
    v, d, _ = classify(("GBP", 40.0, "£40"), {"total": ("GBP", 40.0, "£40")})
    eq(v, "none", "agreement is not a finding")
    v, _, _ = classify(("EUR", 24.0, "€24"), {"total": ("USD", 33.24, "$33.24")})
    eq(v, "currency", "currency switch")
    v, _, _ = classify(None, {"total": ("USD", 33.24, "$33.24")},
                       [("EUR", 24.0, "€24")])
    eq(v, "currency", "silence in another currency is still a finding")
    v, _, _ = classify(None, {"total": ("USD", 33.24, "$33.24")}, [])
    eq(v, "none", "silence with nothing read says nothing")

    seq = iter([[], [], ["found"]])
    waits = []
    eq(settle(lambda: next(seq), bool, pause=waits.append), ["found"], "settle waits")
    eq(waits, [SETTLE_MS, SETTLE_MS], "and paused between reads, twice")
    eq(settle(lambda: ["now"], bool, pause=waits.append), ["now"], "a quick page waits 0")
    eq(len(waits), 2, "no extra pause once it is done")
    eq(settle(lambda: [], bool, tries=3, pause=lambda _: None), [],
       "a page that never settles gives up and returns what it saw")

    eq(repeated_money("£9 £9 £4"), [("GBP", 9.0, "£9")], "twice is a price")
    eq(repeated_money("£9 £4"), [], "once is prose")

    eq(offer([{"verdict": "none"}]), "", "a clean reading is not pitched at")
    eq(offer([{"verdict": "error"}]), "", "a failed reading is not pitched at")
    eq(offer([]), "", "nothing read, nothing said")
    eq("cost money" in offer([{"verdict": "tax_on_top"}]), True, "a finding asks")
    eq("cost money" in offer([{"verdict": "currency"}]), True, "so does a currency switch")
    # The recurring link may not appear without the three words that describe it. This is
    # asserted in the SHIPPED tool as well as in the builder, because this file is what a
    # stranger reads and edits, and a gate that only lives upstream does not travel.
    _fired = offer([{"verdict": "tax_on_top"}])
    eq(all(w in _fired for w in ("subscription", "monthly", "cancel")), True,
       "the recurring option says that it recurs and can be cancelled")
    eq(offer([{"verdict": "tax_on_top"}, {"verdict": "none"}]).splitlines()[1][:6],
       "1 of 2", "the count is of what was read")
    eq(offer([{"verdict": "tax_on_top"}, {"verdict": "error"}]).splitlines()[1][:6],
       "1 of 1", "and an error was not read")
    eq(re.search(r"[$£€]\s?\d", offer([{"verdict": "tax_on_top"}])), None,
       "no price is typed in the offer -- the page renders it")

    print(f"selftest OK ({ok} checks)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", nargs="*", help="Gumroad product URL(s)")
    ap.add_argument("--json", metavar="PATH", help="write the raw readings here")
    ap.add_argument("--country", default="GB", help="informational; the reading is from "
                    "wherever this machine is. Run it from the market you sell to.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-offer", action="store_true", help="readings only; suppress the "
                    "closing block that says what can be done about a finding")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.url:
        ap.error("give at least one Gumroad product URL, or --selftest")

    bad = [u for u in a.url if not re.match(r"https://[a-z0-9-]+\.gumroad\.com/l/", u, re.I)]
    if bad:
        ap.error(f"not Gumroad product URLs: {bad}")

    from playwright.sync_api import sync_playwright

    recs = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(user_agent=UA, viewport={"width": 1280, "height": 900})
        for u in a.url:
            try:
                recs.append(walk(pg, u))
            except Exception as e:                      # one bad page is not a bad run
                recs.append({"url": u, "verdict": "error", "why": f"{type(e).__name__}: {e}"})
            print(report(recs[-1]) if recs[-1].get("verdict") != "error"
                  else f"{u}\n  error: {recs[-1]['why']}")
            print()
        br.close()

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(recs, fh, indent=1, default=list)
        print(f"wrote {a.json}")
    if not a.no_offer:
        block = offer(recs)
        if block:
            print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
