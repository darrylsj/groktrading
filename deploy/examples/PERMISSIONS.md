# Env file permissions (examples only — no hostnames or IPs)

# As root, after copying an example to the real path (skip if dest exists):
#   install -o root -g root -m 0600 finnhub.env.example /etc/trading-desk/finnhub.env
#   install -o root -g root -m 0600 grok-webhook.env.example /etc/trading-desk/grok-webhook.env
#   install -o root -g root -m 0600 groktrading.env.example /etc/trading-desk/groktrading.env
#   install -o root -g root -m 0600 unusual-whales.env.example /etc/trading-desk/unusual-whales.env
#   install -o root -g root -m 0600 tradier-sandbox.env.example /etc/trading-desk/tradier-sandbox.env
#   install -o root -g root -m 0600 tradier-live.env.example /etc/trading-desk/tradier-live.env
#   install -o root -g root -m 0600 trading-desk.env.example /opt/trading-desk/.env
# Then edit the real files in place. Never chmod 0644 a token file.
# Never put tokens in unit files, git, chat logs, or tape JSON.
# scripts/install_helsinki.sh creates /etc/trading-desk (0700) but does not
# overwrite existing *.env and does not copy real secrets.
# Companion / retain example units run as User=tradingdesk (not root).
# systemd reads root-owned 0600 EnvironmentFile= before dropping privileges.
# Scoped writable dirs for tradingdesk:
#   /var/lib/trading-desk/ledger   (uw_flow.sqlite, seen JSON)
#   /var/lib/trading-desk/state    (companion JSON / JSONL)
# Do not grant tradingdesk write to /etc/trading-desk or /opt/trading-desk/.env.
# This repository is not a live deployment and must not restart remote hosts.
