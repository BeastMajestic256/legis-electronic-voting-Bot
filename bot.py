import discord
from discord.ext import commands

import config
import voting

from database import Database


class LegislativeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()

        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

        self.config = config
        self.database = Database()

        self.voting_system = None
        self.recovered = False

    async def setup_hook(self) -> None:

        self.voting_system = await voting.register(
            self,
            self.database,
        )

        await self.tree.sync()

    async def on_ready(self) -> None:

        print(
            f"Logged in as {self.user} "
            f"(ID: {self.user.id})"
        )

        print(
            "Legislative voting bot is online."
        )

        if not self.recovered:

            await self.voting_system.load_active_votes()

            self.recovered = True


bot = LegislativeBot()

bot.run(config.DISCORD_TOKEN)