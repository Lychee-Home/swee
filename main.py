import asyncio
import logging

import discord

import swee.commands  # noqa: F401 — registers slash commands via decorator side effects
import swee.config_commands  # noqa: F401 — registers slash commands via decorator side effects
from swee.bot import bot
from swee.cause_detection import load_last_palworld_settings
from swee.config import BOT_TOKEN, GITHUB_REPO, GUILD_ID, RELAY_CHANNEL_ID
from swee.log_tailer import log_tailer
from swee.player_history import load_player_history
from swee.releases import load_last_release, release_ticker
from swee.rest_client import rest
from swee.restart import check_palworld_service
from swee.stats import stats_ticker

log = logging.getLogger("swee")

_log_tailer_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run


# ---------- Discord -> game ----------
@bot.event
async def on_message(message):
    if RELAY_CHANNEL_ID is None or message.author.bot or message.channel.id != RELAY_CHANNEL_ID:
        return
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    try:
        await rest.announce(f"{message.author.display_name}: {message.content}")
    except Exception:
        log.exception("announce failed")


@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    global _log_tailer_task
    _log_tailer_task = asyncio.create_task(log_tailer())
    stats_ticker.start()
    if GITHUB_REPO:
        release_ticker.start()
    log.info("Logged in as %s", bot.user)


async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    load_player_history()
    load_last_release()
    load_last_palworld_settings()
    async with bot:
        await bot.start(BOT_TOKEN)
        # bot.start() returns once the bot is closed (e.g. Ctrl+C) — clean up
        # the background task and REST client rather than leaving them dangling.
        stats_ticker.cancel()
        release_ticker.cancel()
        if _log_tailer_task:
            _log_tailer_task.cancel()
        await rest.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
