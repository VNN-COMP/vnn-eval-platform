#!/usr/bin/env bash
# Turn a fresh Ubuntu container into an SSH-reachable `ubuntu` node, so the same
# per-step scripts that SSH into ubuntu@<ip> on EC2 work unchanged locally.
#
# Run as root by LocalDockerBackend (docker exec -d -u 0) with $AUTHORIZED_KEY set
# to the backend's public key. Writes /tmp/vnncomp_ready once sshd is up, which is
# how sync_instances marks the node reachable.
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update
# python3-pip/venv and a compiler are part of the node contract, not a tool's job:
# install_tool.sh is expected to find a working Python toolchain (the AWS AMIs ship
# one via anaconda).
apt-get install -y --no-install-recommends \
    openssh-server sudo git curl ca-certificates tmux \
    python3 python3-pip python3-venv build-essential

# `ubuntu` user with passwordless sudo (the run scripts use sudo apt-get, etc.).
id -u ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu
echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu
chmod 440 /etc/sudoers.d/ubuntu

# Install the backend's public key so it can SSH in.
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
printf '%s\n' "${AUTHORIZED_KEY:-}" > /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys

# Host keys + key-only sshd.
mkdir -p /run/sshd
ssh-keygen -A
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
/usr/sbin/sshd

touch /tmp/vnncomp_ready
