#!/bin/sh
# Run the server as an unprivileged user (defense in depth: an RCE in request
# handling — image parsing, auth, the Claude call — must not land as root).
#
# Railway mounts the persistent volume at $SAREGAMAPIC_DATA_DIR owned by root,
# and the mount REPLACES whatever ownership we set at build time, so ownership
# has to be fixed HERE — at container start, after the volume is mounted and
# before we drop privileges. Railway's only first-party knob (RAILWAY_RUN_UID=0)
# just forces the container back to root, so this root-then-drop entrypoint is
# the supported pattern for non-root + a mounted volume. Do NOT set
# RAILWAY_RUN_UID on the service. See the vault decision record
# 2026-07-26-non-root-container.
set -e

data_dir="${SAREGAMAPIC_DATA_DIR:-/data}"
mkdir -p "$data_dir"
chown -R appuser:appuser "$data_dir"

# exec so the server replaces gosu and receives SIGTERM directly for graceful
# shutdown; gosu setuids to appuser without leaving a root process behind.
exec gosu appuser "$@"
