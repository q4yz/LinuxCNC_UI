#!/bin/bash
# Install / update a board from a CI build — any branch, not only releases.
#
# Every CI run uploads the built frontend as the artifact
# "linuxcnc-ui-dist" (.github/workflows/ci.yml, job frontend). This
# script downloads it, clones (or fetches) the backend source, checks out
# exactly the commit the artifact was built from and runs the deploy
# scripts — nothing is compiled on the board (1 GB boards like the CB1).
#
#   install_artifact.sh <artifact-url> [--dir <project dir>] [--full]
#
#   <artifact-url>  https://github.com/<owner>/<repo>/actions/runs/<run>/artifacts/<id>
#   --dir           the checkout (default: ~/<repo>); cloned when missing
#   --full          run install.sh even on an installed board (new apt packages,
#                   systemd units, nginx site); a first install always does
#
# Self-contained, so it also runs from the PC over SSH without a checkout:
#
#   ssh pi@cb1 "GITHUB_TOKEN=$(gh auth token) bash -s -- <artifact-url>" < scripts/install_artifact.sh
#
# (updates only: a first install runs `sudo ./install.sh`, whose password
# prompt needs a terminal — scp the script and run it with `ssh -t`.)
#
# GitHub serves artifacts only to authenticated requests, even on a public
# repository. The token (read access to Actions of the repo) comes from
# $GITHUB_TOKEN, $GH_TOKEN, `gh auth token` or ~/.config/linuxcnc-ui/github-token.
# Run as the normal user, never with sudo: the first install asks for
# sudo itself, everything in the project tree belongs to the user.
set -e

if [ "$EUID" -eq 0 ]; then
    echo "Error: do not run as root; run as the user that owns the project (sudo is asked for when needed)." >&2
    exit 1
fi

ARTIFACT_URL=""
PROJECT_DIR=""
FULL_INSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dir)  PROJECT_DIR="$2"; shift 2 ;;
        --full) FULL_INSTALL=1; shift ;;
        -*) echo "Error: unknown option '$1'" >&2; exit 2 ;;
        *)  ARTIFACT_URL="$1"; shift ;;
    esac
done

URL_PATTERN='^https://github\.com/([^/]+)/([^/]+)/actions/runs/([0-9]+)/artifacts/([0-9]+)/?$'
if [[ ! "$ARTIFACT_URL" =~ $URL_PATTERN ]]; then
    echo "usage: install_artifact.sh https://github.com/<owner>/<repo>/actions/runs/<run>/artifacts/<id> [--dir <dir>] [--full]" >&2
    exit 2
fi
OWNER="${BASH_REMATCH[1]}"
REPO="${BASH_REMATCH[2]}"
RUN_ID="${BASH_REMATCH[3]}"
ARTIFACT_ID="${BASH_REMATCH[4]}"
API="https://api.github.com/repos/$OWNER/$REPO"
PROJECT_DIR="${PROJECT_DIR:-$HOME/$REPO}"

for tool in git curl python3 tar sha256sum; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "Error: '$tool' is missing. Install it once with: sudo apt-get install -y git curl python3 tar coreutils" >&2
        exit 1
    fi
done

TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"
if [ -z "$TOKEN" ] && command -v gh > /dev/null 2>&1; then
    TOKEN="$(gh auth token 2>/dev/null || true)"
fi
if [ -z "$TOKEN" ] && [ -f "$HOME/.config/linuxcnc-ui/github-token" ]; then
    TOKEN="$(tr -d '[:space:]' < "$HOME/.config/linuxcnc-ui/github-token")"
fi
if [ -z "$TOKEN" ]; then
    echo "Error: GitHub serves artifacts only with a token. Set GITHUB_TOKEN (read access to the repo's Actions)" >&2
    echo "       or put it in ~/.config/linuxcnc-ui/github-token." >&2
    exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

github() {
    # github <url> [curl args...] — the token goes through stdin, never the
    # command line (visible in ps). curl drops it on the redirect to the
    # blob storage host.
    local url="$1"; shift
    printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" \
        | curl -fsSL --retry 3 -K - -H "Accept: application/vnd.github+json" \
               -H "X-GitHub-Api-Version: 2022-11-28" "$@" "$url"
}

echo "---> Checking artifact $ARTIFACT_ID of $OWNER/$REPO run $RUN_ID..."
github "$API/actions/artifacts/$ARTIFACT_ID" -o "$WORK_DIR/artifact.json" || {
    echo "Error: could not read the artifact (wrong URL, or the token has no access to $OWNER/$REPO)" >&2
    exit 1
}
python3 -I - "$WORK_DIR/artifact.json" "$RUN_ID" << 'EOF'
import json, sys
info = json.load(open(sys.argv[1]))
run = str((info.get("workflow_run") or {}).get("id"))
if info.get("name") != "linuxcnc-ui-dist":
    sys.exit(f"Error: artifact '{info.get('name')}' is not the frontend package 'linuxcnc-ui-dist'")
if run != sys.argv[2]:
    sys.exit(f"Error: the artifact belongs to run {run}, not {sys.argv[2]}")
if info.get("expired"):
    sys.exit("Error: the artifact has expired (CI keeps it 14 days) — re-run the workflow")
EOF

echo "---> Downloading the frontend package..."
github "$API/actions/artifacts/$ARTIFACT_ID/zip" -o "$WORK_DIR/artifact.zip"
python3 -I -m zipfile -e "$WORK_DIR/artifact.zip" "$WORK_DIR/artifact"
(cd "$WORK_DIR/artifact" && sha256sum -c linuxcnc-ui-dist.tar.gz.sha256)

# Keep the tarball outside the temp dir until the deploy scripts ran.
DIST_TARBALL="$(mktemp --suffix=-linuxcnc-ui-dist.tar.gz)"
trap 'rm -rf "$WORK_DIR" "$DIST_TARBALL"' EXIT
cp "$WORK_DIR/artifact/linuxcnc-ui-dist.tar.gz" "$DIST_TARBALL"
COMMIT="$(tar -xzOf "$DIST_TARBALL" ./release.json | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["commit"])')"
echo "Artifact built from commit $COMMIT"

echo "---> Backend source in $PROJECT_DIR..."
if [ ! -d "$PROJECT_DIR/.git" ]; then
    git clone "https://github.com/$OWNER/$REPO.git" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

if pgrep -x "linuxcnc" > /dev/null || pgrep -x "emc" > /dev/null; then
    echo "Error: LinuxCNC is currently running. Please stop LinuxCNC first." >&2
    exit 1
fi

# The deploy scripts of the artifact's own commit run below, so check it
# out first. A pull-request build is a merge commit no branch contains —
# GitHub still serves it by its id.
git fetch --force --tags origin
if ! git cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
    git fetch origin "$COMMIT"
fi
CURRENT_BRANCH="$(git symbolic-ref --short -q HEAD || true)"
if [ -n "$CURRENT_BRANCH" ]; then
    # "Build newest commit" returns to this branch later (scripts/update.sh).
    mkdir -p backend/data
    echo "$CURRENT_BRANCH" > backend/data/update_branch
fi
git checkout --detach "$COMMIT"

if [ "$FULL_INSTALL" -eq 1 ] || [ ! -f /etc/systemd/system/linuxcnc-ui-system.service ] || [ ! -d backend/venv ]; then
    echo "---> Full install (asks for sudo)..."
    sudo ./install.sh --dist "$DIST_TARBALL"
else
    echo "---> Updating the installed board..."
    bash scripts/update.sh --mode dist --dist "$DIST_TARBALL"
fi
