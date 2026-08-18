# GitHub upload

This export was created in a session with `git` but without an authenticated GitHub connector or GitHub CLI, so direct remote upload was not possible.

## From the ZIP working tree

```bash
unzip transient_research_repo_2026-08-18.zip
cd transient_research_repo
git init -b main
git add .
git commit -m "Freeze historical plate transient methodology and current data state"
git remote add origin https://github.com/<ACCOUNT>/<REPOSITORY>.git
git push -u origin main
```

## From the `.gitbundle`

The accompanying git bundle already contains the snapshot as a commit:

```bash
git clone transient_research_repo_2026-08-18.gitbundle transient_research_repo
cd transient_research_repo
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/<ACCOUNT>/<REPOSITORY>.git
git push -u origin main
```

If the destination is private, authenticate using your normal GitHub credential/SSH mechanism. No credentials or secrets are included in this export.
