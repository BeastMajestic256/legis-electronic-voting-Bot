from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DATABASE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "votes.db"
)


class Database:
    """SQLite database used to persist legislative votes."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
        )

        self.connection.row_factory = sqlite3.Row

        self._create_tables()
        self._migrate()

    def _create_tables(self) -> None:
        cursor = self.connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                creator_id INTEGER NOT NULL DEFAULT 0,
                role_id INTEGER,
                measure TEXT NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                opened_at TEXT NOT NULL,
                closes_at TEXT NOT NULL,
                closed INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS voters (
                vote_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                vote TEXT NOT NULL DEFAULT 'NV',

                PRIMARY KEY (vote_id, member_id),

                FOREIGN KEY (vote_id)
                    REFERENCES votes(id)
                    ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vote_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vote_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                old_vote TEXT,
                new_vote TEXT NOT NULL,
                changed_at TEXT NOT NULL,

                FOREIGN KEY (vote_id)
                    REFERENCES votes(id)
                    ON DELETE CASCADE
            )
            """
        )

        self.connection.commit()

    def _migrate(self) -> None:
        """
        Add columns introduced after the original schema.

        SQLite does not modify an existing table when
        CREATE TABLE IF NOT EXISTS is called, so we explicitly
        add missing columns here.
        """

        cursor = self.connection.cursor()

        cursor.execute("PRAGMA table_info(votes)")
        columns = {
            row["name"]
            for row in cursor.fetchall()
        }

        if "creator_id" not in columns:
            cursor.execute(
                """
                ALTER TABLE votes
                ADD COLUMN creator_id INTEGER NOT NULL DEFAULT 0
                """
            )

        if "role_id" not in columns:
            cursor.execute(
                """
                ALTER TABLE votes
                ADD COLUMN role_id INTEGER
                """
            )

        self.connection.commit()

    @staticmethod
    def now_iso() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def create_vote(
        self,
        guild_id: int,
        channel_id: int,
        creator_id: int,
        role_id: Optional[int],
        measure: str,
        title: str,
        duration_minutes: int,
        opened_at: datetime,
        closes_at: datetime,
    ) -> int:

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO votes (
                guild_id,
                channel_id,
                creator_id,
                role_id,
                measure,
                title,
                duration_minutes,
                opened_at,
                closes_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                creator_id,
                role_id,
                measure,
                title,
                duration_minutes,
                opened_at.isoformat(),
                closes_at.isoformat(),
            ),
        )

        self.connection.commit()

        return int(cursor.lastrowid)

    def set_message_id(
        self,
        vote_id: int,
        message_id: int,
    ) -> None:

        self.connection.execute(
            """
            UPDATE votes
            SET message_id = ?
            WHERE id = ?
            """,
            (message_id, vote_id),
        )

        self.connection.commit()

    def add_voter(
        self,
        vote_id: int,
        member_id: int,
    ) -> None:

        self.connection.execute(
            """
            INSERT OR IGNORE INTO voters (
                vote_id,
                member_id,
                vote
            )
            VALUES (?, ?, 'NV')
            """,
            (
                vote_id,
                member_id,
            ),
        )

        self.connection.commit()

    def get_voter_vote(
        self,
        vote_id: int,
        member_id: int,
    ) -> Optional[str]:

        cursor = self.connection.execute(
            """
            SELECT vote
            FROM voters
            WHERE vote_id = ?
              AND member_id = ?
            """,
            (
                vote_id,
                member_id,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return str(row["vote"])

    def set_voter_vote(
        self,
        vote_id: int,
        member_id: int,
        new_vote: str,
    ) -> None:

        old_vote = self.get_voter_vote(
            vote_id,
            member_id,
        )

        if old_vote is None:
            raise ValueError(
                "Voter is not registered for this vote."
            )

        self.connection.execute(
            """
            UPDATE voters
            SET vote = ?
            WHERE vote_id = ?
              AND member_id = ?
            """,
            (
                new_vote,
                vote_id,
                member_id,
            ),
        )

        self.connection.execute(
            """
            INSERT INTO vote_events (
                vote_id,
                member_id,
                old_vote,
                new_vote,
                changed_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vote_id,
                member_id,
                old_vote,
                new_vote,
                self.now_iso(),
            ),
        )

        self.connection.commit()

    def close_vote(
        self,
        vote_id: int,
    ) -> None:

        self.connection.execute(
            """
            UPDATE votes
            SET closed = 1
            WHERE id = ?
            """,
            (vote_id,),
        )

        self.connection.commit()

    def get_vote(
        self,
        vote_id: int,
    ) -> Optional[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT *
            FROM votes
            WHERE id = ?
            """,
            (vote_id,),
        )

        return cursor.fetchone()

    def get_voters(
        self,
        vote_id: int,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT member_id, vote
            FROM voters
            WHERE vote_id = ?
            ORDER BY member_id
            """,
            (vote_id,),
        )

        return list(cursor.fetchall())

    def get_vote_events(
        self,
        vote_id: int,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT *
            FROM vote_events
            WHERE vote_id = ?
            ORDER BY id
            """,
            (vote_id,),
        )

        return list(cursor.fetchall())

    def get_recent_votes(
        self,
        limit: int = 10,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT *
            FROM votes
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return list(cursor.fetchall())

    def get_open_votes(
        self,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT *
            FROM votes
            WHERE closed = 0
            ORDER BY id DESC
            """
        )

        return list(cursor.fetchall())

    def close(self) -> None:
        self.connection.close()