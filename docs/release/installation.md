# Installation

Step-by-step installation of the schwab-mcp release package on your own
machine. Expected outcomes are listed after every step so you can check
your progress.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Python 3.11 or newer | Required. The install script refuses to install anything older. |
| Internet connection | Needed during installation only: the two runtime dependencies (`schwabdev`, `mcp`) are downloaded from the Python Package Index. |
| Disk space | A few dozen MB. |
| Operating system | macOS or Linux. |

### Check your Python version

```sh
python3 --version
```

**Expected outcome**: `Python 3.11.x` or newer (for example
`Python 3.12.4`). If the command prints `command not found` or a version
below 3.11, install a newer Python first:

- macOS: install from [python.org](https://www.python.org/downloads/) or
  with [Homebrew](https://brew.sh): `brew install python`.
- Linux (Debian/Ubuntu): `sudo apt update && sudo apt install python3
  python3-venv`.
- Any platform: [python.org downloads](https://www.python.org/downloads/).

Then run `python3 --version` again and continue.

## Install steps

1. **Verify the archive** as described in the package
   [README](../README.md) (checksum step).

   **Expected outcome**: `schwab-mcp-<version>.zip: OK`.

2. **Unzip the archive** (double-click in Finder, or):

   ```sh
   unzip schwab-mcp-<version>.zip
   cd schwab-mcp-<version>
   ```

   **Expected outcome**: the folder contains `README.md`, `dist/`,
   `manuals/`, `install.sh`, `manifest.json`, `SHA256SUMS`.

3. **Run the install script**:

   ```sh
   ./install.sh
   ```

   (If your system refuses `./install.sh` because of permissions, run
   `sh install.sh` instead — the result is identical.)

   **Expected outcome**: a few `OK:` lines — prerequisite satisfied,
   virtual environment created, wheel installed — ending with
   `OK: installation complete.` A virtual environment folder `.venv`
   appears in the package folder.

4. **Activate the environment and check the CLI**:

   ```sh
   source .venv/bin/activate
   schwab-mcp --help
   ```

   **Expected outcome**: the help text of `schwab-mcp`, with the package
   version visible at the top. If you see the version, the installation is
   done.

Next: [first-run-authentication.md](first-run-authentication.md) connects
the package to your Schwab account.

## What each install-script error means

Every failure of `install.sh` prints an `ERROR:` line naming this manual.
The messages and their resolutions:

| Message printed by `install.sh` | What it means | How to resolve |
|---------------------------------|---------------|----------------|
| `ERROR: python3 not found. Install Python 3.11 or newer and try again. See manuals/installation.md, section "Prerequisites".` | No `python3` on your PATH. | Install Python 3.11+ (see Prerequisites above), then re-run `./install.sh`. |
| `ERROR: Python 3.11 or newer is required (found <version>). Install a newer Python and try again. See manuals/installation.md, section "Prerequisites".` | Python exists but is too old. | Install Python 3.11+ (see Prerequisites above), then re-run `./install.sh`. |
| `ERROR: could not create the Python virtual environment. See manuals/installation.md, section "Install steps".` | The environment could not be created (common on Debian/Ubuntu when `python3-venv` is missing). | `sudo apt install python3-venv`, then re-run `./install.sh`. |
| `ERROR: bundled wheel not found (dist/*.whl). Re-extract the complete package and try again. See manuals/installation.md, section "Install steps".` | The package folder is incomplete (partial unzip or partial download). | Verify the checksum (README), re-download and re-extract the archive, then re-run `./install.sh`. |
| `ERROR: installing the bundled wheel failed. See manuals/installation.md, section "Install steps".` | The package could not be installed into the virtual environment (most often: no internet connection for the two dependencies). | Check your connection and re-run `./install.sh`. |
| `ERROR: schwab-mcp --help failed after installation. See manuals/installation.md, section "Install steps".` | The CLI was installed but does not run. | Re-run `./install.sh` on a clean folder. If it persists, see [troubleshooting.md](troubleshooting.md). |

## Upgrade in place (your credentials are preserved)

To move to a newer version:

1. Verify and unzip the **new** archive (steps 1–2 above) into a folder of
   its own.
2. Run `./install.sh` from the new folder.

**Expected outcome**: `schwab-mcp --help` (after `source .venv/bin/activate`)
shows the new version.

The upgrade replaces **only** the installation in the package folder.
Your credentials live in `~/.schwab-mcp/tokens.db` — outside any
installation folder — so they are preserved automatically. You do **not**
need to repeat the authentication step after an upgrade (unless
`schwab-mcp auth-status` reports otherwise — see
[troubleshooting.md](troubleshooting.md)).
