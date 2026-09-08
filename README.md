# legis-electronic-voting-Bot

A custom Discord bot for conducting and recording legislative roll-call votes for Discord Servers with proper voting systems.

## Purpose

`legis-electronic-voting-Bot` is designed to provide an electronic legislative voting system for Discord Servers.

The bot is intended to support voting on the legislative procedures established by the Constitution and laws of such servers, including the use of the following voting classifications:

- **Yea** — Vote in favor.
- **Nay** — Vote against.
- **Pres** — Present, without casting a substantive vote.
- **NV** — Not Voting.

`NV` is the default status of an eligible Legislative Member at the beginning of a vote.

## Keys and Required Assets

Create a `.env` for use as an environment variable. The file `env_example.txt` is given as a template.

The exact Discord IDs are configurable and should not be hard-coded into the repository where avoidable.

---

## Planned Features
* Slash-command legislative voting
* Automatic identification of eligible Legislative Members
* Automatic initialization of eligible voters as NV
* Yea, Nay, and Pres voting buttons
* Fifteen-minute voting periods
* Ability to change a vote before the voting period expires
* Automatic closing of votes
* Automatic final roll-call generation
* Vote totals
* Individual voting records
* SQLite-based persistence
* Audit logging
* Legislative forum integration
* Passed/failed determination according to the applicable voting requirement
* Requirements
* Python 3.12 or later
* discord.py
* python-dotenv
* A Discord application with a bot
* Server Members Intent enabled in the Discord Developer Portal

## Installation

Clone the repository:

```
git clone <repository-url>
cd legis-electronic-voting-Bot
```

Create a virtual environment:

```
python -m venv .venv
```

Activate it on Windows PowerShell:

```
.\.venv\Scripts\activate.ps1
```

Install dependencies:

```
python -m pip install -r requirements.txt
```

Create a .env file:

```
DISCORD_TOKEN=your_discord_bot_token
```

Never commit .env to the repository.

## Running the Bot

Run the command `python bot.py`.

The current test command is `/ping` A successful response should be `Pong!`

## Discord Permissions

The bot should be granted only the permissions necessary for its operation.

The current implementation requires access sufficient to:

* View Channels
* Send Messages
* Embed Links
* Read Message History
* Use Application Commands

The bot uses the Server Members Intent so that it can identify eligible Legislative Members by role.

## Security

The Discord bot token is a secret credential.

Do not—
* commit the token to Git;
* place the token directly in source code;
* publish the .env file;
* upload screenshots containing the token; or
* share the token publicly.

If the token is exposed, regenerate it through the Discord Developer Portal immediately.

## Project Status

The project is currently under development.

The initial implementation establishes the Discord application and bot connection. Legislative roll-call functionality is being developed incrementally.

## License

To be determined.