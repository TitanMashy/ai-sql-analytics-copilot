#!/usr/bin/env bash
# Deployment hook used by the release workflow.
#
#   scripts/deploy.sh <environment> <version>      e.g.  scripts/deploy.sh staging 1.2.0
#
# The repository cannot know where you deploy, so this script delegates to a platform-specific
# script that you provide at scripts/deploy.d/<environment>.sh (for example one that runs
# `kubectl set image`, `helm upgrade`, or `docker compose pull && up` over SSH). The delegate
# receives the environment and the version as arguments and must:
#   1. run the migration job for that version and wait for it to succeed,
#   2. roll the backend and frontend to the immutable image tags for that version,
#   3. exit non-zero if any step fails.
# Without a delegate this script fails loudly: a release must never look deployed when nothing was.
set -euo pipefail

ENVIRONMENT="${1:?usage: deploy.sh <environment> <version>}"
VERSION="${2:?usage: deploy.sh <environment> <version>}"
HOOK="$(dirname "$0")/deploy.d/${ENVIRONMENT}.sh"

if [[ ! -x "${HOOK}" ]]; then
  echo "No deployment hook for '${ENVIRONMENT}': create an executable ${HOOK}" >&2
  echo "See docs/operations.md, 'Release process'." >&2
  exit 78
fi
exec "${HOOK}" "${ENVIRONMENT}" "${VERSION}"
