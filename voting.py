from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import Database


VALID_VOTES = {
    "Yea",
    "Nay",
    "Pres",
}


class LegislativeVote:
    """Represents a persistent legislative roll-call vote."""

    def __init__(
        self,
        database: Database,
        vote_id: int,
        interaction: discord.Interaction,
        measure: str,
        title: str,
        duration_minutes: int,
        voters: list[discord.Member],
        opened_at: datetime,
        closes_at: datetime,
    ) -> None:

        self.database = database

        self.vote_id = vote_id

        self.guild = interaction.guild
        self.channel = interaction.channel

        self.measure = measure
        self.title = title
        self.duration_minutes = duration_minutes

        self.opened_at = opened_at
        self.closes_at = closes_at

        self.voters: dict[int, discord.Member] = {
            member.id: member
            for member in voters
        }

        self.message: Optional[discord.Message] = None
        self.closed = False

    def get_vote(self, member_id: int) -> str:
        """Get the member's current recorded vote."""

        vote = self.database.get_voter_vote(
            self.vote_id,
            member_id,
        )

        return vote or "NV"

    def set_vote(
        self,
        member_id: int,
        vote: str,
    ) -> bool:
        """Change a member's recorded vote."""

        if self.closed:
            return False

        if member_id not in self.voters:
            return False

        if vote not in VALID_VOTES:
            return False

        self.database.set_voter_vote(
            self.vote_id,
            member_id,
            vote,
        )

        return True

    def count(self, vote_type: str) -> int:
        return sum(
            self.get_vote(member_id) == vote_type
            for member_id in self.voters
        )

    @property
    def yea_count(self) -> int:
        return self.count("Yea")

    @property
    def nay_count(self) -> int:
        return self.count("Nay")

    @property
    def pres_count(self) -> int:
        return self.count("Pres")

    @property
    def nv_count(self) -> int:
        return self.count("NV")

    def build_roster(self) -> str:
        """Build the individual roll-call roster."""

        if not self.voters:
            return "No eligible voters."

        groups = {
            "YEA": [],
            "NAY": [],
            "PRES": [],
            "NV": [],
        }

        for member in sorted(
            self.voters.values(),
            key=lambda item: item.display_name.lower(),
        ):
            vote = self.get_vote(member.id)

            groups[vote.upper()].append(
                member.mention
            )

        lines = []

        for label in (
            "YEA",
            "NAY",
            "PRES",
            "NV",
        ):
            lines.append(
                f"**{label}**"
            )

            if groups[label]:
                lines.extend(
                    f"{mention}"
                    for mention in groups[label]
                )
            else:
                lines.append(
                    "None"
                )

            lines.append("")

        return "\n".join(lines).strip()

    def build_embed(self) -> discord.Embed:
        """Build the active vote message."""

        timestamp = int(
            self.closes_at.timestamp()
        )

        description = (
            f"**{self.measure}—{self.title}**\n\n"
            f"Voting period: **{self.duration_minutes} minutes**\n"
            f"Status: **{'CLOSED' if self.closed else 'OPEN'}**\n\n"
            f"**Yea:** {self.yea_count}\n"
            f"**Nay:** {self.nay_count}\n"
            f"**Pres:** {self.pres_count}\n"
            f"**NV:** {self.nv_count}\n"
        )

        if not self.closed:
            description += (
                f"\nVoting closes <t:{timestamp}:R>."
            )
        else:
            description += (
                f"\nVoting closed <t:{timestamp}:F>."
            )

        description += (
            "\n\n"
            "### Current Roll Call\n\n"
            f"{self.build_roster()}"
        )

        embed = discord.Embed(
            title="LEGISLATIVE ROLL CALL",
            description=description,
        )

        embed.set_footer(
            text=f"Vote ID: {self.vote_id}"
        )

        return embed


class VoteButton(discord.ui.Button):
    """Interactive button for a legislative vote."""

    def __init__(
        self,
        vote: LegislativeVote,
        vote_type: str,
        label: str,
    ) -> None:

        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"legisvote:"
                f"{vote.vote_id}:"
                f"{vote_type.lower()}"
            ),
        )

        self.vote = vote
        self.vote_type = vote_type

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if self.vote.closed:
            await interaction.response.send_message(
                "This vote is already closed.",
                ephemeral=True,
            )
            return

        member_id = interaction.user.id

        if member_id not in self.vote.voters:
            await interaction.response.send_message(
                "You are not an eligible voter in this roll call.",
                ephemeral=True,
            )
            return

        changed = self.vote.set_vote(
            member_id,
            self.vote_type,
        )

        if not changed:
            await interaction.response.send_message(
                "Your vote could not be recorded.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if self.vote.message is not None:
            await self.vote.message.edit(
                embed=self.vote.build_embed(),
                view=self.view,
            )

        print(
            f"[Vote {self.vote.vote_id}] "
            f"{interaction.user} → {self.vote_type}"
        )


class VoteView(discord.ui.View):
    """Interactive controls for a legislative vote."""

    def __init__(
        self,
        vote: LegislativeVote,
    ) -> None:

        super().__init__(
            timeout=None
        )

        self.vote = vote

        self.add_item(
            VoteButton(
                vote,
                "Yea",
                "YEA",
            )
        )

        self.add_item(
            VoteButton(
                vote,
                "Nay",
                "NAY",
            )
        )

        self.add_item(
            VoteButton(
                vote,
                "Pres",
                "PRES",
            )
        )

    def disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(
                item,
                discord.ui.Button,
            ):
                item.disabled = True


async def get_eligible_members(
    interaction: discord.Interaction,
    role: Optional[discord.Role],
) -> list[discord.Member]:

    guild = interaction.guild
    channel = interaction.channel

    if guild is None or channel is None:
        return []

    members = [
        member
        async for member in guild.fetch_members(
            limit=None
        )
    ]

    eligible = []

    for member in members:

        if member.bot:
            continue

        permissions = channel.permissions_for(
            member
        )

        if not permissions.view_channel:
            continue

        if not permissions.send_messages:
            continue

        if role is not None and role not in member.roles:
            continue

        eligible.append(member)

    return eligible


async def close_vote(
    vote: LegislativeVote,
    view: VoteView,
) -> None:

    await asyncio.sleep(
        max(
            0,
            (
                vote.closes_at
                - datetime.now(timezone.utc)
            ).total_seconds(),
        )
    )

    if vote.closed:
        return

    vote.closed = True

    vote.database.close_vote(
        vote.vote_id
    )

    view.disable_buttons()

    if vote.message is None:
        return

    await vote.message.edit(
        embed=vote.build_embed(),
        view=view,
    )


async def register(
    bot: commands.Bot,
    database: Database,
) -> None:

    @bot.tree.command(
        name="legisvote",
        description=(
            "Open an electronic legislative roll-call vote."
        ),
    )
    @app_commands.describe(
        measure=(
            "The legislative measure, e.g. S. 5"
        ),
        title=(
            "The title of the measure"
        ),
        duration=(
            "Voting duration in minutes; defaults to 15"
        ),
        role=(
            "Optional role restricting who may vote"
        ),
    )
    async def legisvote(
        interaction: discord.Interaction,
        measure: str,
        title: str,
        duration: int = 15,
        role: Optional[discord.Role] = None,
    ) -> None:

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------
        # Creator authorization
        # ---------------------------------------------------------

        legislative_role = (
            interaction.guild.get_role(
                bot.config.LEGISLATIVE_ROLE_ID
            )
        )

        if legislative_role is None:
            await interaction.response.send_message(
                "The configured Legislative role could not be found.",
                ephemeral=True,
            )
            return

        creator = interaction.user

        if not isinstance(
            creator,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Unable to determine your server membership.",
                ephemeral=True,
            )
            return

        if legislative_role not in creator.roles:
            await interaction.response.send_message(
                "Only Members of the Legislative may create "
                "a legislative vote.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------
        # Duration
        # ---------------------------------------------------------

        if duration < 1:
            await interaction.response.send_message(
                "The voting duration must be at least 1 minute.",
                ephemeral=True,
            )
            return

        if duration > 1440:
            await interaction.response.send_message(
                "The voting duration may not exceed 1440 minutes.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------
        # Electorate
        # ---------------------------------------------------------

        voters = await get_eligible_members(
            interaction,
            role,
        )

        if not voters:
            await interaction.response.send_message(
                "No eligible voters were found for this vote.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------
        # Times
        # ---------------------------------------------------------

        opened_at = datetime.now(
            timezone.utc
        )

        closes_at = (
            opened_at
            + timedelta(
                minutes=duration
            )
        )

        # ---------------------------------------------------------
        # Create persistent vote
        # ---------------------------------------------------------

        vote_id = database.create_vote(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            measure=measure,
            title=title,
            duration_minutes=duration,
            opened_at=opened_at,
            closes_at=closes_at,
        )

        for member in voters:
            database.add_voter(
                vote_id,
                member.id,
            )

        vote = LegislativeVote(
            database=database,
            vote_id=vote_id,
            interaction=interaction,
            measure=measure,
            title=title,
            duration_minutes=duration,
            voters=voters,
            opened_at=opened_at,
            closes_at=closes_at,
        )

        view = VoteView(vote)

        await interaction.response.send_message(
            embed=vote.build_embed(),
            view=view,
        )

        vote.message = (
            await interaction.original_response()
        )

        database.set_message_id(
            vote_id,
            vote.message.id,
        )

        asyncio.create_task(
            close_vote(
                vote,
                view,
            )
        )