# BizPartnerCheck

Due diligence checks for construction companies.

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

### Staying up to date
- Pull the latest `main` into your branch **at least once a day**.

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

On GitHub, click **"Compare & pull request"** for your branch, fill in the template, and request a review from a teammate.

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
