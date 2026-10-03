#!/usr/bin/env bash
# rollback.sh — restore the previous digest lock and relaunch the stack.
# Only reverts the IMAGE pins. It does not touch overlay/*.yml or vendored
# upstream files (those are the business of a `git checkout` + redeploy).
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -s overlay/.digests.lock.prev ]; then
  echo "no overlay/.digests.lock.prev — nothing to roll back to" >&2
  exit 1
fi
mv overlay/.digests.lock      overlay/.digests.lock.failed
mv overlay/.digests.lock.prev overlay/.digests.lock
bin/compose-up.sh
echo "rolled back to previous digest-pin. Failed lock kept at overlay/.digests.lock.failed for triage."
