# Deploying Yagnum to Azure

How the site gets onto the internet, what the Free tier can and cannot
do, and how to redeploy. Written 2026-09-07 (ADR-027).

---

## 1. What it is, simply

**ELI5.** Until now the app only ran on one laptop, so only that laptop
could open it. Azure App Service is a rented computer that Microsoft
keeps on for you and gives an address. We rent two rooms in the smallest
free building: one for the API, one for the website. Neon keeps the
database, GitHub keeps running the crons, and Alpaca and Jupiter are where
they always were. Only the two apps move.

**The rule.** *Nothing in the deployment is typed by hand.* The first
deployment is one script that reads the root `.env` and creates and
configures everything. After that a push to `main` redeploys through
GitHub Actions. If a setting needs changing, change the script or the
workflow, never the portal, so the next run does not undo it.

**The trap.** The Free tier sleeps. After twenty minutes with no visitor
the apps are unloaded, and the next visitor waits ten to thirty seconds
while they start. That is not a bug, and it is the price of $0.

---

## 2. The pieces, and the words Azure uses

| Azure word | What it is here |
| --- | --- |
| Subscription | The billing account. "Azure subscription 1". |
| Resource group | A folder for related things. `yagnum-rg`, in East US 2. |
| App Service plan | The rented computer. `yagnum-free`, Linux, tier F1. One plan can hold several apps. |
| Web app | One running app on that plan. `yagnum-api` (Python 3.13) and `yagnum-web` (Node 22). |
| App settings | Environment variables for one web app. Where every secret lives. |
| Startup command | What to run when the app starts. |
| Zip deploy | Upload a zip; App Service unpacks it and, for the API, installs requirements. |

The support plan you chose during sign-up, "Basic - Included", is not one
of these. It only says nobody at Microsoft answers tickets for you. It
costs nothing and changes nothing about the site.

---

## 3. What the Free tier gives, and what it does not

| | F1 Free |
| --- | --- |
| Price | $0 |
| CPU | 60 minutes a day, per app, shared hardware |
| Memory | 1 GB |
| Storage | 1 GB |
| Always on | No. Sleeps after 20 idle minutes. |
| Custom domain | No. The address is `<name>.azurewebsites.net`. |
| TLS | Yes, on the Azure address. |

The CPU minute is the number to watch. Every request costs a little of
it. The dashboard polls the API every few seconds while it is open, so an
afternoon of demoing can use a meaningful share. If the app starts
answering "quota exceeded", that is the day's 60 minutes gone; it resets
at midnight UTC. The step up is Basic B1 at about $13 a month per app,
which also brings always-on and a custom domain.

---

## 4. How each app is shipped

**The API** goes as source. `scripts/azure/package.py api` zips the
`app/api` folder without the virtual environment and tests. App Service
sees `requirements.txt`, installs it into its own environment, and runs
the startup command:

```
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

`requirements.txt` is generated from `uv.lock` by
`uv export --no-dev --no-hashes --format requirements-txt` and committed,
so the server installs exactly the versions the laptop tested.

**The website** goes prebuilt. `next.config.ts` sets `output:
"standalone"`, so `npm run build` emits a self-contained `server.js` with
only the modules it needs. `package.py web` copies the static assets and
the public folder beside it and zips the result. The startup command is:

```
HOSTNAME=0.0.0.0 node server.js
```

The `HOSTNAME` part matters: App Service sets that variable to the
machine's name, and Next.js would bind to it and be unreachable.

The reason for prebuilding is memory. A Next.js build needs more than the
Free tier's 1 GB, so the build runs on the laptop or in GitHub Actions and
only the result goes up.

---

## 5. Settings that change in production

| Setting | Value on Azure | Why |
| --- | --- | --- |
| `APP_ENV` | `production` | The weekend simulator switch and injected settlement do not exist. Weekend trades happen on real weekends. Flip it to `development` on the API's app settings to get the switch back for a demo. |
| `ALLOW_TOKENS_WITHOUT_AZP` | `false` | Every session token must be pinned to the website's origin. |
| `FRONTEND_ORIGIN` | `https://yagnum-web.azurewebsites.net` | What the token pin and CORS compare against. Must match exactly. |
| `API_URL` (web) | `https://yagnum-api.azurewebsites.net` | The website's server-side proxy calls this. The browser never does. |
| `DATABASE_URL` | Neon, unchanged | One database for the site, the crons and the sim (ADR-027). |
| `SOLANA_ENGINE_PUBKEY` | set; keypair absent | The shadow hedge builds and simulates unsigned on Azure. The secret key stays on the laptop. |
| `GROQ_API_KEY` | absent | The personas run from GitHub, not from the site. |
| Clerk keys | the development instance | Clerk's production instance needs a domain we do not have. The site shows Clerk's development badge until then. |

---

## 6. Procedure

**First time.** Sign in and run the script from the repository root:

```
az login --tenant db5c99bc-8854-4cfe-b6b0-495b255bb6cf --scope "https://management.core.windows.net//.default"
bash scripts/azure/first-deploy.sh
```

It creates the group, the plan and both apps, sets every app setting from
`.env`, builds the website, and deploys both. Ten minutes. Then open
`https://yagnum-api.azurewebsites.net/health` and the website.

**Every time after.** Push to `main`. The workflow
`.github/workflows/deploy-azure.yml` rebuilds and redeploys whichever
app changed. It needs three repository secrets, listed at the top of the
workflow file; the two publish profiles come from:

```
az webapp deployment list-publishing-profiles -g yagnum-rg -n yagnum-api --xml
az webapp deployment list-publishing-profiles -g yagnum-rg -n yagnum-web --xml
```

**By hand, without GitHub.** `bash scripts/azure/first-deploy.sh deploy`
repackages and redeploys both apps from the laptop.

**Logs.** `az webapp log tail -g yagnum-rg -n yagnum-api` streams the
API's output; the same with `yagnum-web` for the site.

**Database migrations.** Neon is the same database the laptop uses, so
`uv run alembic upgrade head` in `app/api` on the laptop is the
migration step. The deployed API never migrates.

---

## 7. Say it back

1. What does the "Basic - Included" support plan decide about the site?
   *(Nothing. It is the support contract, not the hosting tier.)*
2. Why does the website arrive prebuilt while the API arrives as source?
   *(A Next.js build does not fit in 1 GB; installing Python packages
   does.)*
3. Why is the first visit after a quiet hour slow? *(The Free tier
   unloads idle apps after 20 minutes and restarts them on demand.)*
4. What stops the weekend simulator from appearing on the deployed site?
   *(`APP_ENV=production`. The switch only exists in development.)*
