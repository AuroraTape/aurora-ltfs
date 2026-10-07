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
- [ ] Man pages regenerated if their SGML sources changed (`make` in
      `man/` with docbook2man installed, see `man/README.md`).
- [ ] For a minor release: `AGENTS.md` and `docs/BUILDING.md` still
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
      packages attached. For a final release it then starts
      `packages.yml` and `homebrew.yml` on `main`: approve the run of
      `packages.yml` (environment `packages`) and watch the installs from
      the repositories in clean containers and from the tap on macOS.

### After the workflow

- [ ] Install the packages in clean containers (`ubuntu:24.04`,
      `rockylinux:9`) from the apt / dnf repositories (for a candidate,
      from the Release assets): clean install and upgrade from the previous
      release;
      run `altfs -V`, `altfs -o device_list`, and format, mount, write, unmount
      and `altfsck` a `file` backend volume. `altfs -V` must print the tag
      version.
- [ ] `docker run --rm ghcr.io/auroratape/aurora-ltfs:X.Y.Z altfs -V`.
- [ ] `brew install auroratape/tap/aurora-ltfs` on a Mac when one is
      available (`homebrew.yml` installs it on a hosted runner, which cannot
      mount).
- [ ] On a real drive when one is available: format, mount, write, unmount,
      remount, `altfsck`, and the service stop with a mounted tape. Record
      the drive, firmware and host in the testing-status note.
- [ ] Write the release notes (above). For a final release that had
      candidates, delete the candidate tags and pre-releases.
- [ ] Close the milestone, create the next one, and remove `!!Backport!!`
      from everything the release shipped.
- [ ] Announce where the project announces (GitHub Release, discussions).

## Package repositories

The final releases are served as apt and dnf repositories on the GitHub
Pages site of this repository (#131):

- `apt/`: suite `noble`, component `main`, signed `InRelease` and
  `Release.gpg`; `aurora-ltfs.sources` is the deb822 entry, `aurora-ltfs.gpg`
  the key for its `Signed-By`.
- `rpm/el9/x86_64/`: `createrepo_c` metadata with a signed `repomd.xml`;
  `aurora-ltfs.repo` sets `repo_gpgcheck=1`, and `aurora-ltfs.asc` is the key.
  The packages themselves are not signed: the signed metadata carries the
  checksum of every package.

`packages.yml` builds both from scratch on every run from the `.deb` and
`.rpm` assets of all final Releases
(`.github/scripts/build-package-repos.sh`), so the repositories serve exactly
the files attached to the Releases. Pre-releases are never published there,
and every final 1.x release stays. `release.yml` starts the workflow on
`main` after a final release; run it by hand after deleting a release or
rotating the key. Its last job installs from the published repositories in
clean `ubuntu:24.04` and `rockylinux:9` containers.

### Signing key

The primary key never leaves the maintainer's offline storage: it only
certifies. A signing subkey, the only secret GitHub holds, signs the
repository metadata.

- GitHub Pages (Settings, Pages): source "GitHub Actions". The
  `github-pages` environment it creates deploys from `main` only, which is
  why `release.yml` starts `packages.yml` on `main` instead of running it
  from the tag.
- Environment `packages` (Settings, Environments): required reviewer the
  maintainer, deployment branches `main` only. Secret
  `PACKAGES_SIGNING_KEY` holds the armored secret subkey, variable
  `PACKAGES_SIGNING_KEY_FINGERPRINT` the fingerprint of the primary key.
  The workflow refuses a secret that contains the primary key.
- Creating the key, on an offline machine or at least a clean `GNUPGHOME`:

  ```
  export GNUPGHOME=/path/to/offline/gnupg
  gpg --quick-gen-key "Aurora LTFS packages <...>" rsa4096 cert 5y
  FPR=<fingerprint printed above>
  gpg --quick-add-key "$FPR" rsa4096 sign 5y
  gpg --output aurora-ltfs-revoke.asc --gen-revoke "$FPR"
  SUB=<fingerprint of the [S] subkey, from gpg -K --with-subkey-fingerprints>

  # The CI cannot type a passphrase: export the subkey without one,
  # through a throwaway keyring, so the offline one keeps its passphrase
  TMP=$(mktemp -d)
  gpg --armor --export-secret-subkeys "$SUB!" | GNUPGHOME=$TMP gpg --import
  # Old passphrase, then an empty one; "No secret key" is for the primary
  # key, which is not in this keyring
  GNUPGHOME=$TMP gpg --passwd "$FPR"
  GNUPGHOME=$TMP gpg --armor --export-secret-subkeys "$SUB!" > subkey.asc
  rm -rf "$TMP"
  ```

  Keep `GNUPGHOME` and the revocation certificate offline, put
  `subkey.asc` into the secret and delete it, and publish the fingerprint
  in the README. The workflow checks before signing that the secret holds
  the key of the variable, a signing subkey usable without a passphrase,
  and no primary key.
- Every change of the published key (a new subkey, a new expiry) has to
  reach the users: apt verifies against the copy in
  `/etc/apt/keyrings` and stops updating (`NO_PUBKEY`, or `EXPKEYSIG`
  once the old expiry passes) until the key is fetched again; dnf imports
  it again from the `gpgkey` URL by itself. Hence the long validity, and
  rotations announced in the release notes of the release before.
- Rotation, before the subkey expires: add a new signing subkey with the
  primary key, replace the secret with the export of the new subkey only
  (as above, through a throwaway keyring), run `packages.yml`. Extending an expiry instead: `gpg --quick-set-expire`,
  export, replace the secret, run the workflow.
- Compromise of the subkey: revoke it with the primary key, rotate as
  above, and tell users to fetch the key again. Compromise of the primary
  key: publish the revocation certificate, create a new key, and announce
  the new fingerprint on every channel the project uses.

## Homebrew tap

macOS is served by the tap `AuroraTape/homebrew-tap` (#131), a formula
that homebrew-core would not take because it needs macFUSE, which is closed
source. `homebrew.yml` renders it from `.github/homebrew/aurora-ltfs.rb.in`
for the highest final release:

- The source is the `make dist` tarball the rpm is built from, attached to
  the release as `aurora-ltfs-X.Y.Z.tar.gz` (for releases that lack it, it
  is taken out of the src.rpm). It is never replaced once attached.
- A bottle for Apple silicon is built on `macos-15` (`arm64_sequoia`, used
  on later macOS too) and attached to the same release. It is not
  relocatable (the binaries carry the path of `altfs.conf`): it is poured in
  the default prefix `/opt/homebrew` only, elsewhere the formula builds from
  source. Homebrew supports
  Intel Macs at Tier 3 only, without bottles for the dependencies either, so
  Intel Macs and older macOS build from source.
- The workflow pushes the formula to the tap with a deploy key, then
  installs it from the tap on a clean runner and checks that the bottle was
  poured. A pull request that changes the template or the workflow builds
  and tests the bottle without publishing.
- `release.yml` starts the workflow on `main` after a final release. It
  publishes only when the rendered formula differs from the one in the tap,
  so a patch release of an older line leaves the tap as it is. Run it by
  hand after changing the template: the same version gets a new bottle with
  the next `rebuild` number (a new asset name, so the published formula
  never points to a replaced file), which `brew upgrade` installs.
- The ICU dependency is versioned (`icu4c@78`): the bottle links that
  version. When homebrew-core moves to a new ICU, change the template and
  run the workflow.

Setup:

- The tap repository `AuroraTape/homebrew-tap`, public, created with a
  README so that `main` exists. If its `main` is protected, deploy keys
  must be allowed to bypass the rules: the workflow pushes directly.
- A deploy key with write access on the tap, created without a passphrase:
  `ssh-keygen -t ed25519 -N "" -C "aurora-ltfs homebrew.yml" -f homebrew-tap`.
  `homebrew-tap.pub` goes to the tap (Settings, Deploy keys, allow write
  access), `homebrew-tap` into the secret `HOMEBREW_TAP_DEPLOY_KEY` of the
  environment `homebrew` of this repository (deployment branches `main`
  only); then delete both files. The key can write to the tap only;
  replace it by creating a new one the same way.

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
- Signing of tags, of the rpm packages themselves and of the container
  images: the repository signing key exists now; whether it, or a separate
  key, signs those is still open.
