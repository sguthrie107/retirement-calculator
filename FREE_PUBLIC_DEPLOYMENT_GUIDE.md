# Run This Webapp Publicly (24/7) for Free

This guide shows how to host your FastAPI retirement app so it is publicly accessible without you manually starting it on your desktop.

---

## Quick Reality Check (Important)

You asked for **permanently running + public + free**.

- That combination is possible, but with caveats.
- Most “free tier” PaaS platforms (Render/Railway/etc.) can sleep, pause, or change limits.
- The most stable free path is usually a small **Always Free VM** (Oracle Cloud), where *you* run the service 24/7.

If your goal is true always-on behavior with zero monthly cost, use **Option A** below.

---

## Option A (Recommended): Oracle Cloud Always Free VM + systemd + Caddy

This is the best free path for “always running” behavior.

## What you’ll get

- Your app running as a Linux service (auto-start on reboot)
- Public HTTPS URL
- No need to keep your home desktop on
- Access for anyone on the internet

---

## 1) Create free infrastructure

1. Create an Oracle Cloud account (Always Free eligible).
2. Create a VM:
   - OS: **Ubuntu 22.04 LTS**
   - Shape: **VM.Standard.E2.1.Micro** (Always Free)
3. Add your SSH public key during VM setup.
4. In Oracle networking/security list, allow inbound:
   - `22` (SSH)
   - `80` (HTTP)
   - `443` (HTTPS)

---

## 2) SSH into the VM

From your desktop PowerShell:

```powershell
ssh ubuntu@<YOUR_VM_PUBLIC_IP>
```

---

## 3) Install runtime dependencies

On the Ubuntu VM:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
```

Install Caddy (reverse proxy + automatic HTTPS):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

---

## 4) Clone your app and install Python deps

```bash
cd /opt
sudo git clone <YOUR_GIT_REPO_URL> retirement-calculator
sudo chown -R ubuntu:ubuntu /opt/retirement-calculator
cd /opt/retirement-calculator
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Optional sanity test:

```bash
source /opt/retirement-calculator/.venv/bin/activate
cd /opt/retirement-calculator
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Stop with `Ctrl+C`.

---

## 5) Create a systemd service (auto-start, auto-restart)

Create service file:

```bash
sudo tee /etc/systemd/system/retirement-calculator.service > /dev/null << 'EOF'
[Unit]
Description=Retirement Calculator FastAPI
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/retirement-calculator
Environment="PYTHONPATH=/opt/retirement-calculator"
ExecStart=/opt/retirement-calculator/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable retirement-calculator
sudo systemctl start retirement-calculator
sudo systemctl status retirement-calculator
```

View logs:

```bash
journalctl -u retirement-calculator -f
```

---

## 6) Put HTTPS in front with Caddy

### If you have a domain (recommended)

Point DNS `A` record to your VM IP, then:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
yourdomain.com {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF

sudo systemctl reload caddy
```

Caddy will automatically provision TLS certs.

### If you do not have a domain yet

You can still serve over HTTP using IP (not ideal):

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
:80 {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF

sudo systemctl reload caddy
```

Then access:

```text
http://<YOUR_VM_PUBLIC_IP>
```

---

## 7) Persist and protect your data

Your app currently uses SQLite (`retirement.db`).

Create backups:

```bash
mkdir -p /opt/retirement-calculator/backups
cp /opt/retirement-calculator/retirement.db /opt/retirement-calculator/backups/retirement-$(date +%F).db
```

Recommended cron backup (daily):

```bash
(crontab -l 2>/dev/null; echo "0 2 * * * cp /opt/retirement-calculator/retirement.db /opt/retirement-calculator/backups/retirement-$(date +\\%F).db") | crontab -
```

---

## 8) Deploy updates when you push code

On VM:

```bash
cd /opt/retirement-calculator
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart retirement-calculator
```

---

## 9) Operational checklist (keep it truly “always on”)

- `sudo systemctl is-active retirement-calculator` → should be `active`
- `sudo systemctl is-active caddy` → should be `active`
- verify public URL from phone/cellular network
- keep Oracle free account in good standing
- backup `retirement.db`

---

## Option B (Easier but less “permanent”): Render/Railway free web service

Pros:
- very easy setup
- no server maintenance

Cons:
- free instances may sleep or be limited
- not guaranteed always-on

Use this only if occasional cold starts are acceptable.

---

## Recommended final setup for your goal

Given your requirement (“accessible by anyone, permanently, for free”), use:

- **Oracle Always Free VM**
- **systemd** for app process
- **Caddy** for reverse proxy + HTTPS
- **(Optional) your own domain** for stable URL

This gives you the closest thing to a professional, always-available backend at zero monthly cost.

---

## Troubleshooting quick commands

```bash
sudo systemctl status retirement-calculator --no-pager
sudo systemctl status caddy --no-pager
journalctl -u retirement-calculator -n 100 --no-pager
journalctl -u caddy -n 100 --no-pager
ss -tulpen | grep -E '8000|80|443'
```

---

If you want, I can also add a second markdown with **exact GitHub Actions auto-deploy** so every push to `main` updates the VM automatically.