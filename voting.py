from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import Database

import aiohttp

VALID_VOTES = {
    "Yea",
    "Nay",
    "Pres",
}

VALID_THRESHOLDS = {
    "majority",
    "plurality",
    "three_fifths",
    "two_thirds",
    "unanimity",
}


THRESHOLD_LABELS = {
    "majority": "Majority",
    "plurality": "Plurality",
    "three_fifths": "Three-Fifths",
    "two_thirds": "Two-Thirds",
    "unanimity": "Unanimity",
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


def evaluate_result(
    yea: int,
    nay: int,
    pres: int,
    nv: int,
    decisive: bool,
    threshold: str,
) -> Optional[str]:
    """
    Determine whether a decisive vote passes or fails.

    Yea and Nay are substantive votes.
    Pres and NV remain recorded but do not enter the
    substantive denominator.
    """

    if not decisive:
        return None

    if threshold not in VALID_THRESHOLDS:
        raise ValueError(
            f"Unknown threshold: {threshold}"
        )

    substantive_votes = yea + nay

    if threshold == "majority":

        return (
            "PASSED"
            if yea > nay
            else "FAILED"
        )

    if threshold == "plurality":

        if yea == nay:
            return "FAILED"

        return (
            "PASSED"
            if yea > nay
            else "FAILED"
        )

    if substantive_votes == 0:
        return "FAILED"

    if threshold == "three_fifths":

        return (
            "PASSED"
            if yea / substantive_votes >= 3 / 5
            else "FAILED"
        )

    if threshold == "two_thirds":

        return (
            "PASSED"
            if yea / substantive_votes >= 2 / 3
            else "FAILED"
        )

    if threshold == "unanimity":

        return (
            "PASSED"
            if yea > 0 and nay == 0
            else "FAILED"
        )

    return "FAILED"


class LegislativeVote:
    """Represents a legislative roll-call vote."""

    def __init__(
        self,
        database: Database,
        vote_id: int,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        message_id: int,
        measure: str,
        title: str,
        duration_minutes: int,
        voters: dict[int, discord.Member],
        opened_at: datetime,
        closes_at: datetime,
        creator_id: int,
        role_id: Optional[int],
        decisive: bool,
        threshold: str,
        closed: bool = False,
    ) -> None:

        self.database = database

        self.vote_id = vote_id

        self.guild = guild
        self.channel = channel
        self.message_id = message_id

        self.measure = measure
        self.title = title
        self.duration_minutes = duration_minutes

        self.voters = voters

        self.opened_at = opened_at
        self.closes_at = closes_at

        self.creator_id = creator_id
        self.role_id = role_id

        self.closed = closed

        self.message: Optional[discord.Message] = None

        self.decisive = decisive
        self.threshold = threshold

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
    def result(self) -> Optional[str]:
        return evaluate_result(
            yea=self.yea_count,
            nay=self.nay_count,
            pres=self.pres_count,
            nv=self.nv_count,
            decisive=self.decisive,
            threshold=self.threshold,
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
        return format_table(
            [
                ("Yea", str(self.yea_count)),
                ("Nay", str(self.nay_count)),
                ("Pres", str(self.pres_count)),
                ("NV", str(self.nv_count)),
            ],
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

        status = (
            "CLOSED"
            if self.closed
            else "OPEN"
        )

        vote_type = (
            "DECISIVE"
            if self.decisive
            else "NON-DECISIVE"
        )

        threshold = THRESHOLD_LABELS[
            self.threshold
        ]

        opened_timestamp = int(
            self.opened_at.timestamp()
        )

        closed_timestamp = int(
            self.closes_at.timestamp()
        )

        # ---------------------------------------------------------
        # Determine the current/final result.
        #
        # Decisive votes have a pass/fail result.
        # Non-decisive votes have no result.
        # ---------------------------------------------------------

        result = None
        result_text = None

        if self.closed and self.decisive:
            result = self.result
            result_text = result

        # ---------------------------------------------------------
        # Description
        # ---------------------------------------------------------

        description = (
            f"**{self.measure}—{self.title}**\n\n"
        )

        # ---------------------------------------------------------
        # Countdown while the vote is open.
        # This is deliberately prominent.
        # ---------------------------------------------------------

        if not self.closed:

            now = datetime.now(
                timezone.utc
            )

            remaining_seconds = max(
                0,
                int(
                    (
                        self.closes_at
                        - now
                    ).total_seconds()
                ),
            )

            minutes, seconds = divmod(
                remaining_seconds,
                60,
            )

            countdown = (
                f"{minutes:02d}:{seconds:02d}"
            )

            description += (
                f"**TIME REMAINING: {countdown}**\n\n"
            )

        # ---------------------------------------------------------
        # Basic vote information.
        # ---------------------------------------------------------

        description += (
            f"Status: **{status}**\n"
            f"Vote Type: **{vote_type}**\n"
            f"Threshold: **{threshold}**\n"
        )

        # ---------------------------------------------------------
        # Final result.
        #
        # Only decisive votes receive a pass/fail determination.
        # ---------------------------------------------------------

        if self.closed and self.decisive:
            description += (
                f"Result: **{result_text}**\n"
            )

        description += (
            f"\n"
            f"### Vote Summary\n"
            f"```text\n"
            f"{self.build_summary_table()}\n"
            f"```\n"
            f"### Roll Call\n"
            f"```text\n"
            f"{self.build_roster_table()}\n"
            f"```\n\n"
            f"Opened: <t:{opened_timestamp}:F>\n"
        )

        # ---------------------------------------------------------
        # Show the closing timestamp.
        # ---------------------------------------------------------

        if final:
            description += (
                f"Closed: <t:{closed_timestamp}:F>\n"
            )
        else:
            description += (
                f"Closes: <t:{closed_timestamp}:F>\n"
            )

        # ---------------------------------------------------------
        # Electorate.
        # ---------------------------------------------------------

        if self.role_id is not None:
            electorate = (
                f"<@&{self.role_id}>"
            )
        else:
            electorate = (
                "Channel-eligible Members"
            )

        description += (
            f"Electorate: {electorate}\n"
            f"Vote ID: **{self.vote_id}**"
        )

        # ---------------------------------------------------------
        # Create embed.
        # ---------------------------------------------------------

        embed = discord.Embed(
            title=(
                "LEGISLATIVE VOTE CLOSED"
                if final
                else "LEGISLATIVE ROLL CALL"
            ),
            description=description,
        )

        # ---------------------------------------------------------
        # Make the final result prominent.
        #
        # Non-decisive votes do not receive this field.
        # ---------------------------------------------------------

        if final and self.decisive:
            embed.add_field(
                name="RESULT",
                value=f"**{result}**",
                inline=False,
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
    """Persistent button used to cast a legislative vote."""

    def __init__(
        self,
        voting_system: "VotingSystem",
        vote_id: int,
        vote_type: str,
        label: str,
    ) -> None:

        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"legisvote:"
                f"{vote_id}:"
                f"{vote_type.lower()}"
            ),
        )

        self.voting_system = voting_system
        self.vote_id = vote_id
        self.vote_type = vote_type

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:

        vote = (
            self.voting_system.active_votes.get(
                self.vote_id
            )
        )

        if vote is None:

            await interaction.response.send_message(
                "This vote is no longer active.",
                ephemeral=True,
            )

            return

        if vote.closed:

            await interaction.response.send_message(
                "This vote is already closed.",
                ephemeral=True,
            )

            return

        member = interaction.user

        if member.id not in vote.voters:

            await interaction.response.send_message(
                "You are not an eligible voter in this roll call.",
                ephemeral=True,
            )

            return

        old_vote = vote.get_vote(
            member.id
        )

        if old_vote == self.vote_type:

            await interaction.response.send_message(
                f"Your vote is already recorded as "
                f"**{self.vote_type}**.",
                ephemeral=True,
            )

            return

        changed = vote.set_vote(
            member.id,
            self.vote_type,
        )

        if not changed:

            await interaction.response.send_message(
                "Your vote could not be recorded.",
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        if vote.message is not None:

            await vote.message.edit(
                embed=vote.build_embed(),
                view=self.voting_system.build_view(
                    vote
                ),
            )

        now = datetime.now(
            timezone.utc
        )

        print(
            f"[{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] "
            f"Vote {vote.vote_id} | "
            f"{member} | "
            f"{old_vote} -> {self.vote_type}"
        )


class VoteView(discord.ui.View):
    """Persistent view for a legislative vote."""

    def __init__(
        self,
        voting_system: "VotingSystem",
        vote_id: int,
        disabled: bool = False,
    ) -> None:

        super().__init__(
            timeout=None
        )

        self.voting_system = voting_system
        self.vote_id = vote_id

        self.add_item(
            VoteButton(
                voting_system,
                vote_id,
                "Yea",
                "YEA",
            )
        )

        self.add_item(
            VoteButton(
                voting_system,
                vote_id,
                "Nay",
                "NAY",
            )
        )

        self.add_item(
            VoteButton(
                voting_system,
                vote_id,
                "Pres",
                "PRES",
            )
        )

        if disabled:
            self.disable_buttons()

    def disable_buttons(self) -> None:

        for item in self.children:

            if isinstance(
                item,
                discord.ui.Button,
            ):
                item.disabled = True


class VotingSystem:
    """Manages active legislative votes, timers, and recovery."""

    def __init__(
        self,
        bot: commands.Bot,
        database: Database,
    ) -> None:

        self.bot = bot
        self.database = database

        self.active_votes: dict[
            int,
            LegislativeVote,
        ] = {}

        self.closing_tasks: dict[
            int,
            asyncio.Task,
        ] = {}

        self.countdown_tasks: dict[
            int,
            asyncio.Task,
        ] = {}

    def build_view(
        self,
        vote: LegislativeVote,
    ) -> VoteView:

        return VoteView(
            self,
            vote.vote_id,
            disabled=vote.closed,
        )

    async def load_active_votes(self) -> None:
        """Recover all open votes after a bot restart."""

        rows = self.database.get_open_votes()

        if not rows:
            print(
                "No open legislative votes to recover."
            )
            return

        print(
            f"Recovering {len(rows)} open legislative "
            f"vote(s)..."
        )

        for row in rows:

            vote_id = row["id"]

            try:
                await self._recover_vote(
                    row
                )

            except Exception as exc:

                print(
                    f"[Vote {vote_id}] "
                    f"Recovery failed: "
                    f"{type(exc).__name__}: {exc}"
                )

    async def _recover_vote(
        self,
        row,
    ) -> None:
        """Recover one individual open vote."""

        vote_id = row["id"]

        # ---------------------------------------------------------
        # Retrieve the guild.
        # ---------------------------------------------------------

        guild = self.bot.get_guild(
            row["guild_id"]
        )

        if guild is None:

            print(
                f"[Vote {vote_id}] "
                f"Guild unavailable; skipping recovery."
            )

            return

        # ---------------------------------------------------------
        # Retrieve the channel.
        # ---------------------------------------------------------

        channel = guild.get_channel(
            row["channel_id"]
        )

        if channel is None:

            print(
                f"[Vote {vote_id}] "
                f"Channel unavailable; skipping recovery."
            )

            return

        # ---------------------------------------------------------
        # Parse timestamps.
        # ---------------------------------------------------------

        opened_at = datetime.fromisoformat(
            row["opened_at"]
        )

        closes_at = datetime.fromisoformat(
            row["closes_at"]
        )

        remaining = (
            closes_at
            - datetime.now(timezone.utc)
        ).total_seconds()

        # ---------------------------------------------------------
        # Check message ID.
        #
        # Older broken test votes may not have one.
        # ---------------------------------------------------------

        message_id = row["message_id"]

        if message_id is None:

            print(
                f"[Vote {vote_id}] "
                f"Message ID is missing."
            )

            if remaining <= 0:

                self.database.close_vote(
                    vote_id
                )

                print(
                    f"[Vote {vote_id}] "
                    f"Expired record closed in database."
                )

            else:

                print(
                    f"[Vote {vote_id}] "
                    f"Cannot recover because "
                    f"message_id is missing."
                )

            return

        # ---------------------------------------------------------
        # Retrieve original message.
        # ---------------------------------------------------------

        try:

            message = await channel.fetch_message(
                message_id
            )

        except discord.NotFound:

            print(
                f"[Vote {vote_id}] "
                f"Recovery failed: the original message "
                f"no longer exists."
            )

            if remaining <= 0:
                self.database.close_vote(
                    vote_id
                )

            return

        except discord.Forbidden:

            permissions = channel.permissions_for(
                guild.me
            )

            print(
                f"[Vote {vote_id}] "
                f"Recovery failed: Discord denied access "
                f"to the original message."
            )

            print(
                f"[Vote {vote_id}] "
                f"Channel permissions — "
                f"view_channel={permissions.view_channel}, "
                f"send_messages={permissions.send_messages}, "
                f"read_message_history={permissions.read_message_history}"
            )

            if remaining <= 0:

                self.database.close_vote(
                    vote_id
                )

            return

        except discord.HTTPException as exc:

            print(
                f"[Vote {vote_id}] "
                f"Discord returned an HTTP error: "
                f"{exc}"
            )

            return

        # ---------------------------------------------------------
        # Reconstruct electorate.
        # ---------------------------------------------------------

        voter_rows = self.database.get_voters(
            vote_id
        )

        voters: dict[
            int,
            discord.Member,
        ] = {}

        for voter_row in voter_rows:

            member_id = voter_row[
                "member_id"
            ]

            member = guild.get_member(
                member_id
            )

            if member is None:

                try:

                    member = (
                        await guild.fetch_member(
                            member_id
                        )
                    )

                except discord.NotFound:

                    print(
                        f"[Vote {vote_id}] "
                        f"Voter {member_id} "
                        f"is no longer in the server."
                    )

                    continue

            if member.bot:
                continue

            voters[member.id] = member

        # ---------------------------------------------------------
        # Reconstruct vote.
        # ---------------------------------------------------------

        vote = LegislativeVote(
            database=self.database,
            vote_id=vote_id,
            guild=guild,
            channel=channel,
            message_id=message.id,
            measure=row["measure"],
            title=row["title"],
            duration_minutes=row["duration_minutes"],
            voters=voters,
            opened_at=opened_at,
            closes_at=closes_at,
            creator_id=row["creator_id"],
            role_id=row["role_id"],
            decisive=bool(row["decisive"]),
            threshold=row["threshold"],
            closed=False,
        )

        vote.message = message

        self.active_votes[
            vote_id
        ] = vote

        # ---------------------------------------------------------
        # If already expired, close immediately.
        # ---------------------------------------------------------

        if remaining <= 0:

            print(
                f"[Vote {vote_id}] "
                f"Already expired; finalizing now."
            )

            await self.finish_vote(
                vote_id
            )

            return

        # ---------------------------------------------------------
        # Restore persistent buttons.
        # ---------------------------------------------------------

        view = self.build_view(
            vote
        )

        self.bot.add_view(
            view,
            message_id=message.id,
        )

        # ---------------------------------------------------------
        # Restore closing timer.
        # ---------------------------------------------------------

        self.closing_tasks[
            vote_id
        ] = asyncio.create_task(
            self.close_vote_after(
                vote_id,
                remaining,
            )
        )

        # ---------------------------------------------------------
        # Restore countdown display.
        # ---------------------------------------------------------

        self.countdown_tasks[
            vote_id
        ] = asyncio.create_task(
            self.update_countdown(
                vote_id
            )
        )

        print(
            f"[Vote {vote_id}] "
            f"Recovered; "
            f"{remaining:.0f}s remaining."
        )

    async def close_vote_after(
        self,
        vote_id: int,
        seconds: float,
    ) -> None:
        """Wait until the scheduled closing time."""

        try:

            await asyncio.sleep(
                max(
                    0,
                    seconds,
                )
            )

            await self.finish_vote(
                vote_id
            )

        except asyncio.CancelledError:
            raise

    async def update_countdown(
        self,
        vote_id: int,
    ) -> None:
        """
        Periodically update the vote message so that the
        displayed MM:SS countdown remains current.
        """

        try:

            while True:

                vote = self.active_votes.get(
                    vote_id
                )

                if vote is None:
                    return

                if vote.closed:
                    return

                if vote.message is None:
                    return

                remaining = (
                    vote.closes_at
                    - datetime.now(timezone.utc)
                ).total_seconds()

                if remaining <= 0:
                    return

                try:

                    await vote.message.edit(
                        embed=vote.build_embed()
                        ,
                        view=self.build_view(
                            vote
                        ),
                    )

                except aiohttp.client_exceptions.ServerDisconnectedError:
                    print(
                        f"[Vote {vote_id}] "
                        f"Discord connection closed during "
                        f"countdown update."
                    )
                    return

                except discord.NotFound:
                    print(
                        f"[Vote {vote_id}] "
                        f"Original message disappeared "
                        f"during countdown update."
                    )
                    return

                except discord.Forbidden:
                    print(
                        f"[Vote {vote_id}] "
                        f"Lost access during countdown update."
                    )
                    return

                except discord.HTTPException as exc:
                    print(
                        f"[Vote {vote_id}] "
                        f"Countdown update failed: "
                        f"{exc}"
                    )

                # Normal updates every two seconds.
                #
                # Once the vote is nearly finished, update
                # every second to make the clock precise.
                if remaining <= 60:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            raise

    async def finish_vote(
        self,
        vote_id: int,
    ) -> None:
        """Permanently close a vote."""

        vote = self.active_votes.get(
            vote_id
        )

        # ---------------------------------------------------------
        # The Python object may not exist, for example if an old
        # malformed database entry is being closed manually.
        # ---------------------------------------------------------

        if vote is None:

            self.database.close_vote(
                vote_id
            )

            closing_task = (
                self.closing_tasks.pop(
                    vote_id,
                    None,
                )
            )

            if (
                closing_task is not None
                and not closing_task.done()
            ):
                closing_task.cancel()

            countdown_task = (
                self.countdown_tasks.pop(
                    vote_id,
                    None,
                )
            )

            if (
                countdown_task is not None
                and not countdown_task.done()
            ):
                countdown_task.cancel()

            return

        if vote.closed:
            return

        # ---------------------------------------------------------
        # Mark database closed FIRST.
        # ---------------------------------------------------------

        vote.closed = True
        
        result = vote.result

        self.database.set_result(
            vote_id,
            result,
        )

        self.database.close_vote(
            vote_id
        )

        # ---------------------------------------------------------
        # Stop countdown task.
        # ---------------------------------------------------------

        countdown_task = (
            self.countdown_tasks.pop(
                vote_id,
                None,
            )
        )

        current_task = asyncio.current_task()

        if (
            countdown_task is not None
            and countdown_task is not current_task
            and not countdown_task.done()
        ):
            countdown_task.cancel()

        # ---------------------------------------------------------
        # Disable buttons and update final record.
        # ---------------------------------------------------------

        view = self.build_view(
            vote
        )

        if vote.message is not None:

            try:

                await vote.message.edit(
                    embed=vote.build_embed(
                        final=True
                    ),
                    view=view,
                )

            except discord.NotFound:

                print(
                    f"[Vote {vote_id}] "
                    f"Original message no longer exists."
                )

            except discord.Forbidden:

                print(
                    f"[Vote {vote_id}] "
                    f"Cannot modify original message."
                )

            except discord.HTTPException as exc:

                print(
                    f"[Vote {vote_id}] "
                    f"Failed to update final result: "
                    f"{exc}"
                )

        self.active_votes.pop(
            vote_id,
            None,
        )

        closing_task = (
            self.closing_tasks.pop(
                vote_id,
                None,
            )
        )

        if (
            closing_task is not None
            and closing_task is not current_task
            and not closing_task.done()
        ):
            closing_task.cancel()

        now = datetime.now(
            timezone.utc
        )

        print(
            f"[{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] "
            f"Vote {vote_id} closed."
        )

    async def close_vote_manual(
        self,
        vote_id: int,
    ) -> bool:
        """
        Manually close a vote.

        Returns True if a vote was found in the database.
        """

        row = self.database.get_vote(
            vote_id
        )

        if row is None:
            return False

        if row["closed"]:
            return True

        # If the active in-memory vote exists, use the
        # normal finalization path.
        if vote_id in self.active_votes:

            await self.finish_vote(
                vote_id
            )

            return True

        # Otherwise this may be an old malformed or unrecovered
        # database record. Close it safely in SQLite.
        self.database.close_vote(
            vote_id
        )

        print(
            f"[Vote {vote_id}] "
            f"Manually closed directly in database."
        )

        return True


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

        eligible.append(
            member
        )

    return eligible


async def register(
    bot: commands.Bot,
    database: Database,
) -> VotingSystem:

    decisive_choices = [
        app_commands.Choice(
            name="Yes",
            value="yes",
        ),
        app_commands.Choice(
            name="No",
            value="no",
        ),
    ]


    threshold_choices = [
        app_commands.Choice(
            name="Majority",
            value="majority",
        ),
        app_commands.Choice(
            name="Plurality",
            value="plurality",
        ),
        app_commands.Choice(
            name="Three-Fifths",
            value="three_fifths",
        ),
        app_commands.Choice(
            name="Two-Thirds",
            value="two_thirds",
        ),
        app_commands.Choice(
            name="Unanimity",
            value="unanimity",
        ),
    ]

    voting_system = VotingSystem(
        bot,
        database,
    )

    bot.voting_system = voting_system

    legis_group = app_commands.Group(
        name="legisvote",
        description=(
            "Electronic legislative roll-call system."
        ),
    )

    @legis_group.command(
        name="open",
        description=(
            "Open an electronic legislative roll-call vote."
        ),
    )
    @app_commands.describe(
        measure="The legislative measure, e.g. S. 5",
        title="The title of the measure",
        duration="Voting duration in minutes; defaults to 15",
        role="Optional role restricting who may vote",
        decisive="Whether the vote produces a pass/fail determination",
        threshold="The winning condition for a decisive vote",
    )
    @app_commands.choices(
        decisive=decisive_choices,
        threshold=threshold_choices,
    )
    async def legisvote_open(
        interaction: discord.Interaction,
        measure: str,
        title: str,
        duration: int = 15,
        role: Optional[discord.Role] = None,
        decisive: str = "yes",
        threshold: str = "majority",
    ) -> None:
        
        decisive_value = decisive.lower()

        if decisive_value not in {"yes", "no"}:
            await interaction.response.send_message(
                "Invalid decisive setting.",
                ephemeral=True,
            )
            return

        decisive_bool = (
            decisive_value == "yes"
        )

        if threshold not in VALID_THRESHOLDS:
            await interaction.response.send_message(
                "Invalid voting threshold.",
                ephemeral=True,
            )
            return

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
            + timedelta(
                minutes=duration
            )
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
            decisive=decisive_bool,
            threshold=threshold,
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
            guild=interaction.guild,
            channel=interaction.channel,
            message_id=0,
            measure=measure,
            title=title,
            duration_minutes=duration,
            voters={
                member.id: member
                for member in voters
            },
            opened_at=opened_at,
            closes_at=closes_at,
            creator_id=creator.id,
            role_id=(
                role.id
                if role is not None
                else None
            ),
            decisive=decisive_bool,
            threshold=threshold,
        )

        view = voting_system.build_view(
            vote
        )

        await interaction.response.send_message(
            embed=vote.build_embed(),
            view=view,
        )

        vote.message = (
            await interaction.original_response()
        )

        vote.message_id = vote.message.id

        database.set_message_id(
            vote_id,
            vote.message.id,
        )

        voting_system.active_votes[
            vote_id
        ] = vote

        task = asyncio.create_task(
            voting_system.close_vote_after(
                vote_id,
                duration * 60,
            )
        )

        voting_system.closing_tasks[
            vote_id
        ] = task

        voting_system.countdown_tasks[
            vote_id
        ] = asyncio.create_task(
            voting_system.update_countdown(
                vote_id
            )
        )

        now = datetime.now(
            timezone.utc
        )

        print(
            f"[{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] "
            f"Vote {vote_id} opened | "
            f"{measure}—{title} | "
            f"Voters: {len(voters)}"
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

            threshold = THRESHOLD_LABELS.get(
                row["threshold"],
                row["threshold"],
            )

            vote_type = (
                "DECISIVE"
                if row["decisive"]
                else "NON-DECISIVE"
            )

            # -----------------------------------------------------
            # Only decisive votes have a result.
            # Open decisive votes are still pending.
            # -----------------------------------------------------

            if row["decisive"]:
                result = (
                    row["result"]
                    if row["result"] is not None
                    else "PENDING"
                )

                result_line = (
                    f"Result: **{result}**\n"
                )
            else:
                result_line = ""

            closes_at = datetime.fromisoformat(
                row["closes_at"]
            )

            lines.append(
                f"**Vote {row['id']}** — "
                f"{row['measure']}—{row['title']}\n\n"
                f"Vote Type: **{vote_type}**\n"
                f"Threshold: **{threshold}**\n"
                f"{result_line}"
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
            min(limit, 25),
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
                    f"#{row['id']} "
                    f"{row['measure']}",
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
        description=(
            "Show the official record of a legislative vote."
        ),
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

        decision = (
            "DECISIVE"
            if row["decisive"]
            else "NON-DECISIVE"
        )

        threshold = THRESHOLD_LABELS.get(
            row["threshold"],
            row["threshold"],
        )

        result = (
            row["result"]
            if row["result"] is not None
            else "NO DETERMINATION"
        )

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

            member = interaction.guild.get_member(
                member_id
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
                (
                    "Yea",
                    str(summary_counts["Yea"]),
                ),
                (
                    "Nay",
                    str(summary_counts["Nay"]),
                ),
                (
                    "Pres",
                    str(summary_counts["Pres"]),
                ),
                (
                    "NV",
                    str(summary_counts["NV"]),
                ),
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
            f"Decision: **{decision}**\n"
            f"Threshold: **{threshold}**\n"
            f"Result: **{result}**\n"
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
            title=(
                f"LEGISLATIVE VOTE RECORD "
                f"#{vote_id}"
            ),
            description=description,
        )

        await interaction.response.send_message(
            embed=embed
        )

    @legis_group.command(
        name="close",
        description="Manually close an open legislative vote.",
    )
    @app_commands.describe(
        vote_id="The ID of the vote to close",
    )
    async def legisvote_close(
        interaction: discord.Interaction,
        vote_id: int,
    ) -> None:

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
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

        if legislative_role not in creator.roles:
            await interaction.response.send_message(
                "Only Members of the Legislative may close "
                "a legislative vote.",
                ephemeral=True,
            )
            return

        row = database.get_vote(
            vote_id
        )

        if row is None:
            await interaction.response.send_message(
                f"Vote {vote_id} does not exist.",
                ephemeral=True,
            )
            return

        if row["guild_id"] != interaction.guild.id:
            await interaction.response.send_message(
                "That vote does not belong to this server.",
                ephemeral=True,
            )
            return

        if row["closed"]:
            await interaction.response.send_message(
                f"Vote {vote_id} is already closed.",
                ephemeral=True,
            )
            return

        closed = await voting_system.close_vote_manual(
            vote_id
        )

        if not closed:
            await interaction.response.send_message(
                f"Vote {vote_id} could not be closed.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Vote **#{vote_id}** has been manually closed.",
        )


    bot.tree.add_command(
        legis_group
    )

    return voting_system