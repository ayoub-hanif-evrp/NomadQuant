# UI visual verification (Prompt 07)

Captured with Playwright Chromium against the local API (`127.0.0.1:8000`) and Next dev server (`127.0.0.1:3000`) on 2026-10-15.

## Verified screens

| Screen | Viewports |
| --- | --- |
| Command Center | 1920×1080, 1440×900, 1280×800, 390×844 |
| Market Explorer (real SIP SPY candles) | same |
| Research Lab (run #2 equity/drawdown) | same |
| Decision Intelligence | same |
| Activity / Runs | same |
| Mobile navigation drawer | 390×844 |

Filenames: `{screen}-{viewport}.png` and `mobile-nav-390x844.png`.

## Notes from inspection

- Alpaca paper equity (~$100k) is visually separated from the $100 research allocation.
- Market Explorer shows provenance chips (alpaca/sip/raw/1Day) and TradingView Lightweight Charts attribution.
- Research Lab shows PASS verification and date-aligned multi-series equity; agents remain empty.
- No browser console errors were printed during capture.

## Re-capture

```powershell
Set-Location apps\web
node .\scripts-capture-ui-shots.mjs
```

Requires `playwright` (devDependency) and both servers running.
