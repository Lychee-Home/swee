import logging

import discord
from discord import app_commands

from swee.bot import bot, is_admin
from swee.config import PALWORLD_SETTINGS_INI_PATH
from swee.palworld_settings import REDACTED_SETTINGS_KEYS, parse_palworld_settings, visible_settings

log = logging.getLogger("swee")

PAGE_SIZE = 20

config_group = app_commands.Group(name="config", description="View and edit Palworld server settings")


async def _key_autocomplete(interaction: discord.Interaction, current: str):
    try:
        keys = visible_settings(PALWORLD_SETTINGS_INI_PATH).keys()
    except Exception:
        log.exception("config autocomplete: failed to read server settings")
        return []
    matches = [k for k in keys if current.lower() in k.lower()]
    return [app_commands.Choice(name=k, value=k) for k in matches[:25]]


@config_group.command(name="get", description="Show a single Palworld server setting")
@app_commands.describe(key="Setting name")
@app_commands.autocomplete(key=_key_autocomplete)
@is_admin()
async def config_get(interaction: discord.Interaction, key: str):
    if key in REDACTED_SETTINGS_KEYS:
        await interaction.response.send_message(
            f"`{key}` can only be edited directly on the server.", ephemeral=True
        )
        return
    try:
        settings = parse_palworld_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config get: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    if key not in settings:
        await interaction.response.send_message(f"No such setting: `{key}`", ephemeral=True)
        return
    await interaction.response.send_message(f"`{key}` = `{settings[key]}`", ephemeral=True)


bot.tree.add_command(config_group)
