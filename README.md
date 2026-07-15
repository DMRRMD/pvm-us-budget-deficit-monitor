# PVM US Budget Deficit Monitor — GitHub Pages deployment

This package is ready to publish as a public static website using **GitHub Pages**.

## Files

- `index.html` — the live dashboard app

## Fast deploy steps

1. Create a new public GitHub repository, for example:
   - `pvm-us-budget-deficit-monitor`
2. Upload `index.html` into the root of that repository.
3. In GitHub, open the repository.
4. Go to **Settings** → **Pages**.
5. Under **Build and deployment**:
   - **Source**: `Deploy from a branch`
   - **Branch**: `main`
   - **Folder**: `/ (root)`
6. Click **Save**.
7. Wait about 1–3 minutes.
8. Your public site should appear at a URL like:
   - `https://YOUR-USERNAME.github.io/pvm-us-budget-deficit-monitor/`

## Updating the site later

When you want to update the dashboard:

1. Replace `index.html` in the repository with the new version.
2. Commit the change.
3. GitHub Pages will automatically republish the site.

## Notes

- This is a browser-only app; no Python or backend is required.
- The page fetches live Treasury FiscalData API endpoints directly in the browser.
- If the Treasury changes API field names or browser access rules, some cards may need code updates.

## Optional custom domain

If you want a branded URL later, you can add a custom domain in:

- **Settings** → **Pages** → **Custom domain**

Examples:
- `budget.purevaluemetrics.com`
- `deficit.purevaluemetrics.com`

## Suggested repo description

Live public dashboard for U.S. budget deficit, debt, TGA balance, and net interest run-rate using official Treasury FiscalData APIs.
