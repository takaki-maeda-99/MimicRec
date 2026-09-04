#!/usr/bin/env bash
# Install path-resolved systemd user units used by MimicRec's Settings UI.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
MIMICREC_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mimicrec"
CONTROL_ENV="$MIMICREC_CONFIG_DIR/service-control.env"

usage() {
    echo "usage: $0 [--uninstall]"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl --user stop mimicrec-rebotarm.service mimicrec-so101.service mimicrec-quest.service 2>/dev/null || true
    systemctl --user disable mimicrec-rebotarm.service mimicrec-so101.service mimicrec-quest.service 2>/dev/null || true
    rm -f \
        "$UNIT_DIR/mimicrec-rebotarm.service" \
        "$UNIT_DIR/mimicrec-so101.service" \
        "$UNIT_DIR/mimicrec-quest.service" \
        "$CONTROL_ENV"
    systemctl --user daemon-reload
    echo "MimicRec user services removed."
    exit 0
elif [[ -n "${1:-}" ]]; then
    usage >&2
    exit 2
fi

if [[ "$REPO_ROOT" == *'|'* || "$REPO_ROOT" == *'&'* || "$REPO_ROOT" == *'"'* || "$REPO_ROOT" == *'\'* || "$REPO_ROOT" =~ [[:space:]] ]]; then
    echo "error: repository path contains a character unsupported by the unit installer" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "error: systemctl is required" >&2
    exit 1
fi

mkdir -p "$UNIT_DIR" "$MIMICREC_CONFIG_DIR" "$HOME/.ros"
for name in mimicrec-rebotarm mimicrec-so101 mimicrec-quest; do
    sed "s|@REPO_ROOT@|$REPO_ROOT|g" \
        "$REPO_ROOT/scripts/systemd/$name.service.in" \
        > "$UNIT_DIR/$name.service"
done

chmod 0644 \
    "$UNIT_DIR/mimicrec-rebotarm.service" \
    "$UNIT_DIR/mimicrec-so101.service" \
    "$UNIT_DIR/mimicrec-quest.service"
printf '%s\n' 'MIMICREC_SERVICE_CONTROL_ENABLED=1' > "$CONTROL_ENV"
chmod 0600 "$CONTROL_ENV"

systemctl --user daemon-reload

cat <<EOF
MimicRec user services installed for:
  $REPO_ROOT

Neither hardware service was started or enabled at login.
Restart the MimicRec backend, then open Settings → Managed services.

Logs:
  journalctl --user -u mimicrec-rebotarm.service -f
  journalctl --user -u mimicrec-so101.service -f
  journalctl --user -u mimicrec-quest.service -f
EOF
