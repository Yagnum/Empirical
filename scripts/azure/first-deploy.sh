#!/usr/bin/env bash
# First deployment of Yagnum to Azure App Service, Free tier (ADR-027).
#
#   bash scripts/azure/first-deploy.sh            # create everything and deploy
#   bash scripts/azure/first-deploy.sh deploy     # redeploy only (resources exist)
#
# Run from the repository root with `az login` done. Secrets come from the
# root .env; nothing is typed by hand. Idempotent: every `create` is safe to
# run again. The walkthrough of what each step does is docs/AZURE-DEPLOY.md.
set -euo pipefail

RG="${RG:-yagnum-rg}"
LOC="${LOC:-westus2}"
PLAN="${PLAN:-yagnum-free}"
API="${API:-yagnum-api}"
WEB="${WEB:-yagnum-web}"
API_URL="https://${API}.azurewebsites.net"
WEB_URL="https://${WEB}.azurewebsites.net"

set -a; source .env; set +a

if [ "${1:-}" != "deploy" ]; then
  echo "== resources"
  az group create -n "$RG" -l "$LOC" -o none
  az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku F1 -o none
  az webapp create -g "$RG" -p "$PLAN" -n "$API" --runtime "PYTHON:3.13" -o none
  az webapp create -g "$RG" -p "$PLAN" -n "$WEB" --runtime "NODE:24-lts" -o none

  echo "== api settings"
  az webapp config set -g "$RG" -n "$API" -o none \
    --startup-file "python -m uvicorn main:app --host 0.0.0.0 --port 8000"
  az webapp config appsettings set -g "$RG" -n "$API" -o none --settings \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    APP_ENV=production \
    ALLOW_TOKENS_WITHOUT_AZP=false \
    FRONTEND_ORIGIN="$WEB_URL" \
    HEDGE_MODE=shadow \
    ALPACA_BROKER_ID="$ALPACA_BROKER_ID" \
    ALPACA_BROKER_SECRET="$ALPACA_BROKER_SECRET" \
    ALPACA_FIRM_ACCOUNT_ID="$ALPACA_FIRM_ACCOUNT_ID" \
    CLERK_SECRET_KEY="$CLERK_SECRET_KEY" \
    DATABASE_URL="$DATABASE_URL" \
    DATABASE_URL_UNPOOLED="$DATABASE_URL_UNPOOLED" \
    JUP_API_KEY="$JUP_API_KEY" \
    SOLANA_ENGINE_PUBKEY="$SOLANA_ENGINE_PUBKEY" \
    SOLANA_RPC_URL="$SOLANA_RPC_URL"

  echo "== web settings"
  az webapp config set -g "$RG" -n "$WEB" -o none \
    --startup-file "HOSTNAME=0.0.0.0 node server.js"
  az webapp config appsettings set -g "$RG" -n "$WEB" -o none --settings \
    SCM_DO_BUILD_DURING_DEPLOYMENT=false \
    API_URL="$API_URL" \
    CLERK_SECRET_KEY="$CLERK_SECRET_KEY" \
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY" \
    NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in \
    NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up \
    NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/dashboard \
    NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/onboarding
fi

echo "== package"
python scripts/azure/package.py api
( cd app/web && NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY" \
  NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up \
  NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/dashboard \
  NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/onboarding \
  npm run build --silent )
python scripts/azure/package.py web

echo "== deploy api"
az webapp deploy -g "$RG" -n "$API" --src-path build/api.zip --type zip --clean true -o none
echo "== deploy web"
az webapp deploy -g "$RG" -n "$WEB" --src-path build/web.zip --type zip --clean true -o none

echo
echo "api  $API_URL/health"
echo "web  $WEB_URL"
