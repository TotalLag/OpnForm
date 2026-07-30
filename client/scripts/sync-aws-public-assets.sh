#!/usr/bin/env bash
set -euo pipefail

bucket="${1:?pass the shadow public bucket name}"
source_dir="${2:-.output/public}"

if [[ ! "$bucket" =~ ^opnform-ui-shadow-[a-z0-9-]+-assets$ ]] || [[ "$bucket" == *opnform-prod* ]]; then
  echo "Refusing a non-shadow public bucket: $bucket" >&2
  exit 1
fi
test -d "$source_dir"

# Filters apply to deletes too: these two passes cannot delete each other's keys.
aws s3 sync "$source_dir" "s3://$bucket" --delete \
  --exclude '*' --include '_nuxt/*' \
  --cache-control 'public,max-age=31536000,immutable'
aws s3 sync "$source_dir" "s3://$bucket" --delete \
  --exclude '_nuxt/*' \
  --cache-control 'no-store,private,max-age=0'
