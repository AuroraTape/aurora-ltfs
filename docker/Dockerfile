# Aurora LTFS container image
#
# Built from the .deb packages produced by the `deb` job in
# .github/workflows/release.yml, so the image content is identical to the
# deb release. The build context must contain the packages under debs/.
#
# The image has no entrypoint on purpose: it is a toolbox. Invoke the
# command you need explicitly, e.g.:
#
#   docker run --rm -it \
#     --device /dev/fuse --device /dev/sg0 \
#     --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
#     ghcr.io/auroratape/aurora-ltfs:<version> \
#     altfs -o devname=/dev/sg0 /ltfs

FROM ubuntu:24.04

COPY debs/ /tmp/debs/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        /tmp/debs/libaltfs0_*.deb \
        /tmp/debs/altfs_*.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/debs

# Default mount point for `altfs`
RUN mkdir -p /ltfs
