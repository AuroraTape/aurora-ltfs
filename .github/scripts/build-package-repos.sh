#!/bin/bash
#
# Build the apt and dnf repositories served on GitHub Pages (#131).
#
# Usage: build-package-repos.sh <assets dir> <site dir> <base url> <key fingerprint>
#
#   <assets dir>       the packages attached to the final GitHub Releases, all in one
#                      directory: *.deb for Ubuntu 24.04, *.el9.*.rpm for Rocky Linux 9
#   <site dir>         created; becomes the root of the Pages site
#   <base url>         where the site is served, e.g. https://auroratape.github.io/aurora-ltfs
#   <key fingerprint>  the primary key; its signing subkey, in the gpg keyring, signs
#
# The repositories are built from scratch every time, from the Release assets: the
# packages served are exactly the ones attached to the Releases. Needs apt-ftparchive
# (apt-utils), createrepo_c and gpg.

set -euo pipefail

if [ $# -ne 4 ]; then
	echo "Usage: $0 <assets dir> <site dir> <base url> <key fingerprint>" >&2
	exit 2
fi

ASSETS=$(realpath "$1")
SITE=$2
BASE_URL=${3%/}
KEY=$4

# The suite and the target the packages are built on (release.yml); a second suite or
# target comes with the move to the next platform releases (#80)
APT_SUITE=noble
RPM_TARGET=el9
RPM_ARCH=x86_64

shopt -s nullglob
debs=("$ASSETS"/*.deb)
rpms=()
for rpm in "$ASSETS"/*."$RPM_TARGET"."$RPM_ARCH".rpm; do
	# The debug symbols stay Release assets only, as the .ddeb files do on the apt side
	case "$rpm" in
	*-debuginfo-*|*-debugsource-*) ;;
	*) rpms+=("$rpm") ;;
	esac
done
shopt -u nullglob
if [ ${#debs[@]} -eq 0 ] || [ ${#rpms[@]} -eq 0 ]; then
	echo "No .deb or no .$RPM_TARGET.$RPM_ARCH.rpm in $ASSETS" >&2
	exit 1
fi

mkdir -p "$SITE"
SITE=$(realpath "$SITE")

sign() {
	gpg --batch --yes --local-user "$KEY" "$@"
}

# apt: dists/<suite>/main/binary-amd64, packages in pool/main
APT=$SITE/apt
mkdir -p "$APT/pool/main" "$APT/dists/$APT_SUITE/main/binary-amd64"
cp "${debs[@]}" "$APT/pool/main/"
(
	cd "$APT"
	apt-ftparchive packages pool/main > "dists/$APT_SUITE/main/binary-amd64/Packages"
	gzip -9 -k "dists/$APT_SUITE/main/binary-amd64/Packages"
	apt-ftparchive \
		-o APT::FTPArchive::Release::Origin="Aurora LTFS" \
		-o APT::FTPArchive::Release::Label="Aurora LTFS" \
		-o APT::FTPArchive::Release::Suite="$APT_SUITE" \
		-o APT::FTPArchive::Release::Codename="$APT_SUITE" \
		-o APT::FTPArchive::Release::Architectures="amd64" \
		-o APT::FTPArchive::Release::Components="main" \
		release "dists/$APT_SUITE" > Release.tmp
	# Written aside: a Release file already in place would list itself
	mv Release.tmp "dists/$APT_SUITE/Release"
	sign --clearsign -o "dists/$APT_SUITE/InRelease" "dists/$APT_SUITE/Release"
	sign --armor --detach-sign -o "dists/$APT_SUITE/Release.gpg" "dists/$APT_SUITE/Release"
)

# dnf: rpm/<target>/<arch>, with a signed repomd.xml (repo_gpgcheck)
RPM=$SITE/rpm/$RPM_TARGET/$RPM_ARCH
mkdir -p "$RPM"
cp "${rpms[@]}" "$RPM/"
createrepo_c --quiet "$RPM"
sign --armor --detach-sign -o "$RPM/repodata/repomd.xml.asc" "$RPM/repodata/repomd.xml"

# The public key, armored for dnf and binary for apt's Signed-By
gpg --batch --export --armor "$KEY" > "$SITE/aurora-ltfs.asc"
gpg --batch --export "$KEY" > "$SITE/aurora-ltfs.gpg"
FINGERPRINT=$(gpg --batch --with-colons --fingerprint "$KEY" | awk -F: '$1 == "fpr" { print $10; exit }')

cat > "$SITE/aurora-ltfs.sources" <<EOF
Types: deb
URIs: $BASE_URL/apt
Suites: $APT_SUITE
Components: main
Signed-By: /etc/apt/keyrings/aurora-ltfs.gpg
EOF

# $releasever is the major version on Rocky Linux and RHEL: el9
cat > "$SITE/aurora-ltfs.repo" <<EOF
[aurora-ltfs]
name=Aurora LTFS
baseurl=$BASE_URL/rpm/el\$releasever/\$basearch
enabled=1
repo_gpgcheck=1
gpgcheck=0
gpgkey=$BASE_URL/aurora-ltfs.asc
EOF

# A landing page until the documentation site of #91 takes the root
cat > "$SITE/index.html" <<EOF
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aurora LTFS packages</title>
</head>
<body>
<h1>Aurora LTFS packages</h1>
<p>apt and dnf repositories of the final releases of
<a href="https://github.com/AuroraTape/aurora-ltfs">Aurora LTFS</a>.
The setup is described in the README, under "Installing packages".</p>
<ul>
<li>Ubuntu 24.04: <a href="aurora-ltfs.sources">aurora-ltfs.sources</a>, key <a href="aurora-ltfs.gpg">aurora-ltfs.gpg</a></li>
<li>Rocky Linux 9 / RHEL 9: <a href="aurora-ltfs.repo">aurora-ltfs.repo</a>, key <a href="aurora-ltfs.asc">aurora-ltfs.asc</a></li>
</ul>
<p>Signing key fingerprint: <code>$FINGERPRINT</code></p>
</body>
</html>
EOF

echo "apt: ${#debs[@]} packages, dnf: ${#rpms[@]} packages, key $FINGERPRINT"
