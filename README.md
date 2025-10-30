# Hero Coins Bot v1.1

A Discord bot for tracking **Hero Coins** and **Big Coins** in tabletop RPGs (especially D&D 5e).  
Perfect for online campaigns that use the **Hero Coin system by Bob World Builder** - supports per-channel ledgers, GM management, backups, and version info.

---

## Features
- Track Hero Coins and Big Coins per player or party
- Award or spend coins with simple slash commands
- Optional **per-channel** or **server-wide** tracking
- Assign or change GM role dynamically with `/setgmrole`
- View all authorized GMs with `/gmstatus`
- Backup and restore data as JSON
- Logs all activity to a rotating file
- `/version` and `/help` commands for quick reference

---

## Setup

### 1 Requirements
- Python 3.10 or newer (for local use)
- Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications)

### 2 Installation (local)
```bash
pip install -r requirements.txt


