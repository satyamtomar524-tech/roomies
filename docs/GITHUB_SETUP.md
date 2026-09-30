# GitHub project

Public repository: [satyamtomar524-tech/roommate](https://github.com/satyamtomar524-tech/roommate).

The repository contains source, tests, documentation and an illustrative room. Runtime databases, actual room backups, credentials and logs are excluded. Check `git status` before publishing any future change.

## Get a working copy

```sh
git clone https://github.com/satyamtomar524-tech/roommate.git
cd roommate
python -m roommate
```

Or extract the source ZIP and run from its directory. A ZIP does not include Git history.

## Publish your next change

Use your GitHub-authenticated working copy. Make a small change and run the relevant checks first:

```sh
python -m unittest discover -s tests -v
node --check web/app.js
git status
git add PATH-TO-YOUR-CHANGED-FILE
git commit -m "Describe the change"
git push
```

Replace the placeholder with the specific file you changed. Keep real room backups private. The repository uses a GitHub noreply commit address so a personal email is not embedded in its commit history.

The workflow checks Python 3.10, 3.12 and 3.13, JavaScript syntax, and the complete Chromium workflow. Its [run history](https://github.com/satyamtomar524-tech/roommate/actions) is the evidence for remote results.
