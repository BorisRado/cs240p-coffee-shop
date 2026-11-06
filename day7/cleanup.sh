#!/bin/bash
# Lab 7, Part 9: delete everything this lab made. Safe to run again.
set -u
source ~/lab-7/env 2>/dev/null || {
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
  B=cs240p-orders-$ACCOUNT; }

echo "- bucket $B"
aws s3 rb s3://$B --force >/dev/null 2>&1 && echo "  deleted" || echo "  gone"

echo "- role menu-reader"
aws iam delete-role-policy --role-name menu-reader --policy-name read \
  2>/dev/null
aws iam delete-role --role-name menu-reader 2>/dev/null && echo "  deleted" \
  || echo "  gone"

echo "- role coffee-app and its instance profile"
aws iam remove-role-from-instance-profile \
  --instance-profile-name coffee-app --role-name coffee-app 2>/dev/null
aws iam delete-instance-profile --instance-profile-name coffee-app 2>/dev/null
aws iam delete-role-policy --role-name coffee-app --policy-name app 2>/dev/null
aws iam delete-role --role-name coffee-app 2>/dev/null && echo "  deleted" \
  || echo "  gone"

echo "- KMS key alias/coffee-orders (7-day waiting period)"
# KEY_ID comes from ~/lab-7/env; the alias is the fallback. Using the ID
# means a second run still finds the key after the alias is deleted.
[ -n "${KEY_ID:-}" ] || KEY_ID=$(aws kms describe-key \
  --key-id alias/coffee-orders --query KeyMetadata.KeyId --output text \
  2>/dev/null)
STATE=$(aws kms describe-key --key-id "${KEY_ID:-none}" \
  --query KeyMetadata.KeyState --output text 2>/dev/null)
aws kms delete-alias --alias-name alias/coffee-orders 2>/dev/null
case "$STATE" in
  PendingDeletion) echo "  deletion scheduled" ;;
  Enabled|Disabled)
    aws kms schedule-key-deletion --key-id "$KEY_ID" \
      --pending-window-in-days 7 >/dev/null && echo "  deletion scheduled" ;;
  *) echo "  gone" ;;
esac
