# GitHub delivery workflow

Repository: [DatasanAli/Accounting_Harness](https://github.com/DatasanAli/Accounting_Harness).

The user has authorized uploading each completed step. Use the existing `origin`. For the initial solo workflow, push the reviewed commit to `main`. Respect branch protections if introduced; use a feature branch and PR when required. Never force-push.

## Before the commit

1. Inspect `git status --short --branch` and the diff. Preserve unrelated work.
2. Run the active checks and one documented demonstration.
3. Update `Plan/STATUS.md`, `Plan/NEXT_STEP.md`, and the active phase's verification record. State observed results and limitations precisely.
4. Review all newly added files. The public repository should contain original code, documentation, and synthetic data. Local PDFs, extracted text, financial records, credentials, and local databases are ignored.
5. Stage intended paths explicitly and run `git diff --cached --check` and `git diff --cached --stat`.

## Commit and upload

Use a message such as `docs(step-01): establish accounting harness foundation` or `feat(step-02): add exact money and chart of accounts`.

```sh
git commit -m 'feat(step-NN): describe the completed behavior'
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
gh run list --workflow verify.yml --limit 5
```

Compare local and remote commit IDs. Select the Actions run whose `headSha` equals the delivered commit, then inspect its result. Do not accept a previous commit's green run. If CI fails, inspect its logs, fix the cause, retest, and push a follow-up commit without rewriting history.

## Completion report

Report the completed step, behavior, checks, demonstration result, commit link, and CI link. Provide one copyable next-step prompt. Stop until the user asks to continue.

If authentication, networking, branch rules, or CI infrastructure block upload or validation, preserve the local commit and state the exact blocked action. Do not claim GitHub delivery is complete.

## Sources remain local

The supplied Volume 1 is 167,017,826 bytes and Volume 2 is 89,822,467 bytes. GitHub blocks regular Git files over 100 MiB; [GitHub's file-size documentation](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) was checked on 2026-09-10. Keep both source PDFs local for consistent repository handling. Commit their bibliographic references and SHA-256 fingerprints. The project check runs from a fresh clone without the books.

## Rollback

Use a new revert commit for published code or documentation. For posted accounting activity, issue a linked correction/reversal through the application once implemented. Follow the migration and restore procedures introduced with persistence and operational readiness; do not delete journals to undo a software release.
