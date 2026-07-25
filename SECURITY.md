# Security Policy

## Supported Version

Security fixes are applied to the latest commit on the `main` branch. This
project is an early local application and does not currently maintain older
release branches.

## Reporting A Vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
private vulnerability reporting feature for this repository. Include the
affected version or commit, reproduction steps, impact, and any suggested
mitigation.

If private vulnerability reporting is not enabled, open a public issue asking
the maintainer to provide a private reporting channel, without including
exploit details.

## Local-Only Security Boundary

The web interface and Python API are intended to run only on the same Windows
computer:

- Next.js UI: `http://127.0.0.1:3000`
- Python API: `http://127.0.0.1:8731`

The API can read source videos and project files selected by the user and can
write generated media to user-selected folders. It does not implement user
accounts or remote authentication. Do not bind either service to `0.0.0.0`,
expose the ports to a local network or the internet, or place the application
behind a public tunnel or reverse proxy.

## Sensitive Data

Videos, transcripts, generated projects, exports, temporary files, model
weights, local environments, and common secret-file formats are excluded by
`.gitignore`. Before publishing a change, review `git status` and confirm that
only intended source and documentation files are staged.

For visual-production work, keep creator projects outside the Git checkout by
using `scripts/new_visual_project.py`. Run `npm run privacy:check` before every
public push. The privacy guard scans tracked files and historical paths for
private workspaces, creator-media formats, transcript artifacts, personal
absolute paths, and oversized binaries.
