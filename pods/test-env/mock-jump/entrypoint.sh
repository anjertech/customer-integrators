#!/usr/bin/env bash
#
# Mock jump host: create the SSH user with a password from env, enable password auth
# and TCP forwarding, then run sshd in the foreground.
set -euo pipefail

SSH_USER="${SSH_USER:-PRESA}"
SSH_PASSWORD="${SSH_PASSWORD:?SSH_PASSWORD is required}"

# Create (or update) the user and set its password non-interactively.
if ! id "$SSH_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /usr/sbin/nologin "$SSH_USER"
fi
echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd

# Host keys (generated once per container).
ssh-keygen -A

# sshd config: password auth on, TCP forwarding on (so -L forwards work), no shell needed.
cat > /etc/ssh/sshd_config.d/mock-jump.conf <<EOF
PasswordAuthentication yes
PubkeyAuthentication no
AllowTcpForwarding yes
PermitOpen any
X11Forwarding no
PermitTTY no
AllowUsers ${SSH_USER}
EOF

echo "[mock-jump] sshd ready for ${SSH_USER} (password auth, TCP forwarding on)"
exec /usr/sbin/sshd -D -e
