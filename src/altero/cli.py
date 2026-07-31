"""Command line for running and administering the server.

The Web API has no way to create an account or issue a credential, so a
deployment is set up from here.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Database
from altero.errors import AlteroError
from altero.services import admin, auth, login
from altero.settings import Settings, get_settings


def _serve(settings: Settings) -> None:
    """Run the development server."""
    import uvicorn

    uvicorn.run(
        "altero.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


async def _with_session(
    settings: Settings, work: Callable[[AsyncSession], Awaitable[None]]
) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            await work(session)
    finally:
        await database.dispose()


async def _user_add(session: AsyncSession, args: argparse.Namespace) -> None:
    user = await admin.create_user(
        session,
        username=args.username,
        display_name=args.display_name or "",
        user_id=args.id,
    )
    print(f"Created user {user.username} with id {user.id} and a personal library.")


async def _user_list(session: AsyncSession, args: argparse.Namespace) -> None:
    users = await admin.list_users(session)
    if not users:
        print("No users.")
        return
    for user in users:
        print(f"{user.id:>8}  {user.username}  {user.display_name}".rstrip())


async def _key_add(session: AsyncSession, args: argparse.Namespace) -> None:
    api_key = await admin.create_api_key(
        session,
        username=args.username,
        name=args.name,
        write=not args.read_only,
        all_groups_read=args.groups,
        all_groups_write=args.groups and not args.read_only,
    )
    # Printed once and never recoverable, so it has to stand out.
    print(f"Key for {args.username}: {api_key.key}")
    print("Store it now; it cannot be shown again.")


async def _key_list(session: AsyncSession, args: argparse.Namespace) -> None:
    keys = await admin.list_api_keys(session)
    if not keys:
        print("No keys.")
        return
    for key in keys:
        access = "rw" if key.library_write else "r-"
        print(f"{key.key}  user={key.user_id}  {access}  {key.name}")


async def _key_revoke(session: AsyncSession, args: argparse.Namespace) -> None:
    await admin.revoke_api_key(session, args.key)
    print("Revoked.")


async def _group_add(session: AsyncSession, args: argparse.Namespace) -> None:
    library = await admin.create_group(
        session, name=args.name, owner_username=args.owner, public=args.public
    )
    print(f"Created group '{library.name}' with id {library.owner_id}.")


async def _group_member_add(session: AsyncSession, args: argparse.Namespace) -> None:
    libraries = await admin.list_libraries(session)
    library = next((lib for lib in libraries if lib.owner_id == args.group), None)
    if library is None:
        raise AlteroError(f"No group with id {args.group}")

    await admin.add_group_member(session, library, username=args.username, role=args.role)
    print(f"Added {args.username} to group {args.group} as {args.role}.")


async def _login_list(session: AsyncSession, args: argparse.Namespace) -> None:
    pending = await login.list_pending(session)
    if not pending:
        print("No logins waiting for approval.")
        return
    for entry in pending:
        wanted = f" (expects user {entry.requested_user_id})" if entry.requested_user_id else ""
        print(f"{entry.token}  started {entry.created:%Y-%m-%d %H:%M}{wanted}")


async def _login_approve(session: AsyncSession, args: argparse.Namespace) -> None:
    if args.key:
        api_key = await auth.get_api_key_by_value(session, args.key)
    else:
        # Issuing a key here means the usual case is one command, not two.
        api_key = await admin.create_api_key(session, username=args.username, name="Zotero client")

    await login.approve_session(session, args.token, api_key)
    print(f"Approved. The client will continue with key {api_key.key}.")


async def _library_list(session: AsyncSession, args: argparse.Namespace) -> None:
    libraries = await admin.list_libraries(session)
    if not libraries:
        print("No libraries.")
        return
    for library in libraries:
        visibility = "public" if library.public else "private"
        print(
            f"{library.type.value:>6}/{library.owner_id:<8} "
            f"version={library.version:<6} {visibility}  {library.name}".rstrip()
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="altero", description=__doc__)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("serve", help="run the server (the default)")

    user = commands.add_parser("user", help="manage users").add_subparsers(dest="subcommand")
    add = user.add_parser("add", help="create a user and their personal library")
    add.add_argument("username")
    add.add_argument("--display-name", default="")
    add.add_argument("--id", type=int, help="assign a specific user id")
    add.set_defaults(handler=_user_add)
    user.add_parser("list", help="list users").set_defaults(handler=_user_list)

    key = commands.add_parser("key", help="manage API keys").add_subparsers(dest="subcommand")
    add = key.add_parser("add", help="issue a key for a user")
    add.add_argument("username")
    add.add_argument("--name", default="", help="a label to recognise the key by")
    add.add_argument("--read-only", action="store_true", help="withhold write access")
    add.add_argument("--groups", action="store_true", help="also grant access to groups")
    add.set_defaults(handler=_key_add)
    key.add_parser("list", help="list keys").set_defaults(handler=_key_list)
    revoke = key.add_parser("revoke", help="delete a key")
    revoke.add_argument("key")
    revoke.set_defaults(handler=_key_revoke)

    group = commands.add_parser("group", help="manage groups").add_subparsers(dest="subcommand")
    add = group.add_parser("add", help="create a group library")
    add.add_argument("name")
    add.add_argument("--owner", required=True, help="username of the owner")
    add.add_argument("--public", action="store_true")
    add.set_defaults(handler=_group_add)
    member = group.add_parser("member", help="add a member")
    member.add_argument("group", type=int)
    member.add_argument("username")
    member.add_argument("--role", default="member", choices=["member", "admin"])
    member.set_defaults(handler=_group_member_add)

    login_parser = commands.add_parser(
        "login", help="approve a desktop client login"
    ).add_subparsers(dest="subcommand")
    login_parser.add_parser("list", help="show logins waiting for approval").set_defaults(
        handler=_login_list
    )
    approve = login_parser.add_parser("approve", help="approve a waiting login")
    approve.add_argument("token")
    approve.add_argument("username", help="the account to log the client in as")
    approve.add_argument("--key", help="use this existing key instead of issuing a new one")
    approve.set_defaults(handler=_login_approve)

    library = commands.add_parser("library", help="inspect libraries").add_subparsers(
        dest="subcommand"
    )
    library.add_parser("list", help="list libraries").set_defaults(handler=_library_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command in (None, "serve"):
        _serve(settings)
        return 0

    handler: Callable[[AsyncSession, argparse.Namespace], Awaitable[Any]] | None = getattr(
        args, "handler", None
    )
    if handler is None:
        parser.parse_args([args.command, "--help"])
        return 2

    async def work(session: AsyncSession) -> None:
        await handler(session, args)

    try:
        asyncio.run(_with_session(settings, work))
    except AlteroError as error:
        print(f"error: {error.message}")
        return 1
    return 0
