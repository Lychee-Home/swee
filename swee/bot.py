import discord
from discord import app_commands
from discord.ext import commands

from swee.config import ADMIN_CHANNEL_ID, ADMIN_ROLE_ID, COMMANDS_CHANNEL_ID

intents = discord.Intents.default()
intents.message_content = True  # must also be enabled in the Discord Developer Portal

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Admin commands can only be used in the server.", ephemeral=True)
            return False
        if interaction.channel_id != ADMIN_CHANNEL_ID:
            await interaction.response.send_message(f"Admin commands can only be used in <#{ADMIN_CHANNEL_ID}>.", ephemeral=True)
            return False
        role = discord.utils.get(interaction.user.roles, id=ADMIN_ROLE_ID)
        if role is None:
            await interaction.response.send_message("Admin role required.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def in_commands_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != COMMANDS_CHANNEL_ID:
            await interaction.response.send_message(f"This command can only be used in <#{COMMANDS_CHANNEL_ID}>.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)
