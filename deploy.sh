#!/usr/bin/env bash
# ==============================================================================
# deploy.sh - 1-Click Deployment & Data Synchronization Pipeline for N890GF Tracker
#
# Usage:
#   ./deploy.sh                  # Interactive verification, 2-way sync, testing & deploy
#   ./deploy.sh -m "commit msg"  # Auto-commit tracked changes and deploy
#   ./deploy.sh --skip-tests     # Deploy skipping local pytest suite
#   ./deploy.sh --skip-sync      # Skip harvesting server data before deploying
#   ./deploy.sh --dry-run        # Preview all deployment steps without changing state
# ==============================================================================
set -euo pipefail

# --- Configuration -------------------------------------------------------------
SERVER="georgefahmy@192.168.68.89"
REMOTE_DIR="/home/georgefahmy/Documents/n890gf_tracker/flask-tracker"
SERVICE="flask-tracker"
DOMAIN="https://log.n890gf.com"
LOCAL_VENV="${HOME}/.virtualenvs/tracker/bin/python3"

# --- Colors & Formatting -------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${NC}"; }
error()   { echo -e "${RED}❌ $*${NC}" >&2; }
step()    { echo -e "\n${BOLD}${BLUE}==> $*${NC}"; }

# --- Argument Parsing ----------------------------------------------------------
SKIP_TESTS=false
SKIP_SYNC=false
DRY_RUN=false
COMMIT_MSG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--commit)
      COMMIT_MSG="$2"
      shift 2
      ;;
    -s|--skip-tests)
      SKIP_TESTS=true
      shift
      ;;
    --skip-sync)
      SKIP_SYNC=true
      shift
      ;;
    -n|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      cat << 'EOF'
Usage: ./deploy.sh [OPTIONS]

Options:
  -m, --commit "MESSAGE"   Commit all local staged/unstaged changes before deploying
  -s, --skip-tests         Skip running local pytest suite
  --skip-sync              Skip pre-deploy sync of server-generated data
  -n, --dry-run            Simulate deployment without modifying local or remote state
  -h, --help               Show this help message
EOF
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      exit 1
      ;;
  esac
done

START_TIME=$(date +%s)
echo -e "${BOLD}======================================================${NC}"
echo -e "${BOLD}       🛩️  N890GF Tracker Deployment Pipeline          ${NC}"
echo -e "${BOLD}======================================================${NC}"

# --- Step 1: Pre-flight Verification -------------------------------------------
step "[1/6] Pre-flight verification..."

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
info "Current branch: ${BOLD}${CURRENT_BRANCH}${NC}"

if [[ "$CURRENT_BRANCH" != "main" ]]; then
  warn "You are currently on branch '${CURRENT_BRANCH}', not 'main'."
  read -r -p "Continue deploying '${CURRENT_BRANCH}' to production? (y/N) " confirm_branch
  if [[ ! "$confirm_branch" =~ ^[Yy]$ ]]; then
    error "Deployment aborted by user."
    exit 1
  fi
fi

# Pre-flight check SSH connectivity to the server
if [[ "$DRY_RUN" = false ]]; then
  if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SERVER" "true" 2>/dev/null; then
    error "Unable to establish SSH connection to $SERVER. Check network or SSH keys."
    exit 1
  fi
  success "SSH connection verified to $SERVER."
fi

# --- Step 2: Harvest & Preserve Server Data ------------------------------------
step "[2/6] Preserving & syncing server-generated data (Aerofuel IQ, Cache, DB)..."

if [[ "$SKIP_SYNC" = true ]]; then
  warn "Skipping server data harvest (--skip-sync)."
elif [[ "$DRY_RUN" = true ]]; then
  info "[DRY-RUN] SSH into $SERVER: commit uncommitted data in data/aerofuel, clean_flights, fuel_prices, src/maintenance.db"
  info "[DRY-RUN] Push server data to GitHub, then git pull --rebase locally"
else
  info "Checking for new server-generated data on production..."
  ssh "$SERVER" "bash -s" <<EOF
set -euo pipefail
cd "$REMOTE_DIR"

# 1. Sync live database if present in instance/
if [ -f "instance/maintenance.db" ]; then
    cp instance/maintenance.db src/maintenance.db 2>/dev/null || true
fi

# 2. Stage server data changes (all data/, fuel prices, flight cache, DB)
git add data/ fuel_prices/ clean_flights/ src/maintenance.db 2>/dev/null || true

# 3. Commit if any data files were updated on the server
if ! git diff --cached --quiet; then
    echo "💾 New data detected on server. Creating sync commit..."
    git commit -m "Auto update: sync server data and fuel cache [skip ci]"
else
    echo "ℹ️  No uncommitted server data changes."
fi

# 4. Fetch latest from GitHub and rebase any server data commits on top with autostash
git fetch origin "$CURRENT_BRANCH" -q
git rebase --autostash "origin/$CURRENT_BRANCH"

# 5. Check if server has commits ahead of GitHub to push
COMMITS_AHEAD=\$(git rev-list --count "origin/$CURRENT_BRANCH..HEAD")
if [ "\$COMMITS_AHEAD" -gt 0 ]; then
    echo "📤 Pushing \$COMMITS_AHEAD server data commit(s) to GitHub..."
    git push origin "$CURRENT_BRANCH"
    echo "✅ Server data pushed to GitHub."
else
    echo "ℹ️  Server is in sync with GitHub."
fi
EOF

  # Pull server data to local repo using rebase with autostash
  info "Pulling server data updates to local repository..."
  git pull --rebase --autostash origin "$CURRENT_BRANCH"
  success "Local repository is up-to-date with all server data."
fi

# --- Step 3: Local Git Commit --------------------------------------------------
step "[3/6] Checking local changes..."

if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git status --porcelain)" ]]; then
  if [[ -n "$COMMIT_MSG" ]]; then
    info "Auto-committing local changes with message: \"$COMMIT_MSG\"..."
    if [[ "$DRY_RUN" = true ]]; then
      info "[DRY-RUN] git add -A && git commit -m \"$COMMIT_MSG\""
    else
      git add -A
      git commit -m "$COMMIT_MSG"
      success "Committed local changes."
    fi
  else
    warn "Uncommitted changes detected in local working tree:"
    git status --short
    echo ""
    read -r -p "Would you like to commit all changes before deploying? (y/N/q) " confirm_commit
    case "$confirm_commit" in
      [Yy]*)
        read -r -p "Enter commit message: " user_commit_msg
        if [[ -z "$user_commit_msg" ]]; then
          error "Commit message cannot be empty. Aborting."
          exit 1
        fi
        if [[ "$DRY_RUN" = true ]]; then
          info "[DRY-RUN] git add -A && git commit -m \"$user_commit_msg\""
        else
          git add -A
          git commit -m "$user_commit_msg"
          success "Committed local changes."
        fi
        ;;
      [Qq]*)
        error "Deployment cancelled."
        exit 1
        ;;
      *)
        error "Cannot deploy with uncommitted changes. Please commit or stash them first."
        exit 1
        ;;
    esac
  fi
else
  success "Local working tree is clean."
fi

# --- Step 4: Automated Local Testing -------------------------------------------
step "[4/6] Running automated test suite..."

if [[ "$SKIP_TESTS" = true ]]; then
  warn "Skipping tests as requested (--skip-tests)."
else
  if [[ -x "$LOCAL_VENV" ]]; then
    PYTHON_EXEC="$LOCAL_VENV"
  else
    PYTHON_EXEC="python3"
  fi
  info "Running pytest using: $PYTHON_EXEC"

  if [[ "$DRY_RUN" = true ]]; then
    info "[DRY-RUN] $PYTHON_EXEC -m pytest"
  else
    if ! "$PYTHON_EXEC" -m pytest; then
      error "Tests failed! Aborting deployment to prevent breaking production."
      exit 1
    fi
    success "All tests passed successfully!"
    # Revert test-generated cache file timestamp touches
    git checkout -- clean_flights/.cache/test_cache_flight.csv.pkl.gz data/aerofuel/.airnav_cache/ 2>/dev/null || true
  fi
fi

# --- Step 5: Push to GitHub & Sync Server --------------------------------------
step "[5/6] Pushing code & deploying to production ($SERVER)..."

if [[ "$DRY_RUN" = true ]]; then
  info "[DRY-RUN] git push origin $CURRENT_BRANCH"
  info "[DRY-RUN] SSH into $SERVER, git pull --rebase, restart $SERVICE"
else
  # Push local commits
  info "Pushing latest commits to GitHub..."
  git push origin "$CURRENT_BRANCH"
  success "GitHub repository updated."

  # SSH to server and pull
  info "Updating production server..."
  ssh -t "$SERVER" "bash -s" <<EOF
set -euo pipefail
cd "$REMOTE_DIR"

echo "📥 Fast-forwarding server to latest commits from origin/$CURRENT_BRANCH..."
git pull --rebase --autostash origin "$CURRENT_BRANCH"

# Update Python dependencies if requirements.txt changed in latest commit
REMOTE_VENV="../tracker/bin"
if git diff --name-only HEAD@{1} HEAD | grep -q "requirements.txt"; then
    echo "📦 requirements.txt updated - installing dependencies..."
    if [ -x "\${REMOTE_VENV}/pip" ]; then
        "\${REMOTE_VENV}/pip" install -q -r requirements.txt
    fi
fi

# Clean up stale Python bytecode
find . -name "*.pyc" -delete 2>/dev/null || true

echo "🔄 Restarting service: $SERVICE..."
if sudo -n systemctl restart "$SERVICE" 2>/dev/null; then
    echo "✅ Service restarted via sudo -n."
else
    echo "🔑 Sudo password required to restart $SERVICE:"
    sudo systemctl restart "$SERVICE"
fi

# Check systemd status
if systemctl is-active --quiet "$SERVICE"; then
    echo "✅ Service $SERVICE is active and healthy!"
else
    echo "❌ Service $SERVICE failed to start! Last logs:"
    journalctl -u "$SERVICE" -n 25 --no-pager
    exit 1
fi
EOF
fi

# --- Step 6: Live Health Check -------------------------------------------------
step "[6/6] Verifying live endpoint health..."

if [[ "$DRY_RUN" = true ]]; then
  info "[DRY-RUN] curl -s -o /dev/null -w \"%{http_code}\" $DOMAIN/login"
else
  sleep 2
  HTTP_STATUS=$(curl -k -s -o /dev/null -w "%{http_code}" "$DOMAIN/login" || echo "000")
  if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "302" ]]; then
    success "Live health check passed! HTTP Status: $HTTP_STATUS ($DOMAIN)"
  else
    warn "Live health check returned HTTP $HTTP_STATUS. Please inspect server logs if unexpected."
  fi
fi

# --- Summary -------------------------------------------------------------------
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
LATEST_COMMIT=$(git rev-parse --short HEAD)
COMMIT_TITLE=$(git log -1 --pretty=%B | head -n 1)

echo ""
echo -e "${BOLD}${GREEN}======================================================${NC}"
echo -e "${BOLD}${GREEN}        🎉 Deployment Successfully Completed!          ${NC}"
echo -e "${BOLD}${GREEN}======================================================${NC}"
echo -e "  • ${BOLD}Branch:${NC}      $CURRENT_BRANCH"
echo -e "  • ${BOLD}Commit:${NC}      $LATEST_COMMIT (\"$COMMIT_TITLE\")"
echo -e "  • ${BOLD}Duration:${NC}    ${DURATION}s"
echo -e "  • ${BOLD}Service:${NC}     $SERVICE (Active)"
echo -e "  • ${BOLD}Live URL:${NC}    $DOMAIN"
echo ""
