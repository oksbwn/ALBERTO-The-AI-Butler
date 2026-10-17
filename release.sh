#!/usr/bin/env bash
# ==============================================================================
# Alberto Release Automation Script
# Single supported entry point for official Alberto releases.
# ==============================================================================

set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ------------------------------------------------------------------------------
# 1. Argument Parsing & Usage
# ------------------------------------------------------------------------------
usage() {
  local code="${1:-1}"
  echo "Alberto Release Automation"
  echo "Usage: ./release.sh <patch|minor|major> [--dry-run]"
  echo ""
  echo "Commands:"
  echo "  patch      Increment patch version (e.g., 0.1.0 -> 0.1.1)"
  echo "  minor      Increment minor version (e.g., 0.1.0 -> 0.2.0)"
  echo "  major      Increment major version (e.g., 0.1.0 -> 1.0.0)"
  echo ""
  echo "Options:"
  echo "  --dry-run  Validate checks and simulate release without making changes"
  echo "  --help, -h Show this help message"
  exit "$code"
}

if [[ $# -lt 1 ]]; then
  usage 1
fi

INCREMENT_TYPE=""
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    patch|minor|major)
      if [[ -n "$INCREMENT_TYPE" ]]; then
        echo "Error: Multiple release increment types specified: $INCREMENT_TYPE and $arg" >&2
        exit 1
      fi
      INCREMENT_TYPE="$arg"
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --help|-h)
      usage 0
      ;;
    *)
      echo "Error: Unknown argument: $arg" >&2
      usage
      ;;
  esac
done

if [[ -z "$INCREMENT_TYPE" ]]; then
  echo "Error: You must specify a release increment type (patch, minor, or major)." >&2
  usage
fi

echo "============================================================"
echo " Alberto Release Pipeline"
echo " Increment type : $INCREMENT_TYPE"
echo " Dry run        : $DRY_RUN"
echo "============================================================"

# ------------------------------------------------------------------------------
# 2. Mandatory Preflight Checks
# ------------------------------------------------------------------------------
echo ""
echo "--> [1/4] Running Preflight Safeguards..."

# Check detached HEAD
if ! git symbolic-ref -q HEAD >/dev/null; then
  echo "❌ Error: Detached HEAD detected. Releases must be performed on the 'master' branch." >&2
  exit 1
fi

# Check branch is exactly master
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "master" ]]; then
  echo "❌ Error: Releases are strictly allowed only on branch 'master' (current branch: '$CURRENT_BRANCH')." >&2
  echo "   Terminating release process. Checkout 'master' manually to proceed." >&2
  exit 1
fi
echo "    ✓ Current branch is 'master'"

# Check git working tree and staging area are clean
if ! git diff --quiet; then
  echo "❌ Error: Git working tree contains unstaged changes. Repository must be clean." >&2
  git status --short >&2
  exit 1
fi

if ! git diff --cached --quiet; then
  echo "❌ Error: Git staging area contains uncommitted changes. Repository must be clean." >&2
  git status --short >&2
  exit 1
fi

UNTRACKED="$(git status --porcelain | grep '^??' || true)"
if [[ -n "$UNTRACKED" ]]; then
  echo "❌ Error: Untracked files present in repository:" >&2
  echo "$UNTRACKED" >&2
  exit 1
fi
echo "    ✓ Git working tree and staging area are clean"

# Check remote origin exists
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "❌ Error: Git remote 'origin' does not exist." >&2
  exit 1
fi
echo "    ✓ Remote 'origin' is configured"

# Fetch latest origin/master and tags
echo "    Fetching remote updates and tags from origin..."
git fetch origin master --tags --quiet || {
  echo "❌ Error: Failed to fetch from remote origin. Check network or credentials." >&2
  exit 1
}

# Verify local master is synchronized with origin/master
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/master)"
if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
  echo "❌ Error: Local master ($LOCAL_SHA) is not synchronized with origin/master ($REMOTE_SHA)." >&2
  BEHIND="$(git rev-list --count HEAD..origin/master)"
  AHEAD="$(git rev-list --count origin/master..HEAD)"
  echo "   Local master is $AHEAD commit(s) ahead, $BEHIND commit(s) behind origin/master." >&2
  exit 1
fi
echo "    ✓ Local master is synchronized with origin/master ($LOCAL_SHA)"

# Validate version.json
VERSION_FILE="$REPO_ROOT/version.json"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "❌ Error: Canonical version file '$VERSION_FILE' not found." >&2
  exit 1
fi

# Discover Python interpreter for JSON parsing & validation
if [[ -n "$VIRTUAL_ENV" && -f "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -n "$VIRTUAL_ENV" && -f "$VIRTUAL_ENV/Scripts/python.exe" ]]; then
  PYTHON="$VIRTUAL_ENV/Scripts/python.exe"
elif [[ -f "$REPO_ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/backend/.venv/bin/python"
elif [[ -f "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]]; then
  PYTHON="$REPO_ROOT/backend/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "❌ Error: Python not found for version parsing." >&2
  exit 1
fi

CURRENT_VERSION="$("$PYTHON" -c "
import json, sys, re
try:
    with open('version.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('version', '')
    t = data.get('tag', '')
    if not re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', v):
        sys.stderr.write(f'Invalid semver in version.json: {v}\n')
        sys.exit(1)
    if t != f'v{v}':
        sys.stderr.write(f'Version/tag mismatch in version.json: version={v}, tag={t}\n')
        sys.exit(1)
    print(v)
except Exception as e:
    sys.stderr.write(f'Error reading {e}\n')
    sys.exit(1)
")"

if [[ $? -ne 0 || -z "$CURRENT_VERSION" ]]; then
  echo "❌ Error: version.json is invalid or internally inconsistent." >&2
  exit 1
fi
echo "    ✓ Current canonical version: $CURRENT_VERSION (tag: v$CURRENT_VERSION)"

# Calculate proposed new version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$INCREMENT_TYPE" in
  patch)
    NEXT_PATCH=$((PATCH + 1))
    NEXT_VERSION="${MAJOR}.${MINOR}.${NEXT_PATCH}"
    ;;
  minor)
    NEXT_MINOR=$((MINOR + 1))
    NEXT_VERSION="${MAJOR}.${NEXT_MINOR}.0"
    ;;
  major)
    NEXT_MAJOR=$((MAJOR + 1))
    NEXT_VERSION="${NEXT_MAJOR}.0.0"
    ;;
esac

NEXT_TAG="v${NEXT_VERSION}"
echo "    Proposed next version: $NEXT_VERSION (tag: $NEXT_TAG)"

# Check if proposed tag already exists locally
if git rev-parse "$NEXT_TAG" >/dev/null 2>&1; then
  echo "❌ Error: Git tag '$NEXT_TAG' already exists locally." >&2
  exit 1
fi

# Check if proposed tag already exists remotely
if git ls-remote --tags origin "refs/tags/$NEXT_TAG" | grep -q "$NEXT_TAG"; then
  echo "❌ Error: Git tag '$NEXT_TAG' already exists on remote 'origin'." >&2
  exit 1
fi
echo "    ✓ Release tag '$NEXT_TAG' is available both locally and remotely"

# Check required quality script
if [[ ! -f "$REPO_ROOT/tests/check.sh" ]]; then
  echo "❌ Error: Quality check script '$REPO_ROOT/tests/check.sh' not found." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 3. Dry-Run Check / Quality Validation
# ------------------------------------------------------------------------------
if [[ "$DRY_RUN" == true ]]; then
  echo ""
  echo "============================================================"
  echo " DRY-RUN MODE: Simulating Release Process"
  echo "============================================================"
  echo " Current Version   : $CURRENT_VERSION (v$CURRENT_VERSION)"
  echo " Target Version    : $NEXT_VERSION ($NEXT_TAG)"
  echo " Branch Target     : master -> origin/master"
  echo " Validation Action : Would execute ./tests/check.sh"
  echo " Mutation Action   : Would update version.json to version: $NEXT_VERSION, tag: $NEXT_TAG"
  echo " Git Commit Action : chore(release): $NEXT_TAG"
  echo " Git Tag Action    : Annotated tag $NEXT_TAG"
  echo " Git Push Action   : Atomic push to origin master and tag $NEXT_TAG"
  echo ""
  echo "✓ DRY RUN COMPLETED SUCCESSFULLY."
  echo "  No files were modified."
  echo "  No commits were made."
  echo "  No Git tags were created."
  echo "  No remote updates were performed."
  echo "============================================================"
  exit 0
fi

echo ""
echo "--> [2/4] Executing Mandatory Quality Gate (tests/check.sh)..."
if ! "$REPO_ROOT/tests/check.sh"; then
  echo ""
  echo "❌ Error: Quality checks failed! Release has been ABORTED." >&2
  echo "   No files were modified, no commit was created, no tag was created, nothing was pushed." >&2
  exit 1
fi
echo "    ✓ Mandatory quality gate passed completely."

# ------------------------------------------------------------------------------
# 4. Final Safety Recheck Before Release Mutation
# ------------------------------------------------------------------------------
echo ""
echo "--> [3/4] Re-verifying Repository State..."
CHECK_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CHECK_BRANCH" != "master" ]]; then
  echo "❌ Error: Branch changed unexpectedly during quality checks (now '$CHECK_BRANCH'). Aborting." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "❌ Error: Working tree became dirty during quality checks. Aborting." >&2
  git status --short >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 5. Version Update, Commit, Tag, Push
# ------------------------------------------------------------------------------
echo ""
echo "--> [4/4] Executing Official Release Sequence for $NEXT_TAG..."

# Update version.json
"$PYTHON" -c "
import json
with open('version.json', 'w', encoding='utf-8') as f:
    json.dump({'version': '$NEXT_VERSION', 'tag': '$NEXT_TAG'}, f, indent=2)
    f.write('\n')
"

# Validate new version.json
"$PYTHON" -c "
import json
with open('version.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
assert data['version'] == '$NEXT_VERSION'
assert data['tag'] == '$NEXT_TAG'
"

# Stage only version.json
git add version.json

# Commit
git commit -m "chore(release): $NEXT_TAG"

# Create annotated tag
git tag -a "$NEXT_TAG" -m "Release $NEXT_TAG"

# Atomic Push
echo "    Pushing release commit and tag to origin..."
if ! git push --atomic origin master "$NEXT_TAG"; then
  echo ""
  echo "⚠️ Warning: Atomic push failed or unsupported by remote. Attempting safe branch push then tag push..." >&2
  if git push origin master; then
    if git push origin "$NEXT_TAG"; then
      echo "    ✓ Non-atomic fallback push succeeded."
    else
      echo "❌ CRITICAL: Pushed release commit to origin/master, but failed to push tag '$NEXT_TAG'." >&2
      echo "   Local commit: $(git rev-parse HEAD)"
      echo "   To recover, push the tag manually: git push origin $NEXT_TAG" >&2
      exit 1
    fi
  else
    echo "❌ CRITICAL: Failed to push release commit to origin/master." >&2
    echo "   Local commit: $(git rev-parse HEAD)"
    echo "   Tag: $NEXT_TAG (local only)"
    echo "   To undo local release commit and tag:" >&2
    echo "     git tag -d $NEXT_TAG" >&2
    echo "     git reset --hard origin/master" >&2
    exit 1
  fi
fi

FINAL_SHA="$(git rev-parse HEAD)"

echo ""
echo "============================================================"
echo " 🎉 ALBERTO RELEASE SUCCESSFUL!"
echo " Version    : $NEXT_VERSION"
echo " Tag        : $NEXT_TAG"
echo " Commit SHA : $FINAL_SHA"
echo " Branch     : master"
echo " Remote     : origin"
echo "============================================================"
