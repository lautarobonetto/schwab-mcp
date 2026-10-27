#!/bin/sh
# Install script for the schwab-mcp release package (see research D11).
#
# Checks the documented prerequisite (Python >= 3.11), creates a virtual
# environment, installs the bundled wheel, and verifies the CLI runs.
# Every failure prints an actionable ERROR line whose wording is mirrored
# in manuals/installation.md, section "What each install-script error
# means".  Upgrade-safe: re-running replaces the installation in place and
# NEVER touches ~/.schwab-mcp/ (credentials live outside the install).
set -eu

# Resolve the package directory using shell builtins only, so the
# prerequisite error paths below work even on a stripped PATH.
case "$0" in
    */*) _dir=${0%/*} ;;
    *) _dir=. ;;
esac
SCRIPT_DIR=$(CDPATH= cd -- "$_dir" && pwd)

PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="$SCRIPT_DIR/.venv"

fail() {
    echo "$1" >&2
    exit 1
}

# --- Prerequisite: Python >= 3.11 -------------------------------------------
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    fail 'ERROR: python3 not found. Install Python 3.11 or newer and try again. See manuals/installation.md, section "Prerequisites".'
fi

if ! PY_VERSION_OUTPUT=$("$PYTHON_BIN" --version 2>&1); then
    fail "ERROR: $PYTHON_BIN is not a working Python interpreter. Install Python 3.11 or newer and try again. See manuals/installation.md, section \"Prerequisites\"."
fi

PY_VERSION=${PY_VERSION_OUTPUT#Python }
PY_MAJOR=${PY_VERSION%%.*}
PY_MINOR=${PY_VERSION#*.}
PY_MINOR=${PY_MINOR%%.*}

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    fail "ERROR: Python 3.11 or newer is required (found $PY_VERSION). Install a newer Python and try again. See manuals/installation.md, section \"Prerequisites\"."
fi

echo "OK: Python $PY_VERSION satisfies the >= 3.11 prerequisite."

# --- Bundled wheel ----------------------------------------------------------
WHEEL=$(ls "$SCRIPT_DIR"/dist/*.whl 2>/dev/null | head -n 1 || true)
if [ -z "$WHEEL" ]; then
    fail 'ERROR: bundled wheel not found (dist/*.whl). Re-extract the complete package and try again. See manuals/installation.md, section "Install steps".'
fi

# --- Virtual environment (upgrade-safe: replace in place) --------------------
rm -rf "$VENV_DIR"
if ! "$PYTHON_BIN" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    fail 'ERROR: could not create the Python virtual environment. See manuals/installation.md, section "Install steps".'
fi
echo "OK: virtual environment created at $VENV_DIR"

# --- Install the bundled wheel ----------------------------------------------
if ! "$VENV_DIR/bin/python" -m pip install --quiet "$WHEEL" >/dev/null 2>&1; then
    fail 'ERROR: installing the bundled wheel failed. See manuals/installation.md, section "Install steps".'
fi
echo "OK: bundled wheel installed"

# --- Verify the CLI runs ----------------------------------------------------
if ! "$VENV_DIR/bin/schwab-mcp" --help >/dev/null 2>&1; then
    fail 'ERROR: schwab-mcp --help failed after installation. See manuals/installation.md, section "Install steps".'
fi

echo "OK: installation complete."
echo "Next: source .venv/bin/activate and follow manuals/first-run-authentication.md"
