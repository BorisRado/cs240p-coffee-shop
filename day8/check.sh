#!/bin/bash
# The final check of Lab 8: what is left in the account (it must be
# nothing), then what you did, read from results.log.
. "$(dirname "$0")/names.sh"

aws lambda get-function --function-name "$FN" > /dev/null 2>&1 \
  && FUNC="still there" || FUNC=deleted
ROLES=$(aws iam list-roles --path-prefix /service-role/ --output text \
  --query "length(Roles[?starts_with(RoleName, '$FN-role-')])")
aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null \
  && BKT="still there" || BKT=deleted
GROUPS_LEFT=$(aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/$FN" --output text \
  --query "length(logGroups[?logGroupName=='/aws/lambda/$FN'])")

touch "$LOG"
CALLS=$(grep -c 'one-by-one .*status=200' "$LOG")
RUSH=$(grep 'at-once' "$LOG" | tail -n 1 | cut -d' ' -f3-)
# Each step must come after the one before it, so look at the order.
STEPS=$(grep -E ' (steal|as-menu) ' "$LOG" | python3 -c '
import sys
stole = read = denied = refused = "no"
for line in sys.stdin:
    w = line.split()
    s3 = " s3 " in " " + " ".join(w[3:]) + " " or "s3api" in w[3:]
    if w[1:3] == ["steal", "ok"]:
        stole = "yes"
    elif w[1:3] == ["steal", "refused"] and stole == "yes":
        refused = "yes"
    elif w[1:3] == ["as-menu", "ok"] and s3:
        read = "yes"
    elif w[1:3] == ["as-menu", "denied"] and s3 and read == "yes":
        denied = "yes"
print(stole, read, denied, refused)
')
set -- $STEPS

echo "Date (UTC):            $(date -u '+%d %b %Y %H:%M')"
echo "Signed in as:          $ARN"
echo "Region:                $AWS_REGION"
echo "Function $FN:  $FUNC"
echo "Roles left:            $ROLES"
echo "Orders bucket:         $BKT"
echo "Log group:             $([ "$GROUPS_LEFT" = 0 ] && echo deleted \
  || echo 'still there')"
echo "Menu calls (Part 1):   $CALLS served"
echo "Rush (Part 2):         ${RUSH:-not run}"
echo "Keys stolen:           $1"
echo "Stolen keys read S3:   $2"
echo "After the role fix:    $([ "$3" = yes ] && echo AccessDenied \
  || echo 'not tested')"
echo "After the code fix:    $([ "$4" = yes ] && echo 'file:// refused' \
  || echo 'not tested')"
