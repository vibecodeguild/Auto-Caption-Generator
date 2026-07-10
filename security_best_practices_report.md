# Public Release Security Review

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
