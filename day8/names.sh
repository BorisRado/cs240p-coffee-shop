# Sourced by the scripts of Lab 8. Finds the names of today's things.
# Signed in as admin (your own account): coffee-menu, coffee-orders-<id>.
# Any other user (the TA account): the names end with -<user name>.
# You can also load it in your own shell, ". ./names.sh", to get $FN,
# $BUCKET and $URL there.
if ! ARN=$(aws sts get-caller-identity --query Arn --output text); then
  echo "Cannot find who you are. Are you in CloudShell?"
  return 1 2>/dev/null || exit 1
fi
ACCOUNT=$(echo "$ARN" | cut -d: -f5)
ME=${ARN##*/}
if [ "$ME" = admin ] || [ "${ARN##*:}" = root ]; then
  SUFFIX=""
else
  SUFFIX="-$ME"
fi
FN=coffee-menu$SUFFIX
BUCKET=coffee-orders-$ACCOUNT${SUFFIX,,}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LOG=$HERE/results.log
export AWS_REGION=${AWS_REGION:-eu-central-1}

function_url() {
  aws lambda get-function-url-config --function-name "$FN" \
    --query FunctionUrl --output text 2>/dev/null
}
URL=$(function_url)
