#!/bin/bash
# Lab 8, Part 4: deletes what today made: the function (if it is still
# there), its role and the role's policy, its log group, and the orders
# bucket. Touches only today's names. Safe to run twice.
. "$(dirname "$0")/names.sh"

if aws lambda get-function --function-name "$FN" > /dev/null 2>&1; then
  aws lambda delete-function --function-name "$FN" \
    && echo "Deleted the function $FN"
fi

for ROLE in $(aws iam list-roles --path-prefix /service-role/ --output text \
    --query "Roles[?starts_with(RoleName, '$FN-role-')].RoleName"); do
  for P in $(aws iam list-attached-role-policies --role-name "$ROLE" \
      --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$P"
    case "$P" in
      arn:aws:iam::aws:*) ;;   # an AWS policy: it is not yours to delete
      *) aws iam delete-policy --policy-arn "$P" \
           && echo "Deleted the policy ${P##*/}" ;;
    esac
  done
  for P in $(aws iam list-role-policies --role-name "$ROLE" \
      --query 'PolicyNames[]' --output text); do
    aws iam delete-role-policy --role-name "$ROLE" --policy-name "$P"
  done
  aws iam delete-role --role-name "$ROLE" && echo "Deleted the role $ROLE"
done

if aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/$FN" \
    --query "logGroups[?logGroupName=='/aws/lambda/$FN'].logGroupName" \
    --output text | grep -q .; then
  aws logs delete-log-group --log-group-name "/aws/lambda/$FN" \
    && echo "Deleted the log group /aws/lambda/$FN"
fi

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3 rb "s3://$BUCKET" --force > /dev/null \
    && echo "Deleted the bucket $BUCKET"
fi

rm -f "$HERE/stolen-keys.txt"
echo "Clean-up done."
