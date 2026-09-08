from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


@dataclass
class Voter:
    """Represents one participant in a legislative roll call."""

    member: discord.Member
    vote: str = "NV"


class LegislativeVote:
    """
    Represents one active legislative vote.

    This first version keeps vote information in memory.
    SQLite persistence will be added later.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        measure: str,
        title: str,
        duration_minutes: int,
        voters: list[discord.Member],
    ) -> None:
        self.guild = interaction.guild
        self.channel = interaction.channel

        self.measure = measure
        self.title = title
        self.duration_minutes = duration_minutes

        self.opened_at = datetime.now(timezone.utc)
        self.closes_at = (
            self.opened_at
            + timedelta(minutes=duration_minutes)
        )

        self.voters: dict[int, Voter] = {
            member.id: Voter(member=member)
            for member in voters
        }

        self.message: Optional[discord.Message] = None
        self.closed = False

    @property
    def yea_count(self) -> int:
        return sum(
            voter.vote == "Yea"
            for voter in self.voters.values()
        )

    @property
    def nay_count(self) -> int:
        return sum(
            voter.vote == "Nay"
            for voter in self.voters.values()
        )

    @property
    def pres_count(self) -> int:
        return sum(
            voter.vote == "Pres"
            for voter in self.voters.values()
        )

    @property
    def nv_count(self) -> int:
        return sum(
            voter.vote == "NV"
            for voter in self.voters.values()
        )

    def set_vote(self, member_id: int, vote: str) -> bool:
        """Set or change a member's vote."""
        if self.closed:
            return False

        if member_id not in self.voters:
            return False

        if vote not in {"Yea", "Nay", "Pres"}:
            return False

        self.voters[member_id].vote = vote
        return True

    def build_embed(self) -> discord.Embed:
        """Create the current roll-call embed."""

        status = "CLOSED" if self.closed else "OPEN"

        description = (
            f"**{self.measure}—{self.title}**\n\n"
            f"Voting period: **{self.duration_minutes} minutes**\n"
            f"Status: **{status}**\n\n"
            f"**Yea:** {self.yea_count}\n"
            f"**Nay:** {self.nay_count}\n"
            f"**Pres:** {self.pres_count}\n"
            f"**NV:** {self.nv_count}\n"
        )

        if not self.closed:
            timestamp = int(self.closes_at.timestamp())

            description += (
                f"\nVoting closes <t:{timestamp}:R>."
            )
        else:
            description += (
                f"\nVoting closed "
                f"<t:{int(self.closes_at.timestamp())}:F>."
            )

        embed = discord.Embed(
            title="LEGISLATIVE ROLL CALL",
            description=description,
        )

        embed.set_footer(
            text="Yea • Nay • Pres • NV"
        )

        return embed

    def build_final_embed(self) -> discord.Embed:
        """Create the final roll-call record."""

        description = (
            f"**{self.measure}—{self.title}**\n\n"
            f"**FINAL ROLL CALL**\n\n"
            f"Yea: **{self.yea_count}**\n"
            f"Nay: **{self.nay_count}**\n"
            f"Pres: **{self.pres_count}**\n"
            f"NV: **{self.nv_count}**\n"
        )

        embed = discord.Embed(
            title="LEGISLATIVE VOTE CLOSED",
            description=description,
        )

        opened = int(self.opened_at.timestamp())
        closed = int(self.closes_at.timestamp())

        embed.add_field(
            name="Opened",
            value=f"<t:{opened}:F>",
            inline=True,
        )

        embed.add_field(
            name="Closed",
            value=f"<t:{closed}:F>",
            inline=True,
        )

        embed.set_footer(
            text="Final roll call"
        )

        return embed

    def build_roster(self) -> str:
        """Create a readable individual voting roster."""

        if not self.voters:
            return "No eligible voters."

        lines = []

        sorted_voters = sorted(
            self.voters.values(),
            key=lambda voter: voter.member.display_name.lower(),
        )

        for voter in sorted_voters:
            lines.append(
                f"{voter.member.mention} — **{voter.vote}**"
            )

        return "\n".join(lines)


class VoteButton(discord.ui.Button):
    """Button used to cast a vote."""

    def __init__(
        self,
        vote: LegislativeVote,
        vote_type: str,
        label: str,
    ) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            custom_id=f"legisvote:{vote_type.lower()}",
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

        if interaction.user.id not in self.vote.voters:
            await interaction.response.send_message(
                "You are not an eligible voter in this roll call.",
                ephemeral=True,
            )
            return

        self.vote.set_vote(
            interaction.user.id,
            self.vote_type,
        )

        await interaction.response.defer()

        if self.vote.message is not None:
            await self.vote.message.edit(
                embed=self.vote.build_embed(),
                view=self.view,
            )


class VoteView(discord.ui.View):
    """Interactive voting controls."""

    def __init__(self, vote: LegislativeVote) -> None:
        super().__init__(timeout=None)

        self.vote = vote

        self.add_item(
            VoteButton(vote, "Yea", "YEA")
        )

        self.add_item(
            VoteButton(vote, "Nay", "NAY")
        )

        self.add_item(
            VoteButton(vote, "Pres", "PRES")
        )

    def disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


async def get_eligible_members(
    interaction: discord.Interaction,
    role: Optional[discord.Role],
) -> list[discord.Member]:
    """
    Determine the electorate.

    Default:
        Members who can view and interact in the current channel.

    With role:
        Members who satisfy the channel eligibility requirement
        AND possess the supplied role.

    Bot accounts are excluded.
    """

    guild = interaction.guild
    channel = interaction.channel

    if guild is None or channel is None:
        return []

    eligible: list[discord.Member] = []

    # Fetch members rather than depending exclusively on cache.
    members = [
        member
        async for member in guild.fetch_members(limit=None)
    ]

    for member in members:
        if member.bot:
            continue

        permissions = channel.permissions_for(member)

        # For our purposes, an eligible participant must be able
        # to see the channel and send/interact in it.
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
    """Wait for the duration of the vote, then close it."""

    await asyncio.sleep(
        vote.duration_minutes * 60
    )

    if vote.closed:
        return

    vote.closed = True
    view.disable_buttons()

    if vote.message is None:
        return

    # Update the original message to show it is closed.
    await vote.message.edit(
        embed=vote.build_final_embed(),
        view=view,
    )

    # Post the individual roll call beneath it.
    await vote.channel.send(
        content=(
            "**FINAL ROLL CALL**\n\n"
            f"{vote.build_roster()}"
        )
    )


async def register(
    bot: commands.Bot,
) -> None:
    """
    Register the /legisvote command on the supplied bot.
    """

    @bot.tree.command(
        name="legisvote",
        description="Open an electronic legislative roll-call vote.",
    )
    @app_commands.describe(
        measure="The legislative measure, e.g. S. 5",
        title="The title of the measure",
        duration="Voting duration in minutes; defaults to 15",
        role="Optional role restricting who may vote",
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

        legislative_role = interaction.guild.get_role(
            bot.config.LEGISLATIVE_ROLE_ID
            if hasattr(bot, "config")
            else 0
        )

        if legislative_role is None:
            await interaction.response.send_message(
                "The configured Legislative role could not be found.",
                ephemeral=True,
            )
            return

        creator = interaction.user

        if not isinstance(creator, discord.Member):
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
        # Duration validation
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
        # Determine electorate
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
        # Create vote
        # ---------------------------------------------------------

        vote = LegislativeVote(
            interaction=interaction,
            measure=measure,
            title=title,
            duration_minutes=duration,
            voters=voters,
        )

        view = VoteView(vote)

        await interaction.response.send_message(
            embed=vote.build_embed(),
            view=view,
        )

        vote.message = await interaction.original_response()

        # Launch the closing timer without blocking Discord.
        asyncio.create_task(
            close_vote(vote, view)
        )