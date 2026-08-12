# The number on your Gumroad page is not the number your buyer pays

Gumroad is the merchant of record. For a buyer in the UK or the EU it adds VAT **at the
pay step**, on top of the figure the product page showed them. You cannot see this from
inside your own account: logged in, from your own country, in your own currency, both the
page and the dashboard show you the pre-tax number.

Your buyer sees one number on the page and a larger one at the moment of paying.

## What that costs, measured

27 of 31 Gumroad products drawn at random charge a UK buyer more at the checkout
than their page advertises. The median gap is **21.2%**; the range runs
16.6% to 27.9%.

That is the drawn sample only. **Our own product is not counted in it** — it was walked
too, and it has the same gap, but a store you chose yourself does not belong in a random
sample's numerator. The per-store table, including ours, is
[published here](https://sujeito-operator.github.io/gumroad-market-data/checkout.html).

| | |
|---|---:|
| sellers in the frame | 4,255 |
| products drawn (stratified, seeded) | 32 |
| readable | 31 |
| **charge more at the pay step** | **27** |
| page and pay step agree | 1 |
| charge less at the pay step | 1 |
| page prices in a currency the pay step does not use | 2 |
| not readable (the product is free) | 1 |

The gap is a percentage, so the money at stake scales with your price. Drawn by band:

| seller median price (USD) | products higher at checkout | median gap |
|---|---:|---:|
| under-10 | 6 | 21.2% |
| 10-29 | 7 | 21.2% |
| 30-99 | 8 | 21.0% |
| 100-plus | 6 | 21.1% |

Every reading is in [`data/sample-2026-08-09.json`](data/sample-2026-08-09.json) with the
subtotal, the tax line and the total each product's own checkout itemised.

## Measure your own

```
pip install playwright && playwright install chromium
python checkout_gap.py https://YOURSTORE.gumroad.com/l/YOURPRODUCT
```

```
  the page showed        £184.34
  the checkout itemised  £186.52 + £37.28 VAT
  the buyer pays         £223.80   -- 21.4% more
```

That is this repo's own product, read from London. Run it from the market you sell to —
the reading is taken from wherever the machine is, so a US box will show you the US
answer, which is the one you can already see.

It loads two public pages and stops. It completes no order, submits no form, types no
email or card into a checkout, and touches no account.

Give it as many product URLs as you like and it reads them all. When a run turns up a
gap it closes by saying what can be done about one — including the paid thing at the
bottom of this page, so you know that up front. `--no-offer` turns that off. Under a
clean reading it says nothing, because there would be nothing to say.

## What it will not tell you

The reading **refuses rather than guesses**. A page figure is only quoted when the
checkout subtotal confirms it within 6%. A product whose page carries no figure the pay
step agrees with comes back `none`, not zero and not a finding.

That gate exists because an earlier version took the smallest repeated amount on the page
— which on a storefront is somebody else's product — and produced a reading that
overstated a real seller's own price by more than threefold. `choose_page_price` in
[`checkout_gap.py`](checkout_gap.py) carries the whole story.

`VAT` is the label the checkouts themselves used.

## Nobody here did anything wrong

This is Gumroad's doing, not the seller's. Gumroad is the merchant of record; for a buyer
in a VAT jurisdiction it collects the tax on top of the listed price and remits it. That
is lawful, it is what a merchant of record is for, and no setting in a seller's account
switches it off. Our own product does exactly the same thing. The only thing a seller can
do about it is say so in the description — which is why knowing the number matters.

## Reproducing the sample

The rows in this repo are aggregate, by band. The frame and the draw are both public, so
you can redraw the identical sample and walk it yourself:

1. The frame is [`gumroad-sellers.csv`](https://github.com/sujeito-operator/gumroad-market-data/blob/main/data/gumroad-sellers.csv)
   — 4,255 sellers with a paid median price (290 more
   were excluded for having none).
2. The draw is seeded at **20260809**, stratified by seller median listed price, 4 bands, equal draw. Same CSV,
   same seed, same 32 products, in the same order.
3. Walk them with `checkout_gap.py` and compare.

Prices reconvert daily — these pages are priced in USD and Gumroad re-renders them in
sterling at the day's rate — so the page figures will not match 2026-08-09 exactly.
The checkout totals were stable across re-walks; the gap is the thing to compare.

## The whole storefront, done for you

This measures one product. If you want every product on your storefront walked and
itemised the same way — page figure, subtotal, tax line, total, and the gap on each —
that is what I sell:

**[Storefront checkout audit →](https://sujeitooperator.gumroad.com/l/xlvfeb?referrer=https://readme-cg.click.sujeito.org/)** (price on the page)

Also free, no email required: **[Gumroad Market Data](https://github.com/sujeito-operator/gumroad-market-data)** — 8,311 products
across 4,532 sellers, with real unit sales for the ones that expose them.

## Licence

MIT. The readings you take with it are yours.
