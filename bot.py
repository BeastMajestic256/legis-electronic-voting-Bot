import discord
from discord.ext import commands

import config
import voting


class LegislativeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()

        # Required for discovering server members and roles.
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

        # Make configuration available to command modules.
        self.config = config

    async def setup_hook(self) -> None:
        await voting.register(self)

        # Synchronize slash commands with Discord.
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(
            f"Logged in as {self.user} "
            f"(ID: {self.user.id})"
        )
        print("Legislative voting bot is online.")


bot = LegislativeBot()

bot.run(config.DISCORD_TOKEN)