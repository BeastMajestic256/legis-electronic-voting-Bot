import discord
from discord.ext import commands

from config import DISCORD_TOKEN


class LegislativeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()

        # Required for identifying server members and their roles.
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

    async def setup_hook(self) -> None:
        # Synchronize slash commands with Discord.
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Legislative voting bot is online.")


bot = LegislativeBot()


@bot.tree.command(
    name="ping",
    description="Check whether the legislative voting bot is online.",
)
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Pong!")


bot.run(DISCORD_TOKEN)