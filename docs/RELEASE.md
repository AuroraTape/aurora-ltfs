# Release process

How Aurora LTFS is versioned, branched, tagged and released. It records the
practice of the 1.0.0 and 1.0.1 releases and the rules the message ID
scheme ([`messages/README`](../messages/README)) already assumes.

## Versioning

- Semantic versioning, `MAJOR.MINOR.PATCH`. A release is an annotated tag
  `vX.Y.Z` on the commit it is built from.
- Release candidates are tagged `vX.Y.Z-rc.N`. The release workflow marks
  them as pre-releases, and the packages carry the version as `X.Y.Z~rc.N`
  (`~` sorts before the final in both deb and rpm). Once the final release
  is published, the candidate tags and their pre-releases are deleted; a
  deleted tag is never pushed again.
- The version in the sources is derived at build time
  (`build-aux/git-version.sh`): the tag on a release build, `git describe`
  otherwise (`1.0.1-3-g1a2b3c4`, which sorts after the release and names
  the commit), `.tarball-version` in a distribution tarball. Nothing in the
  tree has to be edited for a release; the release workflow embeds the tag
  version into `configure.ac`, `rpm/altfs.spec` and `debian/changelog` on
  its own checkout.

## Branches

- `main` is where development happens. Minor and major releases (`X.Y.0`)
  are cut from `main`.
- `release/X.Y` is created at the tag `vX.Y.0` and receives the patch
  releases `X.Y.Z` of that line, each tagged on the branch. Only one patch
  stream per minor is active at a time (the message ID pools depend on it).
- Release branches change through pull requests only, never by direct
  commits (see [GOVERNANCE.md](GOVERNANCE.md)). Backports are the only
  changes they receive; a fix is never developed on a release branch first.
- Support window: a minor line receives fixes until six months after the
  next minor is released, the transition period the platform support policy
  in the README also uses. After that, its release branch stays in the
  repository and gets no further tags.

## Backports

A fix that a shipped line needs lands on `main` first, then goes back:

1. Label the issue (or the PR, when there is no issue) `!!Backport!!`. The
   label lists the outstanding backports; it is removed when the backport is
   merged.
2. Branch from the release branch: `git checkout -b backport/X.Y/<PR#>-<slug>
   origin/release/X.Y`, then `git cherry-pick -x <squash commit of the PR on
   main>`. The `-x` line in the message is the record of the origin.
3. Resolve conflicts on the release branch's terms: the fix keeps its
   behaviour, code that does not exist on the line is left out. A message
   catalog conflict is usually context only (messages the line does not
   have); keep the backported IDs as they are on `main`.
4. Open a PR into `release/X.Y` titled `[X.Y] <original title> (backport
   #NN)`, labelled `!!Backported!!`, with the milestone of the next patch
   release (`Version X.Y.Z`). The PR description says what was
   cherry-picked and whether anything changed relative to the original.
5. CI on the PR runs the builds, the test suites and the message ID check
   for release branches.

Message IDs on a release branch: a backported message keeps the ID it has on
`main`. A message that exists only on the release branch takes the
letter-bearing shape of that line's pool (`AFSA001E` for 1.0.x, `AFSAA01E`
for 1.1.x, ...), so that it cannot collide with IDs allocated on `main` later.
`validate_error_messages.py --target-branch release/X.Y --base origin/release/X.Y`
checks both; CI runs it on every PR into `release/**`.

## Milestones and labels

- Issues carry the milestone: `Version X.Y` for the minor line, `Version
  X.Y.Z` for a patch release. A PR that belongs to an issue carries none; a
  PR without an issue carries the milestone itself. Backport PRs always carry
  the patch milestone.
- A milestone is closed right after its release is tagged and published;
  the next one (`Version X.Y.Z+1`, or the next minor) is created then.
- The bracketed labels (`[A01] Enhancement`, `[300] Incorrect result (500)`,
  ...) classify issues, not PRs. PRs are told apart by their conventional
  commit title (`feat(...)`, `fix(...)`, `ci:`, `docs:`, `test:`), which is
  what the release notes are written from.

## Release notes

GitHub Releases are the changelog of the project; there is no `CHANGELOG.md`
in the repository, and the packages' changelogs (`debian/changelog`, the rpm
`%changelog`) carry one "Release X.Y.Z" entry each.

The release workflow seeds the release with the list of merged PRs and the
"Full Changelog" compare link that GitHub generates. The maintainer then
replaces it with the hand-written notes, in the structure of the previous
releases:

1. An opening paragraph: what the release is, in two or three sentences,
   and where the packages and the container image are.
2. Callouts (`> [!IMPORTANT]`, `> [!WARNING]`, `> [!NOTE]`) for anything a
   user must know before upgrading: known issues, behaviour visible to
   scripts, and the testing status (which suites, which containers, which
   drive).
3. **Upgrade notes**: every change visible to users or scripts, with the
   issue number.
4. **New Features**, **Fixes**, **Documentation**, **Infrastructure**
   (CI, test environment): one line per change, issue or PR number at the
   end. Interoperability notes (format version, incremental indexes,
   extended attribute semantics) go under Upgrade notes.
5. The `**Full Changelog**` compare link.

Sources for the list: `git log --oneline vA..vB` (the squash-commit titles),
the milestone's closed issues, and the `!!Backported!!` PRs for a patch
release. Items collected during development are noted on the release's
tracking issue as they land, so the notes are not written from memory.

## Checklist

### Before tagging

- [ ] Every issue in the milestone is closed or moved to a later one.
- [ ] `Build` and `Scenario tests` are green on the release commit, and
      `python3 validate_error_messages.py` is clean.
- [ ] The README says what the release does: platform support, drive
      table, format version and interoperability, container tag examples
      (`X.Y` of the line, never a patch version that will go stale).
- [ ] Man pages regenerated if their SGML sources changed
      (`make man-rebuild` in `man/`, needs docbook2man).
- [ ] For a minor release: `AGENTS.md` and the build instructions still
      match the tree.
- [ ] For a patch release: every `!!Backport!!` item intended for it is
      merged and the label removed.

### Tagging

- [ ] Release candidate first when the change is more than a handful of
      backports: `git tag -a vX.Y.Z-rc.1 -m "Aurora LTFS X.Y.Z-rc.1"` on
      the release commit, `git push origin vX.Y.Z-rc.1`, then the same
      verification as for the final. Fix on the branch, tag `-rc.2`, and so
      on.
- [ ] Final: `git tag -a vX.Y.Z -m "Aurora LTFS X.Y.Z"` on the same commit
      as the last candidate, `git push origin vX.Y.Z`. For `X.Y.0`, create
      `release/X.Y` at the tag and push it.
- [ ] Watch `release.yml`: the `.deb` (Ubuntu 24.04) and `.rpm` (Rocky Linux
      9) jobs, the container image (GHCR, `X.Y.Z` / `X.Y` / `X`, no
      `latest`) with its smoke test, and the GitHub Release with the
      packages attached.

### After the workflow

- [ ] Install the packages in clean containers (`ubuntu:24.04`,
      `rockylinux:9`): clean install and upgrade from the previous release;
      run `altfs -V`, `altfs -o device_list`, and format, mount, write, unmount
      and `altfsck` a `file` backend volume. `altfs -V` must print the tag
      version.
- [ ] `docker run --rm ghcr.io/auroratape/aurora-ltfs:X.Y.Z altfs -V`.
- [ ] On a real drive when one is available: format, mount, write, unmount,
      remount, `altfsck`, and the service stop with a mounted tape. Record
      the drive, firmware and host in the testing-status note.
- [ ] Write the release notes (above). For a final release that had
      candidates, delete the candidate tags and pre-releases.
- [ ] Close the milestone, create the next one, and remove `!!Backport!!`
      from everything the release shipped.
- [ ] Announce where the project announces (GitHub Release, discussions).

## Branch protection

Three repository rulesets enforce the branch rules (Settings, Rules):

- `main`: no deletion, no force push, changes through pull requests only
  (squash merges, signed commits), and the required checks `Ubuntu 24.04`,
  `Rocky Linux 9`, `Message IDs` and `FS API + scenarios (Ubuntu 24.04)`.
- `release/*`: the same, plus one approving review. Backports are pull
  requests like any other change.
- `v*` tags: created by repository admins only, never moved or deleted by
  anyone else.

Repository admins can bypass the pull request rules, but only from within a
pull request (bypass mode "pull request"): with a single Core Member that is
what lets the maintainer merge their own backports; direct pushes to `main`
and `release/*` are refused for everyone. The review requirement on
`release/*` binds every non-admin contributor.

## Deferred decisions

- Multi-architecture container images (arm64) and a `latest` tag: the tag is
  deliberately not published (a tape-touching tool must not change behind
  the user's back); arm64 images wait for a user.
- apt / dnf repositories and a Homebrew tap: #131.
- Signing of tags, packages and images: with #131, since the repositories
  need a signing key anyway.
