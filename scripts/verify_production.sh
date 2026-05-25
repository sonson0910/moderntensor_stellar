#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_PYTEST=1
RUN_CARGO_TEST=1
RUN_STELLAR_BUILD=1
RUN_LEGACY_SCAN=1
RUN_SECRET_SCAN=1

usage() {
  cat <<'USAGE'
Usage: scripts/verify_production.sh [options]

Runs local production release acceptance checks:
  - pytest
  - cargo test for the Soroban metagraph contract
  - stellar contract build
  - legacy chain artifact scan
  - secret scan

Options:
  --skip-pytest
  --skip-cargo-test
  --skip-stellar-build
  --skip-legacy-scan
  --skip-secret-scan
  -h, --help
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --skip-pytest) RUN_PYTEST=0 ;;
    --skip-cargo-test) RUN_CARGO_TEST=0 ;;
    --skip-stellar-build) RUN_STELLAR_BUILD=0 ;;
    --skip-legacy-scan) RUN_LEGACY_SCAN=0 ;;
    --skip-secret-scan) RUN_SECRET_SCAN=0 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

section() {
  printf '\n==> %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 127
  fi
}

python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    echo "$PYTHON_BIN"
  elif command -v python >/dev/null 2>&1; then
    echo python
  elif command -v python3 >/dev/null 2>&1; then
    echo python3
  else
    echo "Missing required command: python or python3" >&2
    exit 127
  fi
}

run_pytest() {
  section "pytest"
  "$(python_bin)" -m pytest
}

run_cargo_test() {
  section "cargo test"
  require_cmd cargo
  cargo test --manifest-path contracts/metagraph/Cargo.toml
}

run_stellar_build() {
  section "stellar contract build"
  require_cmd stellar
  (
    cd contracts/metagraph
    stellar contract build
  )
}

run_legacy_scan() {
  section "legacy chain scan"
  require_cmd rg

  local legacy_pattern
  local legacy_terms=(
    "Car""dano"
    "car""dano"
    "Plu""tus"
    "plu""tus"
    "Block""frost"
    "block""frost"
    "Ogm""ios"
    "ogm""ios"
    "Ku""po"
    "ku""po"
    "Ko""ios"
    "ko""ios"
    "UT""xO"
    "UT""XO"
    "ut""xo"
    "Ai""ken"
    "ai""ken"
    "Lu""cid"
    "lu""cid"
  )
  legacy_pattern="$(IFS='|'; echo "${legacy_terms[*]}")"

  local matches
  matches="$(mktemp)"
  if rg -n --hidden --color never \
    --glob '!scripts/verify_production.sh' \
    -e "$legacy_pattern" \
    sdk tests contracts/metagraph/src scripts/bootstrap_stellar_testnet.py pyproject.toml requirements.txt pytest.ini .env.example \
    >"$matches"; then
    cat "$matches"
    rm -f "$matches"
    echo "Legacy chain references found in active runtime/test/config files." >&2
    exit 1
  fi
  rm -f "$matches"
}

run_secret_scan() {
  section "secret scan"

  if command -v gitleaks >/dev/null 2>&1; then
    local scan_root
    local status
    scan_root="$(mktemp -d)"
    mkdir -p "$scan_root/contracts/metagraph" "$scan_root/.github"
    cp -R README.md CHANGELOG.md .env.example pyproject.toml requirements.txt pytest.ini sdk tests scripts "$scan_root/"
    cp -R contracts/metagraph/src "$scan_root/contracts/metagraph/"
    cp contracts/metagraph/Cargo.toml "$scan_root/contracts/metagraph/"
    cp -R .github/workflows "$scan_root/.github/"
    status=0
    gitleaks detect --source "$scan_root" --no-git --redact --verbose || status=$?
    rm -rf "$scan_root"
    return "$status"
  fi

  require_cmd rg

  local matches
  matches="$(mktemp)"
  if rg -n --hidden --color never \
    --glob '!target/**' \
    --glob '!.git/**' \
    --glob '!.venv/**' \
    --glob '!__pycache__/**' \
    --glob '!.pytest_cache/**' \
    -e '(^|[^A-Z2-7])S[A-Z2-7]{55}([^A-Z2-7]|$)' \
    -e '(?i)(secret|private[_-]?key|mnemonic|seed|password|api[_-]?key|access[_-]?token)\s*[:=]\s*["'\''"][^"'\''[:space:]]{16,}["'\'']' \
    README.md CHANGELOG.md .env.example pyproject.toml requirements.txt pytest.ini sdk tests scripts contracts/metagraph/src contracts/metagraph/Cargo.toml .github/workflows \
    >"$matches"; then
    cat "$matches"
    rm -f "$matches"
    echo "Potential secret material found. Remove live secrets from tracked files." >&2
    exit 1
  fi
  rm -f "$matches"
}

if [[ "$RUN_PYTEST" -eq 1 ]]; then
  run_pytest
fi
if [[ "$RUN_CARGO_TEST" -eq 1 ]]; then
  run_cargo_test
fi
if [[ "$RUN_STELLAR_BUILD" -eq 1 ]]; then
  run_stellar_build
fi
if [[ "$RUN_LEGACY_SCAN" -eq 1 ]]; then
  run_legacy_scan
fi
if [[ "$RUN_SECRET_SCAN" -eq 1 ]]; then
  run_secret_scan
fi

section "production verification complete"
