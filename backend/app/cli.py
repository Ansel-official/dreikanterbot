"""运维 CLI：在容器内直接重置密码或创建账号（忘记管理员密码时的救命入口）。

用法（在项目根目录）：
    docker compose exec backend python -m app.cli reset-password --username admin
    docker compose exec backend python -m app.cli create-user --username ops --role admin

不传 --password 时会交互式输入，避免密码进入 shell history。
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

import asyncpg

from .database import close_db, get_pool, init_db
from .security import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
)


def _prompt_password(label: str) -> str:
    password = getpass.getpass(label)
    if password != getpass.getpass("请再次输入: "):
        raise SystemExit("两次输入的密码不一致")
    validate_password_policy(password)
    return password


async def _reset_password(username: str, password: str) -> int:
    await init_db()
    try:
        pool = get_pool()
        target = await pool.fetchrow(
            "SELECT id, username, role FROM users WHERE username = $1",
            username.strip().lower(),
        )
        if target is None:
            print(f"用户不存在：{username}", file=sys.stderr)
            return 1
        await pool.execute(
            """
            UPDATE users
            SET password_hash = $1, token_version = token_version + 1,
                is_active = TRUE, updated_at = NOW()
            WHERE id = $2
            """,
            hash_password(password),
            target["id"],
        )
        print(f"已重置 {target['username']} 的密码；该用户所有旧 JWT 已失效。")
        return 0
    finally:
        await close_db()


async def _create_user(username: str, password: str, role: str) -> int:
    await init_db()
    try:
        pool = get_pool()
        try:
            row = await pool.fetchrow(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES ($1, $2, $3)
                RETURNING id, username, role
                """,
                username.strip().lower(),
                hash_password(password),
                role,
            )
        except asyncpg.UniqueViolationError:
            print(f"用户名已存在：{username}", file=sys.stderr)
            return 1
        print(f"已创建用户 {row['username']}（{row['role']}，ID {row['id']}）")
        return 0
    finally:
        await close_db()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepSeek Chatbot 运维 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    reset = sub.add_parser("reset-password", help="重置已存在用户的密码并踢出所有旧会话")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password", help="不传则交互式输入")

    create = sub.add_parser("create-user", help="直接创建账号（用于管理员恢复/初始化）")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=["admin", "member", "guest"], default="member")
    create.add_argument("--password", help="不传则交互式输入")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        password = args.password or _prompt_password("请输入新密码: ")
        validate_password_policy(password)
    except PasswordPolicyError as exc:
        print(f"密码不符合策略：{exc}", file=sys.stderr)
        return 2

    if args.command == "reset-password":
        return asyncio.run(_reset_password(args.username, password))
    if args.command == "create-user":
        return asyncio.run(_create_user(args.username, password, args.role))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
