# U.S. Treasury Wire — Debt & Auction Monitor

A single-file, static dashboard showing:
- Total public debt outstanding (Debt to the Penny), with the public/intragovernmental
  split and a trailing ~12-month trend chart
- The currently announced Treasury auction calendar (bills, notes, bonds, FRNs, TIPS)
- Results from completed auctions in the trailing 45 days

All data is fetched **client-side, at page load**, directly from Treasury's own public
APIs — there is no backend, build step, or API key:

- `https://api.fiscaldata.treasury.gov/...` — Debt to the Penny
- `https://www.treasurydirect.gov/TA_WS/securities/...` — auction announcements & results

## Deploy on GitHub Pages

1. Create a new repo (or use an existing one) and add `index.html` to the repo root.
2. Push to GitHub.
3. In the repo: **Settings → Pages → Build and deployment → Source: Deploy from a
   branch**, branch `main`, folder `/ (root)`. Save.
4. GitHub gives you a URL like `https://<username>.github.io/<repo>/` within a minute
   or two — that's the live dashboard.

No other configuration is needed — it's a plain HTML/CSS/JS file.

## Notes / known limitations

- **CORS**: both Treasury endpoints are public, unauthenticated APIs, but they are
  government infrastructure, not a CDN — if either ever stops sending permissive
  CORS headers, the browser will block the fetch and the affected panel will show
  a "could not reach…" message with a link to the source instead of failing silently.
- **Refresh cadence**: the debt figure only updates once per U.S. business day at
  the source; the page auto-refreshes every 15 minutes and also has a manual
  "Refresh now" button. There is no live-ticking estimate between official updates —
  the headline number is always the last officially published figure, clearly dated.
- **Auction fields**: TreasuryDirect's `TA_WS` fields aren't formally versioned, so
  the JS reads several candidate field names defensively (e.g. `highYield` /
  `highDiscountRate` / `highInvestmentRate`) rather than assuming one.
