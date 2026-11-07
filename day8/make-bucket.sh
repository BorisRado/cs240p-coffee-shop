#!/bin/bash
# Lab 8, Part 3: makes the shop's orders bucket and puts the orders in it.
# Safe to run twice.
. "$(dirname "$0")/names.sh"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3 mb "s3://$BUCKET" --region eu-central-1 > /dev/null || exit 1
fi
aws s3 cp "$HERE/orders.json" "s3://$BUCKET/orders.json" --quiet || exit 1
echo "Bucket:  $BUCKET"
aws s3 ls "s3://$BUCKET/"
