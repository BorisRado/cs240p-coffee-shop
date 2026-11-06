#!/bin/bash
# Lab 7, Part 1: build the shop's back end (one time). Safe to run again:
# it skips what already exists. Writes ~/lab-7/env.
set -u
cd "$(dirname "$0")"
mkdir -p ~/lab-7
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
B=cs240p-orders-$ACCOUNT
REGION=${AWS_REGION:-eu-central-1}

fill() { sed -e "s/ACCOUNT/$ACCOUNT/g" -e "s/BUCKET/$B/g" "$1"; }

echo "1/4  KMS key alias/coffee-orders"
KEY_ID=$(aws kms describe-key --key-id alias/coffee-orders \
  --query KeyMetadata.KeyId --output text 2>/dev/null)
if [ -z "$KEY_ID" ] || [ "$KEY_ID" = None ]; then
  KEY_ID=$(aws kms create-key --description "cs240p coffee orders" \
    --query KeyMetadata.KeyId --output text)
  aws kms create-alias --alias-name alias/coffee-orders \
    --target-key-id "$KEY_ID"
fi

echo "2/4  role coffee-app (broad s3:* for now) and instance profile"
aws iam get-role --role-name coffee-app >/dev/null 2>&1 || \
  aws iam create-role --role-name coffee-app \
    --assume-role-policy-document file://trust-ec2.json >/dev/null
aws iam put-role-policy --role-name coffee-app --policy-name app \
  --policy-document file://coffee-app-broad.json
aws iam get-instance-profile --instance-profile-name coffee-app \
  >/dev/null 2>&1 || {
  aws iam create-instance-profile \
    --instance-profile-name coffee-app >/dev/null
  aws iam add-role-to-instance-profile \
    --instance-profile-name coffee-app --role-name coffee-app
}

echo "3/4  let coffee-app use the key"
fill key-policy.json > /tmp/key-policy.json
# A just-created role can take a few seconds to be visible to KMS.
for try in 1 2 3 4 5 6 7 8; do
  aws kms put-key-policy --key-id "$KEY_ID" --policy-name default \
    --policy file:///tmp/key-policy.json 2>/tmp/kms.err && break
  echo "   waiting for the role to propagate ($try)..."; sleep 5
done
grep -q . /tmp/kms.err 2>/dev/null && cat /tmp/kms.err

echo "4/4  bucket $B, encrypted with the key"
aws s3api head-bucket --bucket "$B" >/dev/null 2>&1 || \
  aws s3api create-bucket --bucket "$B" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
aws s3api put-bucket-encryption --bucket "$B" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSide'\
'EncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":'\
'"alias/coffee-orders"}}]}'

declare -p ACCOUNT B KEY_ID REGION > ~/lab-7/env
echo "done. bucket=$B  key=$KEY_ID"
