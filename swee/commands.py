import logging

import discord
from discord import app_commands

import swee.restart as restart_module
from swee.bot import bot, in_commands_channel, is_admin
from swee.config import COLOR_CHAT, COLOR_SHUTDOWN, OFFLINE_PLAYERS_LIMIT
from swee.embeds import add_status_fields, format_offline_field, format_online_field, offline_entries_from_history
from swee.player_history import online_players, player_history, refresh_online_players, session_started
from swee.rest_client import rest
from swee.restart import restart_palworld

log = logging.getLogger("swee")


@bot.tree.command(description="Show server status")
@in_commands_channel()
async def status(interaction: discord.Interaction):
    info, metrics = await rest.info(), await rest.metrics()
    try:
        players_list = (await rest.players()).get("players", [])
        refresh_online_players(players_list)
    except Exception:
        log.exception("player history: failed to fetch players for /status")
        players_list = []
    offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
    embed = discord.Embed(title=info["servername"], color=COLOR_CHAT)
    add_status_fields(embed, info, metrics, players_list, offline_entries)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description="List online and offline players")
@in_commands_channel()
async def players(interaction: discord.Interaction):
    plist = (await rest.players()).get("players", [])
    refresh_online_players(plist)
    offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
    embed = discord.Embed(title="Players", color=COLOR_CHAT)
    embed.add_field(name="Online", value=format_online_field(plist, session_started), inline=False)
    embed.add_field(name="Offline", value=format_offline_field(offline_entries, OFFLINE_PLAYERS_LIMIT), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Force-save the world")
@is_admin()
async def save(interaction: discord.Interaction):
    await rest.save()
    await interaction.response.send_message("World saved.")


@bot.tree.command(description="Kick a player by SteamID")
@is_admin()
async def kick(interaction: discord.Interaction, steamid: str, reason: str = ""):
    await rest.kick(steamid, reason)
    await interaction.response.send_message(f"Kicked `{steamid}`.")


@bot.tree.command(description="Ban a player by SteamID")
@is_admin()
async def ban(interaction: discord.Interaction, steamid: str, reason: str = ""):
    await rest.ban(steamid, reason)
    await interaction.response.send_message(f"Banned `{steamid}`.")


@bot.tree.command(description="Send an in-game announcement")
@is_admin()
async def broadcast(interaction: discord.Interaction, message: str):
    await rest.announce(message)
    await interaction.response.send_message("Sent.")


@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Restarting Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Sending restart command…")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    restart_module._bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        restart_module._bot_restart_in_progress = False
    await interaction.edit_original_response(embed=result_embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        return  # predicate (is_admin/in_commands_channel) already sent its own response

    command_name = interaction.command.name if interaction.command else "?"
    log.exception("command error in /%s", command_name, exc_info=error)

    message = "Something went wrong talking to the server."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
