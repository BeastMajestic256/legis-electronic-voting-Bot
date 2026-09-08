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


def format_table(
    rows: list[tuple[str, str]],
    header_1: str,
    header_2: str,
) -> str:
    """Create a simple monospace table."""

    first_lengths = [
        len(header_1),
        *(
            len(row[0])
            for row in rows
        ),
    ]

    second_lengths = [
        len(header_2),
        *(
            len(row[1])
            for row in rows
        ),
    ]

    first_width = max(first_lengths)
    second_width = max(second_lengths)

    separator = (
        f"+-{'-' * first_width}"
        f"-+-{'-' * second_width}-+"
    )

    lines = [
        separator,
        (
            f"| {header_1:<{first_width}} "
            f"| {header_2:<{second_width}} |"
        ),
        separator,
    ]

    for first, second in rows:
        lines.append(
            f"| {first:<{first_width}} "
            f"| {second:<{second_width}} |"
        )

    lines.append(separator)

    return "\n".join(lines)


class LegislativeVote:

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
        creator_id: int,
        role_id: Optional[int],
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

        self.creator_id = creator_id
        self.role_id = role_id

        self.voters = {
            member.id: member
            for member in voters
        }

        self.message: Optional[discord.Message] = None
        self.closed = False

    def get_vote(
        self,
        member_id: int,
    ) -> str:

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

    def count(
        self,
        vote_type: str,
    ) -> int:

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

    def build_summary_table(self) -> str:

        rows = [
            ("Yea", str(self.yea_count)),
            ("Nay", str(self.nay_count)),
            ("Pres", str(self.pres_count)),
            ("NV", str(self.nv_count)),
        ]

        return format_table(
            rows,
            "Status",
            "Count",
        )

    def build_roster_table(self) -> str:

        rows = []

        sorted_members = sorted(
            self.voters.values(),
            key=lambda member:
                member.display_name.lower(),
        )

        for member in sorted_members:
            rows.append(
                (
                    member.display_name,
                    self.get_vote(member.id),
                )
            )

        if not rows:
            rows.append(
                ("None", "—")
            )

        return format_table(
            rows,
            "Member",
            "Vote",
        )

    def build_embed(
        self,
        final: bool = False,
    ) -> discord.Embed:

        status = "CLOSED" if self.closed else "OPEN"

        opened_timestamp = int(
            self.opened_at.timestamp()
        )

        closed_timestamp = int(
            self.closes_at.timestamp()
        )

        description = (
            f"**{self.measure}—{self.title}**\n\n"
            f"Status: **{status}**\n\n"
            f"### Vote Summary\n"
            f"```text\n"
            f"{self.build_summary_table()}\n"
            f"```\n"
            f"### Roll Call\n"
            f"```text\n"
            f"{self.build_roster_table()}\n"
            f"```\n"
        )

        description += (
            f"\nOpened: <t:{opened_timestamp}:F>\n"
        )

        if final:
            description += (
                f"Closed: <t:{closed_timestamp}:F>\n"
            )
        else:
            description += (
                f"Closes: <t:{closed_timestamp}:R>\n"
            )

        electorate = (
            f"<@&{self.role_id}>"
            if self.role_id is not None
            else "Channel-eligible Members"
        )

        description += (
            f"Electorate: {electorate}\n"
            f"Vote ID: **{self.vote_id}**"
        )

        embed = discord.Embed(
            title=(
                "LEGISLATIVE VOTE CLOSED"
                if final
                else "LEGISLATIVE ROLL CALL"
            ),
            description=description,
        )

        embed.set_footer(
            text=(
                "Final roll call"
                if final
                else "Yea • Nay • Pres • NV"
            )
        )

        return embed


class VoteButton(discord.ui.Button):

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

        old_vote = self.vote.get_vote(
            member_id
        )

        if old_vote == self.vote_type:
            await interaction.response.send_message(
                f"Your vote is already recorded as "
                f"**{self.vote_type}**.",
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
            f"{interaction.user} | "
            f"{old_vote} -> {self.vote_type}"
        )


class VoteView(discord.ui.View):

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
        embed=vote.build_embed(final=True),
        view=view,
    )


async def register(
    bot: commands.Bot,
    database: Database,
) -> None:

    legis_group = app_commands.Group(
        name="legisvote",
        description="Electronic legislative roll-call system.",
    )

    @legis_group.command(
        name="open",
        description="Open an electronic legislative roll-call vote.",
    )
    @app_commands.describe(
        measure="The legislative measure, e.g. S. 5",
        title="The title of the measure",
        duration="Voting duration in minutes; defaults to 15",
        role="Optional role restricting who may vote",
    )
    async def legisvote_open(
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

        opened_at = datetime.now(
            timezone.utc
        )

        closes_at = (
            opened_at
            + timedelta(minutes=duration)
        )

        vote_id = database.create_vote(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            creator_id=creator.id,
            role_id=(
                role.id
                if role is not None
                else None
            ),
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
            creator_id=creator.id,
            role_id=(
                role.id
                if role is not None
                else None
            ),
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

    @legis_group.command(
        name="status",
        description="Show currently active legislative votes.",
    )
    async def legisvote_status(
        interaction: discord.Interaction,
    ) -> None:

        votes = database.get_open_votes()

        if not votes:
            await interaction.response.send_message(
                "There are currently no open legislative votes.",
                ephemeral=True,
            )
            return

        lines = []

        for row in votes:
            closes_at = datetime.fromisoformat(
                row["closes_at"]
            )

            lines.append(
                f"**Vote {row['id']}** — "
                f"{row['measure']}—{row['title']}\n"
                f"Closes <t:{int(closes_at.timestamp())}:R>"
            )

        embed = discord.Embed(
            title="ACTIVE LEGISLATIVE VOTES",
            description="\n\n".join(lines),
        )

        await interaction.response.send_message(
            embed=embed
        )

    @legis_group.command(
        name="history",
        description="Show recent legislative votes.",
    )
    @app_commands.describe(
        limit="Number of records to display; defaults to 10",
    )
    async def legisvote_history(
        interaction: discord.Interaction,
        limit: int = 10,
    ) -> None:

        limit = max(
            1,
            min(limit, 25)
        )

        votes = database.get_recent_votes(
            limit
        )

        if not votes:
            await interaction.response.send_message(
                "No legislative votes have been recorded.",
                ephemeral=True,
            )
            return

        rows = []

        for row in votes:
            status = (
                "OPEN"
                if not row["closed"]
                else "CLOSED"
            )

            rows.append(
                (
                    f"#{row['id']} {row['measure']}",
                    status,
                )
            )

        table = format_table(
            rows,
            "Vote",
            "Status",
        )

        await interaction.response.send_message(
            content=(
                "### LEGISLATIVE VOTE HISTORY\n"
                "```text\n"
                f"{table}\n"
                "```"
            )
        )

    @legis_group.command(
        name="record",
        description="Show the official record of a legislative vote.",
    )
    @app_commands.describe(
        vote_id="The ID of the vote to display",
    )
    async def legisvote_record(
        interaction: discord.Interaction,
        vote_id: int,
    ) -> None:

        row = database.get_vote(
            vote_id
        )

        if row is None:
            await interaction.response.send_message(
                f"Vote {vote_id} does not exist.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        voter_rows = database.get_voters(
            vote_id
        )

        roll_call_rows = []

        for voter_row in voter_rows:
            member_id = voter_row["member_id"]

            member = (
                interaction.guild.get_member(
                    member_id
                )
            )

            if member is None:
                try:
                    member = (
                        await interaction.guild.fetch_member(
                            member_id
                        )
                    )
                except discord.NotFound:
                    name = f"User {member_id}"
                else:
                    name = member.display_name
            else:
                name = member.display_name

            roll_call_rows.append(
                (
                    name,
                    voter_row["vote"],
                )
            )

        roll_call_rows.sort(
            key=lambda item:
                item[0].lower()
        )

        summary_counts = {
            "Yea": 0,
            "Nay": 0,
            "Pres": 0,
            "NV": 0,
        }

        for _, vote in roll_call_rows:
            if vote in summary_counts:
                summary_counts[vote] += 1

        summary_table = format_table(
            [
                ("Yea", str(summary_counts["Yea"])),
                ("Nay", str(summary_counts["Nay"])),
                ("Pres", str(summary_counts["Pres"])),
                ("NV", str(summary_counts["NV"])),
            ],
            "Status",
            "Count",
        )

        roll_call = format_table(
            roll_call_rows,
            "Member",
            "Vote",
        )

        opened_at = datetime.fromisoformat(
            row["opened_at"]
        )

        closes_at = datetime.fromisoformat(
            row["closes_at"]
        )

        status = (
            "OPEN"
            if not row["closed"]
            else "CLOSED"
        )

        electorate = (
            f"<@&{row['role_id']}>"
            if row["role_id"] is not None
            else "Channel-eligible Members"
        )

        description = (
            f"**{row['measure']}—{row['title']}**\n\n"
            f"Status: **{status}**\n"
            f"Creator: <@{row['creator_id']}>\n"
            f"Electorate: {electorate}\n"
            f"Opened: <t:{int(opened_at.timestamp())}:F>\n"
            f"Closes: <t:{int(closes_at.timestamp())}:F>\n\n"
            f"### Vote Summary\n"
            f"```text\n"
            f"{summary_table}\n"
            f"```\n"
            f"### Roll Call\n"
            f"```text\n"
            f"{roll_call}\n"
            f"```"
        )

        embed = discord.Embed(
            title=f"LEGISLATIVE VOTE RECORD #{vote_id}",
            description=description,
        )

        await interaction.response.send_message(
            embed=embed
        )

    bot.tree.add_command(
        legis_group
    )