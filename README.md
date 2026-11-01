# BizPartnerCheck

Due diligence checks for construction companies.

---
## Install the tools (once)

### Docker Desktop
1. Download it from https://www.docker.com/products/docker-desktop/ → **Download for Windows**.
2. Run the installer and keep the default options (**Use WSL 2** ticked). Restart the computer if asked.
3. Start **Docker Desktop** and wait until it shows **Engine running** (bottom left).
4. Check in PowerShell:
   ```powershell
   docker --version
   ```
Docker Desktop must be **running** whenever you work with the database.

### uv (Python package manager)
1. In PowerShell run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   (Alternative: `winget install --id=astral-sh.uv -e`)
2. **Close and reopen** the terminal (in VS Code/PyCharm: restart the whole app), otherwise `uv` is not found.
3. Check:
   ```powershell
   uv --version
   ```
You don't need to install Python separately – `uv` downloads the right version (3.13) automatically.

### Node.js (for the frontend)
1. Download the **LTS** version from https://nodejs.org/ (version 22 or newer) and run the installer with the default options.
   (Alternative: `winget install OpenJS.NodeJS.LTS`)
2. **Close and reopen** the terminal.
3. Check:
   ```powershell
   node --version
   npm --version
   ```

---
## Local database setup
**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running) and [uv](https://docs.astral.sh/uv/).

Run once, from the project folder:

```powershell
Copy-Item .env.example .env                       # create your local settings file (never commit .env)
docker compose -f infra/docker-compose.yml up -d  # start PostgreSQL 17 in Docker
cd backend
uv sync                                           # install Python packages
uv run alembic upgrade head                       # create/update all tables in the database
```

- **After `git pull`**: run `uv run alembic upgrade head` again (in `backend`), in case someone added a new migration.
- **After changing `app/db/models.py`**: create a migration with `uv run alembic revision --autogenerate -m "what changed"`, then `uv run alembic upgrade head`, and commit the new file in `app/db/migrations/versions/`.
- **Stop the database**: `docker compose -f infra/docker-compose.yml down`

---
## Run the backend (API)
**Requirements:** the database is running (see above).

```powershell
cd backend
uv run uvicorn app.main:app --reload   # starts the API on http://localhost:8000
```

- Health check: http://localhost:8000/health → `{"status": "ok"}`
- Interactive API docs: http://localhost:8000/docs
- Run the tests: `uv run pytest` (in `backend`, database must be running). The tests never call the real VIES service.
- The **Check** button (VIES) needs internet: it asks the EU VIES service. Details: [docs/vies.md](docs/vies.md)

---
## Run the frontend (web app)
**Requirements:** [Node.js](https://nodejs.org/) LTS and the backend running (see above).

Run once, from the project folder:

```powershell
cd frontend
npm install        # install packages (again after `git pull` if package.json changed)
```

Then start it:

```powershell
npm run dev        # opens on http://localhost:5173
```

The web app calls the backend through `/api`, which the dev server forwards to http://localhost:8000.

---

## How we work

### Branches
- `main` always contains working, reviewed code. **Never push to it directly** (it is protected).
- Create **one branch per Jira item**: `SCRUM-<number>-short-description` (e.g. `SCRUM-31-vies-check`).
- Keep branches small and short-lived. Split big items into smaller ones.
- Ihor deletes the branch after it is merged.

### Commits
- Format: `SCRUM-<number>: what you did` (e.g. `SCRUM-31: add VIES client`).
- Commit small and often, whenever you reach a small working step.

### Pull requests
- Every change goes into `main` through a pull request.
- Fill in the PR template (Jira item, what changed, how to test, checklist).
- Ihor approves before merging.
- Review comments must be resolved before merging.
- Ihor merges after approval.
- Keep PRs small: **one Jira item per PR**, reviewable in about 15 minutes.

---

### Staying up to date
- Pull the latest `main` into your branch **at least once a day**.

---

### Documentation
- There is **one README** for the whole project. Do not replace it – only add or update the lines your change affects (e.g. a new setup step or `.env` variable).
- If your task includes a decision or something the team needs to understand later (why you chose X, how something works, research results), write a short `.md` file in the `docs/` folder and add it in the same PR.
- **One topic per file**, lowercase names with hyphens, e.g. `docs/database.md`, `docs/data-sources.md`.
- Suggested structure: **Context** (what problem), **Decision** (what we chose), **Why / Alternatives** (what we rejected and why).
- If your change makes an existing doc outdated, update that file instead of creating a new one.
- Small tasks that need no explanation: the PR description is enough.


---

## Why we use branches

A branch is a separate line of work inside the project. It lets you change code without touching the version everyone else relies on.

```
main  ──●──────────●──────────────●────►   (always working code)
         \        /  \            /
          ●──●──●     ●──●──●──●
       SCRUM-23 branch   SCRUM-31 branch
       (merged via PR)   (merged via PR)
```

This keeps half-finished or broken code away from the rest of the team, makes changes easy to review, and lets us throw away experiments without affecting anyone.

---

## Workflow: from start to finish

Example task: **SCRUM-31 – Add VAT number check via the VIES service.**

### 1. Start from an up-to-date `main`

**PyCharm:** Click the branch name (top-left in the new UI, bottom-right in the classic UI) → `main` → **Checkout**. Then **Git → Pull** (Ctrl+T / ⌘T).

```bash
git switch main
git pull
```

### 2. Create your branch

**PyCharm:** Branch popup → **New Branch…** → enter `SCRUM-31-vies-check` → keep **Checkout branch** ticked → **Create**.

```bash
git switch -c SCRUM-31-vies-check
```

### 3. Write code and commit in small steps

**PyCharm:** Open the Commit tool window (Ctrl+K / ⌘K), tick the changed files, write a message, click **Commit**.

Example commits:
- `SCRUM-31: add VIES client`
- `SCRUM-31: add /vat-check endpoint`
- `SCRUM-31: add tests for VAT check`

```bash
git add .
git commit -m "SCRUM-31: add VIES client"
```

### 4. Push your branch

**PyCharm:** **Git → Push** (Ctrl+Shift+K / ⌘⇧K). The first push creates the branch on GitHub.

```bash
git push -u origin SCRUM-31-vies-check   # later pushes: git push
```

### 5. Keep up with `main` (at least daily)

**PyCharm:** Branch popup → hover over `main` → **Merge 'main' into 'SCRUM-31-vies-check'**. If there are conflicts, PyCharm opens a merge tool where you choose which lines to keep.

```bash
git switch main
git pull
git switch SCRUM-31-vies-check
git merge main
```

### 6. Open a pull request

On GitHub, click **"Compare & pull request"** for your branch, fill in the template, and request a review from Ihor (Ihor’s own PRs: from another teammate).

### 7. Address review feedback

Keep working on the same branch, commit, and push. The pull request updates automatically.

### 8. Merge(only applies to Ihor)

Once approved and all comments are resolved, click **Merge** and then **Delete branch** on GitHub.

### 9. Clean up and start the next item

**PyCharm:** Checkout `main` → **Git → Pull** → branch popup → hover your old branch → **Delete**.

```bash
git switch main
git pull
git branch -d SCRUM-31-vies-check
```

Then go back to step 1 for the next Jira item.

---

## Merge conflicts

A conflict happens when two branches changed the same lines. On GitHub, a PR then shows *"This branch has conflicts"*:

1. Click **Resolve conflicts**.
2. Decide which lines to keep (sometimes both).
3. Delete the `<<<<<<<`, `=======` and `>>>>>>>` marker lines.
4. Click **Mark as resolved → Commit merge**.

In PyCharm, conflicts open in a three-panel merge tool where you accept changes from either side.

---

## Undoing, deleting and renaming branches

You **cannot delete the branch you are currently on**, so switch to `main` first.

### Delete a local branch

**PyCharm:** Branch popup → hover over the branch → **Delete**.
If it has unmerged commits, PyCharm warns you; deleting loses that work. A **Restore** link briefly appears afterwards.

```bash
git branch -d SCRUM-31-vies-check   # -D to force if it has unmerged work
```

### Delete a branch you already pushed

Make sure no teammate is still using it.

**PyCharm:** Branch popup → under **Remote**, hover over `origin/<branch>` → **Delete**.

```bash
git push origin --delete SCRUM-31-vies-check
```

### Rename a branch

**PyCharm:** Branch popup → hover over the branch → **Rename…**

```bash
git branch -m old-name new-name
```

---

## Quick reference

| Action | PyCharm | Terminal |
|--------|---------|----------|
| Pull latest | Git → Pull (Ctrl+T / ⌘T) | `git pull` |
| New branch | Branch popup → New Branch… | `git switch -c <name>` |
| Switch branch | Branch popup → branch → Checkout | `git switch <name>` |
| Commit | Ctrl+K / ⌘K | `git commit -m "SCRUM-<n>: ..."` |
| Push | Ctrl+Shift+K / ⌘⇧K | `git push` |
| Merge `main` into branch | Branch popup → main → Merge into current | `git merge main` |
| Delete local branch | Branch popup → branch → Delete | `git branch -d <name>` |
| Delete remote branch | Branch popup → Remote → Delete | `git push origin --delete <name>` |
| Open terminal in PyCharm | Alt+F12 | – |

---
