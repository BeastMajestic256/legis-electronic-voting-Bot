import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")


class LegislativeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()

        # Required later so the bot can identify eligible
        # Legislative Members by their server roles.
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

    async def setup_hook(self) -> None:
        await self.tree.sync()


bot = LegislativeBot()


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Legislative voting bot is online.")


@bot.tree.command(
    name="ping",
    description="Check whether the legislative voting bot is online."
)
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Pong!")


bot.run(TOKEN)