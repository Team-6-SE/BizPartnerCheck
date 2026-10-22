# BizPartnerCheck

Due diligence checks for construction companies.

## How we work

### Branches
- `main` always contains working, reviewed code. Never push to it directly.
- Create one branch per Jira item: `SCRUM-<number>-short-description`
  (e.g. `SCRUM-31-vies-check`).
- Delete the branch after it is merged.
- Only Ihor is allowed to merge branches after reviewing it. This way we can prohibit failure of code.

### Commits
- Format: `SCRUM-<number>: what you did` (e.g. `SCRUM-31: add VIES client`).
- Commit small and often.

### Pull requests
- Every change goes into `main` through a pull request.
- Ihor must approve before merging.
- Ihor merges after approval.
- Keep PRs small: one Jira item per PR.

### Staying up to date
- Pull the latest `main` into your branch at least once a day.
