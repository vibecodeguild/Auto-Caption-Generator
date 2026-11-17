# Public Release Security Review

## Publication review: November 17, 2026

The privacy issue identified in this review has been removed from the current
publication tree and all reachable local Git refs. The application is **not
fully release-ready**: dependency advisories and failing cut-export tests remain.
The June review below is retained as history; its clean-audit result is
superseded by this review.

### PR-1: Private information in a tracked screenshot (fixed locally)

- Severity: High for publication privacy.
- Location: the former `docs/assets/single-row-stage-header-approved.png`.
- Evidence: the source-preview header displayed a personal Windows directory
  and recording filename inside the image pixels. Text searches did not detect it.
- Impact: publishing the image disclosed private source context.
- Resolution: preserve the local image, ignore it, remove the public Markdown
  embed, and retain the approved written design requirements. Add privacy-guard
  regression coverage for the image, environment files, and key containers.
- With explicit user authorization, rewrite local branch history to remove
  the image. Also sanitize the local non-commit checkpoint tree. Verify the
  image blob is unreachable from every local ref. Preserve working files and
  the index during the rewrite.
- Nothing was pushed. GitHub remains unchanged. If the old history is already
  published, a coordinated remote replacement and any required cache/fork
  cleanup remain separate work. A normal new commit cannot erase old history.

### PR-2: Dependency advisories (unresolved)

- Severity: Critical reported by npm; exploitability was not established here.
- Locations: `package.json`, `package-lock.json`, and the local Python environment.
- `npm audit --omit=dev` reports 14 affected packages: 1 critical, 10 high,
  and 3 moderate. Next.js is the critical package. One reported advisory is
  [Windows-hosted server remote code execution](https://github.com/advisories/GHSA-p293-qw3h-jr36).
- `pip-audit --local` reports 23 advisory entries across 8 installed packages;
  the output includes duplicate entries. GPU builds of torch and torchaudio
  could not be audited. This is an environment audit, not proof that every
  reported package is a direct application dependency.
- Dependency upgrades require compatibility work and renewed verification;
  none were made in this privacy cleanup. Keep the documented local-only
  server boundary in place. Public source publication does not authorize
  exposing either application server to the network.

### Privacy verification and limits

- Scanned 538 reachable historical blobs and the publication candidates for
  common credential tokens, private keys, credential-bearing URLs, personal
  paths, and private email patterns. Compared the local environment's populated
  credential value against the candidate files and historical blobs without
  printing it. No credential match was found.
- Inspected all four tracked design images visually. Email matches in the three
  remaining concept images belong to vendor provenance metadata; they are not
  personal contact details identified by this review.
- Local environment files remain ignored. Commit author and committer emails
  use GitHub noreply addresses; public account attribution remains visible.
- `python scripts/check_repo_privacy.py --history` passes after cleanup.
- All 23 privacy regression tests pass. TypeScript typecheck, all 3 web tests,
  and the Next.js production build pass. `git diff --check` passes.
- The full Python suite has 484 passing tests and 3 failures in existing
  cut-export API tests. The focused run has 114 passes and the same 3 failures.
  No product behavior was changed to address those tests.
- Pattern scans and visual inspection reduce disclosure risk; they do not
  certify that every possible secret or private fact has been detected.

## Earlier review (superseded)

> Point-in-time audit record. This report covers the repository as reviewed on
> June 18, 2026 and has not been re-certified for later working-tree changes.
> Current operating guidance remains in `SECURITY.md`; rerun the verification
> below before the next public release.

Reviewed: June 18, 2026

## Result

No known credentials, private keys, personal filesystem paths, generated media,
model weights, or project files are tracked in the current repository or were
found in its reachable Git history. The repository is suitable for public
publication with the local-only operating boundary documented below.

## Findings Fixed

### Medium: Local API did not enforce its documented host and origin boundary

The API can read user-selected project and video files and write generated
media. It was bound to `127.0.0.1` and configured with CORS, but it did not
explicitly reject untrusted `Host` or browser `Origin` headers.

Fixed by:

- Adding trusted-host enforcement for `127.0.0.1` and `localhost`.
- Rejecting browser requests from origins other than the local UI.
- Disabling public API documentation routes.
- Adding `nosniff` and no-referrer response headers.
- Adding regression tests for trusted and untrusted requests.

### Medium: Vulnerable transitive PostCSS version

`npm audit --omit=dev` reported the PostCSS advisory
`GHSA-qx2v-qp2m-jg93`.

Fixed by pinning the patched PostCSS release through `package.json` overrides
and regenerating `package-lock.json`.

### Low: Python dependency versions were not reproducible

The Python requirements allowed unconstrained upgrades, which could produce
different environments for different contributors.

Fixed by pinning the currently tested direct dependencies and optional NVIDIA
runtime packages.

## Verification

- `54` Python tests passed.
- TypeScript typecheck passed.
- Next.js production build passed.
- `npm audit --omit=dev` reported zero vulnerabilities.
- `pip-audit --local` reported no known vulnerabilities after updating the
  virtual environment's `pip` installer.
- Tracked-file and reachable-history scans found no common secret patterns,
  personal local paths, private email addresses, or sensitive file types.
- `.gitignore` behavior was verified for environments, build output, media,
  exports, temporary files, VCG projects, model files, FFmpeg binaries, and
  common secret-file formats.
- Commit author and committer metadata use the configured GitHub noreply email.

## Residual Boundary

This application is not designed to be hosted as a remote web service. The API
does not have user authentication because it is intended to run only on the
same machine as the UI. Keep ports `3000` and `8731` bound to `127.0.0.1` and
do not expose them through a tunnel, reverse proxy, router, container mapping,
or firewall rule.

This review covers the repository state and dependency advisories available on
the review date. Dependency audits should be repeated before future releases.
