import itertools
import logging
import os
import random

import aiohttp
import discord
from discord.ext import tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discord_bot")

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
DISCORD_ALLOWED_USER_IDS = os.environ.get("DISCORD_ALLOWED_USER_IDS", "").strip()

# Fixed defaults requested for this bot: "normal" darkness = the web UI's
# middle slider position (3 of 5), "medium" font size = the web UI's middle
# text_columns value (32 columns). These only apply to plain-text messages;
# TiMini Print rasterizes image/PDF attachments as-is, so text_columns has
# no effect on those (see print_server.py build_cmd()).
DEFAULT_DARKNESS = 3
DEFAULT_TEXT_COLUMNS = 32

PRINT_SERVER_URL = "http://localhost:8099"

IMAGE_CONTENT_TYPES = ("image/png", "image/jpeg", "image/gif", "image/bmp")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf")

if not DISCORD_BOT_TOKEN:
    raise SystemExit("DISCORD_BOT_TOKEN is not set; refusing to start.")
if not DISCORD_CHANNEL_ID:
    raise SystemExit("DISCORD_CHANNEL_ID is not set; refusing to start.")

try:
    CHANNEL_ID = int(DISCORD_CHANNEL_ID)
except ValueError:
    raise SystemExit(f"DISCORD_CHANNEL_ID '{DISCORD_CHANNEL_ID}' is not a valid integer.")

# Optional comma-separated allowlist, e.g. "111111111111111111,222222222222222222".
# Leave DISCORD_ALLOWED_USER_IDS blank to allow anyone who can post in the
# configured channel.
ALLOWED_USER_IDS = set()
if DISCORD_ALLOWED_USER_IDS:
    for part in DISCORD_ALLOWED_USER_IDS.split(","):
        part = part.strip()
        if part:
            try:
                ALLOWED_USER_IDS.add(int(part))
            except ValueError:
                log.warning("Ignoring invalid user id in DISCORD_ALLOWED_USER_IDS: %r", part)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Idle "custom status" text the bot cycles through while waiting for a print
# job. Shuffled once at startup, then cycled in order so the same phrase
# doesn't repeat back-to-back.
IDLE_STATUSES = [
    "waiting to print \U0001F5A8",
    "talking to the printer service",
    "wishing i was printing",
    "counting thermal paper rolls",
    "dreaming of receipts",
    "watching for print jobs",
    "thermal paper go brrr",
]
_status_cycle = itertools.cycle(random.sample(IDLE_STATUSES, len(IDLE_STATUSES)))


@tasks.loop(seconds=120)
async def rotate_status():
    await client.change_presence(activity=discord.CustomActivity(name=next(_status_cycle)))


def is_printable_attachment(attachment):
    if attachment.content_type and attachment.content_type.split(";")[0] in IMAGE_CONTENT_TYPES:
        return True
    filename = (attachment.filename or "").lower()
    return filename.endswith(IMAGE_EXTENSIONS)


async def post_file_to_printer(session, filename, data):
    form = aiohttp.FormData()
    form.add_field("darkness", str(DEFAULT_DARKNESS))
    form.add_field("file", data, filename=filename)
    async with session.post(f"{PRINT_SERVER_URL}/print/file", data=form) as resp:
        payload = await resp.json(content_type=None)
        if resp.status == 200:
            return True, payload.get("output", "")
        return False, payload.get("error", f"HTTP {resp.status}")


async def post_text_to_printer(session, text):
    body = {
        "text": text,
        "darkness": DEFAULT_DARKNESS,
        "text_columns": DEFAULT_TEXT_COLUMNS,
    }
    async with session.post(f"{PRINT_SERVER_URL}/print/text", json=body) as resp:
        payload = await resp.json(content_type=None)
        if resp.status == 200:
            return True, payload.get("output", "")
        return False, payload.get("error", f"HTTP {resp.status}")


@client.event
async def on_ready():
    log.info("Logged in as %s, watching channel %s", client.user, CHANNEL_ID)
    if not rotate_status.is_running():
        rotate_status.start()


@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if ALLOWED_USER_IDS and message.author.id not in ALLOWED_USER_IDS:
        log.info("Ignoring message from non-allowlisted user %s", message.author.id)
        return

    printable_attachments = [a for a in message.attachments if is_printable_attachment(a)]

    if not printable_attachments and not message.content.strip():
        return

    rotate_status.stop()
    await client.change_presence(activity=discord.CustomActivity(name="printing now \U0001F5A8"))
    try:
        async with aiohttp.ClientSession() as session:
            if printable_attachments:
                for attachment in printable_attachments:
                    try:
                        data = await attachment.read()
                        ok, detail = await post_file_to_printer(session, attachment.filename, data)
                    except Exception as exc:  # noqa: BLE001
                        ok, detail = False, str(exc)
                    await react_and_log(message, ok, detail)
            elif message.content.strip():
                try:
                    ok, detail = await post_text_to_printer(session, message.content.strip())
                except Exception as exc:  # noqa: BLE001
                    ok, detail = False, str(exc)
                await react_and_log(message, ok, detail)
    finally:
        rotate_status.start()


async def react_and_log(message, ok, detail):
    emoji = "\U0001F5A8" if ok else "\u26A0"  # printer / warning
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass
    if ok:
        log.info("Printed message %s from %s", message.id, message.author)
    else:
        log.error("Print failed for message %s: %s", message.id, detail)


def main():
    client.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
