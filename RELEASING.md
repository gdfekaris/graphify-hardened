# Releasing

Concrete steps for cutting a release of `graphify-hardened`. Solo
maintainer, single trunk, signed tags, GitHub Releases.

## Conventions

- **Trunk:** `main`. All work lands here. Direct push or PR-then-merge,
  both fine.
- **Tag format:** `vMAJOR.MINOR.PATCH-hardened` (e.g. `v0.1.0-hardened`,
  `v0.2.0-hardened`). The `-hardened` suffix is permanent across all
  fork releases — it disambiguates from upstream's `vX.Y.Z` namespace
  in any context that fetches both projects' tags.
- **Signing:** every release tag is signed with the maintainer's GPG
  key, fingerprint `43C238872226A83A4FDAB86E0C757C7BAF91D21B`. Users
  verify with `git tag -v <tag>`.
- **No `stable` branch.** "Latest stable" is the most recent signed tag.
- **Release branches** `release/X.Y.x` are created on demand only —
  the day a security fix on `main` needs to backport to a still-supported
  older line.

## Pre-release checklist

1. Working tree clean: `git status` empty.
2. On `main`, in sync with origin: `git status -sb` shows
   `## main...origin/main`.
3. Test suite green: `uv run --with pytest pytest tests/`.
4. Dependency audit clean:

       uv export --format requirements-txt --no-emit-project --all-extras > /tmp/req.txt
       uv tool run pip-audit==2.10.0 -r /tmp/req.txt
       osv-scanner --lockfile=uv.lock

5. CHANGELOG / release notes draft ready.
6. Version in `pyproject.toml` bumped (without the `-hardened` suffix —
   the suffix lives in the git tag, not in package metadata).

## Cutting the release

7. Commit the version bump:

       git commit -am "chore(release): vX.Y.Z-hardened"

8. Create the signed tag with a meaningful annotation:

       git tag -s vX.Y.Z-hardened -m "Release notes summary

       Phases / threat surfaces covered, upstream baseline SHA, link to
       full release notes."

9. Push commit then tag:

       git push origin main
       git push origin vX.Y.Z-hardened

10. Verify the tag landed and verifies:

        git tag -v vX.Y.Z-hardened
        git ls-remote --tags origin | grep vX.Y.Z-hardened

## Publishing the GitHub Release

11. Generate a source tarball locally and record its SHA256:

        git archive --format=tar.gz \
            --prefix=graphify-hardened-X.Y.Z/ \
            vX.Y.Z-hardened > graphify-hardened-X.Y.Z.tar.gz
        sha256sum graphify-hardened-X.Y.Z.tar.gz

12. On GitHub: Releases → Draft a new release → choose the tag →
    "Generate release notes" → review and edit. In the body, include:
    - Short prose summary of what this release is for.
    - Threat surfaces or CVEs addressed (link to advisories).
    - Breaking changes and migration notes if any.
    - Upstream baseline SHA at the time of release.
    - The tarball SHA256 from step 11.
13. Attach the tarball as a release asset.
14. Publish.

## Backporting a security fix

If a CVE lands against an older shipped line you have committed to
supporting, *then* (and only then):

15. Cut a release branch from the older tag:

        git checkout -b release/X.Y.x vX.Y.0-hardened

16. Cherry-pick the fix from `main`.
17. Tag `vX.Y.(Z+1)-hardened` from the release branch and follow the
    standard release flow above for that tag.
