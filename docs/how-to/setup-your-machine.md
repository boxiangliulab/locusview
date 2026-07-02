# How to set up your machine for locusview (Day 0)

> **Diátaxis quadrant:** How-to — a task recipe. Goal: go from a fresh laptop to *"tests pass and
> the genomics tools run"* in one sitting. If you want to understand *why* the toolchain looks like
> this, see [`../explanation/`](../explanation/).

**Who this is for.** Anyone joining the project — including students. No assumptions beyond "I can
open a terminal."

**Definition of done.** You can run `uv run pytest` (green), `bash scripts/smoke_tabix.sh` (passes),
and `uv run locusview serve` (starts the web app).

There are two paths. **Path A (Dev Container) is the recommended, lowest-pain option** — it gives
everyone an identical environment and avoids the classic `pysam`/`bcftools` build headaches. Use
**Path B (manual)** if you prefer a native setup.

---

## Path A — Dev Container (recommended)

**Prerequisites:** [Docker](https://www.docker.com/products/docker-desktop/) and
[VS Code](https://code.visualstudio.com/) with the *Dev Containers* extension (`ms-vscode-remote.remote-containers`).

1. Clone and open the repo:
   ```bash
   git clone https://github.com/boxiangliulab/locusview.git
   cd locusview
   code .
   ```
2. When VS Code prompts **"Reopen in Container"**, click it. (Or run *Dev Containers: Reopen in
   Container* from the command palette.) The first build takes a few minutes; it installs Python,
   `uv`, and the genomics toolchain (`bcftools`, `tabix`) for you — see
   [`../../.devcontainer/devcontainer.json`](../../.devcontainer/devcontainer.json).
3. When it finishes, verify (see [Verify](#verify) below).

That's it — no native installs, and everyone on the team runs the same environment.

---

## Path B — Manual (native) setup

### 1. Install `uv` (Python package/environment manager)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS / Linux
```
`uv` installs and manages the right Python version for you; you do **not** need to install Python
separately.

### 2. Install the genomics toolchain (`bcftools`, `tabix`/`bgzip`)
These are system tools (from HTSlib), not Python packages. Pick your platform:

```bash
# macOS (Homebrew)
brew install bcftools htslib

# Debian / Ubuntu
sudo apt-get update && sudo apt-get install -y bcftools tabix

# Cross-platform via conda/mamba (works anywhere, avoids build pain)
conda install -c bioconda bcftools htslib
```

### 3. Get the code and install dependencies
```bash
git clone https://github.com/boxiangliulab/locusview.git
cd locusview
uv sync                 # creates the virtual env and installs everything (incl. dev tools)
```

### 4. (Optional) enable the pre-commit hooks
```bash
uv run pre-commit install    # runs ruff + gitleaks + large-file checks before each commit
```

---

## Verify

Run all three; each should succeed:

```bash
uv run pytest                 # unit tests — expect all green
bash scripts/smoke_tabix.sh   # genomics runtime — expect "SMOKE TEST PASSED"
uv run locusview serve        # starts the web app at http://127.0.0.1:8000  (Ctrl-C to stop)
```

While the server runs, in another terminal:
```bash
curl -s http://127.0.0.1:8000/health     # -> {"status":"ok","version":"...","env":"development"}
```

If all of these work, your machine is ready. 🎉

---

## Troubleshooting

- **`bcftools: command not found` (Path B).** The genomics toolchain isn't installed or isn't on your
  `PATH`. Re-do step 2, or switch to **Path A** (the Dev Container installs it for you).
- **`pysam` fails to build (later phases).** This is the classic native-build headache — it needs
  HTSlib headers. The Dev Container (Path A) sidesteps it entirely; prefer it if you hit this.
- **`uv: command not found`.** Restart your terminal after installing `uv`, or add its install dir
  (usually `~/.local/bin`) to your `PATH`.
- **Port 8000 already in use.** Run `uv run locusview serve --port 8080` and adjust the URL.

## Next steps
- Read [how we work](../process/ways-of-working.md) and the
  [PR & branch-protection explainer](../explanation/pull-requests-and-branch-protection.md).
- Pick a `good-first-issue`/`agent-ok` issue from the board and open your first pull request.
