#!/usr/bin/env zsh
set -euo pipefail

cd "$(dirname "$0")"

git add -A
if git diff-index --quiet HEAD; then
  print "nothing to commit"
else
  git commit -m "deploy"
  git push
  print "committed and pushed"
fi

print "building frontend..."
cd app/ui/client
npm run build 2>&1 | tail -5
cd "$(dirname "$0")"

if ! wrangler_out=$(npx wrangler pages deploy app/ui/client/build \
  --project-name trading-cards-frontend \
  --branch main \
  --commit-dirty=true 2>&1); then
  print "$wrangler_out" | grep -v -E '(⛅|─{3,}|🪵|update available)' | sed '/^[[:space:]]*$/d'
  exit 1
fi

url=$(print "$wrangler_out" | grep -o 'https://[^ ]*pages\.dev' | tail -1)
print "deployed: $url"
