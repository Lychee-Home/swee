import logging

import discord
from discord import app_commands

from swee.bot import bot, is_admin
from swee.config import PALWORLD_SETTINGS_INI_PATH
from swee.palworld_settings import (
    REDACTED_SETTINGS_KEYS,
    format_new_value,
    parse_palworld_settings,
    visible_settings,
    write_palworld_setting,
)

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


class ConfigListView(discord.ui.View):
    def __init__(self, user_id, entries, page):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.entries = entries
        self.page = page
        self.last_page = (len(entries) - 1) // PAGE_SIZE
        self.message = None
        self._update_buttons()

    def _update_buttons(self):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.last_page

    def embed(self):
        start = self.page * PAGE_SIZE
        embed = discord.Embed(title=f"Palworld settings (page {self.page + 1}/{self.last_page + 1})")
        for key, value in self.entries[start:start + PAGE_SIZE]:
            embed.add_field(name=key, value=value, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran this command can page through it.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        self.previous_button.disabled = True
        self.next_button.disabled = True
        if self.message is not None:
            await self.message.edit(view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


@config_group.command(name="list", description="List Palworld server settings")
@app_commands.describe(page="Page number (starts at 1)")
@is_admin()
async def config_list(interaction: discord.Interaction, page: int = 1):
    try:
        settings = visible_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config list: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    entries = sorted(settings.items())
    last_page = (len(entries) - 1) // PAGE_SIZE
    zero_page = max(0, min(page - 1, last_page))
    view = ConfigListView(interaction.user.id, entries, zero_page)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()


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


@config_group.command(name="set", description="Change a Palworld server setting (requires /restart to apply)")
@app_commands.describe(key="Setting name", value="New value")
@app_commands.autocomplete(key=_key_autocomplete)
@is_admin()
async def config_set(interaction: discord.Interaction, key: str, value: str):
    if key in REDACTED_SETTINGS_KEYS:
        await interaction.response.send_message(
            f"`{key}` can only be edited directly on the server.", ephemeral=True
        )
        return
    try:
        settings = parse_palworld_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config set: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    if key not in settings:
        await interaction.response.send_message(f"No such setting: `{key}`", ephemeral=True)
        return
    try:
        formatted = format_new_value(settings[key], value)
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return
    try:
        write_palworld_setting(PALWORLD_SETTINGS_INI_PATH, key, formatted)
    except Exception:
        log.exception("/config set: failed to write server settings")
        await interaction.response.send_message("Couldn't write server settings.", ephemeral=True)
        return
    await interaction.response.send_message(f"`{key}` set to `{formatted}`. Run `/restart` to apply.")


bot.tree.add_command(config_group)
