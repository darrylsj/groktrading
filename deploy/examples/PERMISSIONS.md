# Env file permissions (examples only — no hostnames or IPs)

# As root, after copying an example to the real path:
#   install -o root -g root -m 0600 finnhub.env.example /etc/trading-desk/finnhub.env
#   install -o root -g root -m 0600 grok-webhook.env.example /etc/trading-desk/grok-webhook.env
# Then edit the real files in place. Never chmod 0644 a token file.
# Never put tokens in unit files, git, chat logs, or tape JSON.
# This repository is not a live deployment and must not restart remote hosts.
