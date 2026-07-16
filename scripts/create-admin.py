from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import auth_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或提升 Speech Flow 管理员账户")
    parser.add_argument("--username", help="管理员用户名；省略时交互输入")
    args = parser.parse_args()
    username = (args.username or input("管理员用户名: ")).strip()
    try:
        existing = auth_store.user_by_username(username)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if existing:
        auth_store.set_user_admin(existing.id, True)
        auth_store.set_user_active(existing.id, True)
        print(f"账户 {existing.username} 已设为管理员并启用。")
        return 0

    password = getpass.getpass("管理员密码（至少8位）: ")
    confirmation = getpass.getpass("再次输入密码: ")
    if password != confirmation:
        print("错误: 两次输入的密码不一致。", file=sys.stderr)
        return 1
    try:
        user = auth_store.create_user(username, password, is_admin=True)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(f"管理员 {user.username} 创建成功。登录后访问 /admin。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
