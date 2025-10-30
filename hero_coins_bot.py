# Hero Coins Discord Bot v1.1
# Complete feature set: per-channel toggle, GM management, backup/restore, logging, help/version commands
# Author: ChatGPT + Sean Ashcraft, 2025

import os
import json
import sys
import logging
import pathlib
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional
import platform
from datetime import datetime

from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands

# -------------------------------------------------------------------
# Environment & Logging
# -------------------------------------------------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GM_USER_ID = os.getenv("GM_USER_ID")
GM_ROLE_NAME = os.getenv("GM_ROLE_NAME")
PER_CHANNEL = os.getenv("PER_CHANNEL", "0") == "1"

BASE_DIR = pathlib.Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "hero_coins.log"

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(fmt)
root_logger.addHandler(handler)

logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

def excepthook(exc_type, exc, tb):
    logging.exception("Uncaught exception", exc_info=(exc_type, exc, tb))
sys.excepthook = excepthook

# -------------------------------------------------------------------
# Data & Helpers
# -------------------------------------------------------------------
DATA_FILE = "hero_coins_data.json"
EMOJI_COIN = "🪙"
EMOJI_BIG = "🏅"

def load_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logging.exception("Failed to load data file")
        return {}

def save_data(data: Dict):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def ensure_guild_store(data: Dict, guild_id: int) -> Dict:
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {}
    if "party" in data[gid] or "members" in data[gid]:
        old_party = data[gid].get("party", {"big": 0})
        old_members = data[gid].get("members", {})
        data[gid] = {"channels": {"_server": {"party": old_party, "members": old_members}}}
    if "channels" not in data[gid]:
        data[gid]["channels"] = {}
    return data[gid]

def get_scope_key(interaction: discord.Interaction) -> str:
    if PER_CHANNEL and interaction.channel:
        return f"ch_{interaction.channel.id}"
    return "_server"

def ensure_scope_store(gstore: Dict, scope_key: str) -> Dict:
    channels = gstore["channels"]
    if scope_key not in channels:
        channels[scope_key] = {"party": {"big": 0}, "members": {}}
    return channels[scope_key]

def ensure_member(store: Dict, member_id: int) -> Dict:
    mid = str(member_id)
    if mid not in store["members"]:
        store["members"][mid] = {"coins": 0}
    return store["members"][mid]

def authorized(interaction: discord.Interaction) -> bool:
    if GM_USER_ID:
        try:
            if int(GM_USER_ID) == interaction.user.id:
                return True
        except ValueError:
            pass
    if GM_ROLE_NAME and isinstance(interaction.user, discord.Member):
        if any(r.name == GM_ROLE_NAME for r in interaction.user.roles):
            return True
    if interaction.user.guild_permissions.administrator:
        return True
    return False

def render_tally(store: Dict, guild: discord.Guild) -> str:
    lines: List[str] = []
    party_big = store["party"].get("big", 0)
    lines.append(f"Party: {EMOJI_BIG * party_big}" if party_big > 0 else "Party:")
    members_map = store["members"]
    id_to_member: Dict[str, discord.Member] = {str(m.id): m for m in guild.members if not m.bot}
    for member in sorted(id_to_member.values(), key=lambda m: m.display_name.lower()):
        rec = members_map.get(str(member.id), {"coins": 0})
        coins = rec.get("coins", 0)
        display = f"{EMOJI_COIN * coins}" if coins > 0 else ""
        lines.append(f"{member.display_name}: {display}")
    for mid, rec in members_map.items():
        if mid not in id_to_member:
            coins = rec.get("coins", 0)
            if coins > 0:
                lines.append(f"(Former member {mid}): {EMOJI_COIN * coins}")
    return "\n".join(lines) if lines else "No players yet."

# -------------------------------------------------------------------
# Bot Setup
# -------------------------------------------------------------------
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    logging.info(f"Bot ready as {bot.user} (ID: {bot.user.id})")

# -------------------------------------------------------------------
# Core Commands
# -------------------------------------------------------------------
@bot.tree.command(name="coins", description="Show current Hero Coin tallies.")
async def coins(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Use this in a server.", ephemeral=True)
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    await interaction.response.send_message(f"**Hero Coins**\n{render_tally(store, interaction.guild)}")

@bot.tree.command(name="coin", description="Give a player 1 Hero Coin (GM only).")
@app_commands.describe(user="Player to receive a coin")
async def coin(interaction: discord.Interaction, user: discord.Member):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    ensure_member(store, user.id)["coins"] += 1
    save_data(data)
    await interaction.response.send_message(f"**Awarded {user.display_name} {EMOJI_COIN}.**\n{render_tally(store, interaction.guild)}")

@bot.tree.command(name="spend", description="Spend 1 Hero Coin from each mentioned player (GM only).")
@app_commands.describe(users="Mention one or more players separated by spaces")
async def spend(interaction: discord.Interaction, users: str):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    mentions = [m.strip("<@!>") for m in users.split() if m.startswith("<@")]
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    msgs = []
    for mid in mentions:
        rec = store["members"].get(mid)
        if not rec or rec.get("coins", 0) <= 0:
            msgs.append(f"<@{mid}> has no {EMOJI_COIN} to spend.")
        else:
            rec["coins"] -= 1
            msgs.append(f"<@{mid}> spent {EMOJI_COIN}.")
    save_data(data)
    await interaction.response.send_message(f"**Spend Result**\n" + "\n".join(msgs) + f"\n\n{render_tally(store, interaction.guild)}")

@bot.tree.command(name="bigcoin", description="Add 1 Party Big Coin (GM only).")
async def bigcoin(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    store["party"]["big"] += 1
    save_data(data)
    await interaction.response.send_message(f"**Party gains {EMOJI_BIG}.**\n{render_tally(store, interaction.guild)}")

@bot.tree.command(name="bigspend", description="Spend 1 Party Big Coin (GM only).")
async def bigspend(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    if store["party"]["big"] <= 0:
        return await interaction.response.send_message(f"Party has no {EMOJI_BIG} to spend.", ephemeral=True)
    store["party"]["big"] -= 1
    save_data(data)
    await interaction.response.send_message(f"**Party spent {EMOJI_BIG}.**\n{render_tally(store, interaction.guild)}")

# -------------------------------------------------------------------
# GM Management Commands
# -------------------------------------------------------------------
@bot.tree.command(name="setgmrole", description="Change the role name recognized as Game Master (GM only).")
@app_commands.describe(role_name="Exact name of the role to grant GM permissions.")
async def setgmrole(interaction: discord.Interaction, role_name: str):
    global GM_ROLE_NAME
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    guild_role = discord.utils.find(lambda r: r.name == role_name, interaction.guild.roles)
    if not guild_role:
        return await interaction.response.send_message(f"❌ Role `{role_name}` not found.", ephemeral=True)
    GM_ROLE_NAME = role_name
    await interaction.response.send_message(f"✅ Game Master role updated to **{GM_ROLE_NAME}**.", ephemeral=True)

@bot.tree.command(name="gmstatus", description="List who currently qualifies as GM (authorized only).")
async def gmstatus(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    gms = []
    for member in interaction.guild.members:
        if member.bot:
            continue
        if interaction.user.guild_permissions.administrator or \
           (GM_ROLE_NAME and any(r.name == GM_ROLE_NAME for r in member.roles)) or \
           (GM_USER_ID and str(member.id) == GM_USER_ID):
            gms.append(member.display_name)
    gm_list = ", ".join(sorted(gms)) if gms else "No GMs found."
    await interaction.response.send_message(
        f"**Current Game Masters:**\n{gm_list}\n\nGM Role: {GM_ROLE_NAME or 'None set'}",
        ephemeral=True
    )

# -------------------------------------------------------------------
# Info, Utility, and Data Commands
# -------------------------------------------------------------------
@bot.tree.command(name="ledgerinfo", description="Show ledger scope and summary (GM only).")
async def ledgerinfo(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    data = load_data()
    gstore = ensure_guild_store(data, interaction.guild_id)
    store = ensure_scope_store(gstore, get_scope_key(interaction))
    total_players = len(store["members"])
    total_coins = sum(m.get("coins", 0) for m in store["members"].values())
    total_big = store["party"].get("big", 0)
    scope_name = f"Channel-specific ledger for #{interaction.channel.name}" if PER_CHANNEL else "Server-wide ledger"
    msg = f"**Ledger Info**\nScope: {scope_name}\nParty 🏅: {total_big}\nPlayers: {total_players}\nTotal 🪙: {total_coins}"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="backupdata", description="Export Hero Coins data as JSON (GM only).")
async def backupdata(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    if not os.path.exists(DATA_FILE):
        return await interaction.response.send_message("No data file found.", ephemeral=True)
    backup_path = f"backup_{interaction.guild_id}.json"
    with open(DATA_FILE, "r", encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    await interaction.response.send_message(file=discord.File(backup_path))
    os.remove(backup_path)

@bot.tree.command(name="restoredata", description="Restore Hero Coins data from a backup JSON (GM only).")
@app_commands.describe(file="Upload a backup JSON file exported by /backupdata")
async def restoredata(interaction: discord.Interaction, file: discord.Attachment):
    if not authorized(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    if not file.filename.endswith(".json"):
        return await interaction.response.send_message("Upload a .json file.", ephemeral=True)
    data_bytes = await file.read()
    text = data_bytes.decode("utf-8")
    try:
        restored = json.loads(text)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(restored, f, ensure_ascii=False, indent=2)
        await interaction.response.send_message(f"✅ Data restored from `{file.filename}`.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Restore failed: {e}", ephemeral=True)

@bot.tree.command(name="version", description="Show bot version, Python version, and data info.")
async def version(interaction: discord.Interaction):
    bot_version = "1.1.0"
    python_version = platform.python_version()
    data_mtime = datetime.fromtimestamp(os.path.getmtime(DATA_FILE)).strftime("%Y-%m-%d %H:%M:%S") if os.path.exists(DATA_FILE) else "No data yet."
    info = (
        f"**Hero Coins Bot v{bot_version}**\n"
        f"Python: {python_version}\n"
        f"Data last updated: {data_mtime}\n"
        f"Ledger mode: {'Per-channel' if PER_CHANNEL else 'Server-wide'}\n"
        f"Log file: `{LOG_FILE.name}`"
    )
    await interaction.response.send_message(info, ephemeral=True)

@bot.tree.command(name="help", description="List all Hero Coins commands and their usage.")
async def help_command(interaction: discord.Interaction):
    commands_text = (
        "**Hero Coins Bot Commands**\n\n"
        "🪙 **Player / Table Commands**\n"
        "`/coins` — Show current Hero Coin tallies.\n\n"
        "🏅 **Game Master Commands**\n"
        "`/coin @user` — Give a player 1 Hero Coin.\n"
        "`/spend @user [@user…]` — Spend 1 Hero Coin per listed player.\n"
        "`/poolbig` — Spend 5 🪙 across players to gain 1 Party 🏅.\n"
        "`/bigcoin` — Add 1 Party 🏅.\n"
        "`/bigspend` — Spend 1 Party 🏅.\n"
        "`/resetcoins` — Reset for new session.\n\n"
        "🧾 **Ledger Management**\n"
        "`/ledgerinfo` — Show current ledger stats.\n"
        "`/backupdata` — Export data as JSON.\n"
        "`/restoredata` — Restore from JSON.\n\n"
        "🎮 **GM Management**\n"
        "`/setgmrole` — Change GM role dynamically.\n"
        "`/gmstatus` — Show all users with GM access.\n\n"
        "🔧 **Maintenance**\n"
        "`/version` — Show bot version & data info.\n"
        "`/help` — Show this list.\n\n"
        f"_Ledger mode: {'Per-channel' if PER_CHANNEL else 'Server-wide'}_\n"
        "💡 Tip: Use `/version` anytime to check bot health or data timestamp."
    )
    await interaction.response.send_message(commands_text, ephemeral=True)

# -------------------------------------------------------------------
# Run Bot
# -------------------------------------------------------------------
if not TOKEN:
    print("ERROR: DISCORD_TOKEN missing in .env")
    sys.exit(1)

bot.run(TOKEN)
