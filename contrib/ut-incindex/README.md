# Unit Tests for incremental index

This is a directory for having unit tests for incremental index feature.

## How to run

### Basic operation test

  1. `cd` to this directory
  2. Run the basic test with `./ut-basic.sh [mount_point]`
      - The test script formats a (filebackend) tape under `/tmp/altfstape`, start altfs and stop altfs automatically.
      - If `[mount_point]` is not specified, the script uses `/tmp/mnt`
      - You can pass the specific `altfs` binary directory with the environmental value `ALTFS_BIN_PATH`
