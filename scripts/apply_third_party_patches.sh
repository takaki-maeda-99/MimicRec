#!/usr/bin/env bash
# Apply MimicRec-owned overlays to pinned third-party submodules.
#
# The submodule gitlinks intentionally point at commits available from their
# public remotes. Portable local changes live as reviewable patches in the
# parent repository so a fresh clone does not depend on unpublished commits.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_ROOT="$REPO_ROOT/patches"

log() { echo "[third-party] $*"; }
die() { echo "[third-party] error: $*" >&2; exit 1; }

apply_series() {
    local relative_path="$1"
    local expected_commit="$2"
    local patch_directory="$3"
    local checkout="$REPO_ROOT/$relative_path"
    local actual_commit
    local patch
    local patches=()

    [[ -d "$checkout/.git" || -f "$checkout/.git" ]] \
        || die "$relative_path is not initialized; run git submodule update --init --recursive"

    actual_commit="$(git -C "$checkout" rev-parse HEAD)"
    [[ "$actual_commit" == "$expected_commit" ]] \
        || die "$relative_path is at $actual_commit; expected pinned commit $expected_commit"

    shopt -s nullglob
    patches=("$PATCH_ROOT/$patch_directory"/*.patch)
    shopt -u nullglob
    [[ ${#patches[@]} -gt 0 ]] || die "no patches found for $relative_path"

    for patch in "${patches[@]}"; do
        if git -C "$checkout" apply --reverse --check "$patch" >/dev/null 2>&1; then
            log "$relative_path: $(basename "$patch") already applied"
        elif git -C "$checkout" apply --check "$patch"; then
            git -C "$checkout" apply "$patch"
            log "$relative_path: applied $(basename "$patch")"
        else
            die "cannot apply $(basename "$patch") cleanly to $relative_path"
        fi
    done
}

apply_series \
    "third_party/reBotArm_control_py" \
    "72ee481762280f90ecda96e19d7b6ec62e885114" \
    "reBotArm_control_py"

apply_series \
    "third_party/unity_ros_teleoperation" \
    "521c42982c8b266a28d723a58490253bb4cfe31c" \
    "unity_ros_teleoperation"

log "portable overlays are ready"
