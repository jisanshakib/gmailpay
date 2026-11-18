"""
seed_owner.py — Interactive script to create the initial owner admin account.
Run once before first use: python seed_owner.py
"""

import getpass
import os
import sys

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import libsql_client
    from passlib.context import CryptContext
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Run: pip install libsql-client passlib[bcrypt]")
    sys.exit(1)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    print("=" * 50)
    print("  Gmail Bot — Owner Account Setup")
    print("=" * 50)
    print()

    # Check env vars
    db_url = os.environ.get("TURSO_CORE_DB_URL", "")
    db_token = os.environ.get("TURSO_CORE_DB_TOKEN", "")

    if not db_url or not db_token:
        print("ERROR: TURSO_CORE_DB_URL and TURSO_CORE_DB_TOKEN must be set.")
        print("Set them in your .env file or environment variables.")
        sys.exit(1)

    # Get credentials
    username = input("Owner username: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    password = getpass.getpass("Owner password: ")
    if len(password) < 4:
        print("Password must be at least 4 characters.")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    # Connect to database
    try:
        db = libsql_client.create_client_sync(url=db_url, auth_token=db_token)
    except Exception as e:
        print(f"ERROR connecting to database: {e}")
        sys.exit(1)

    # Check if owner already exists
    existing = db.execute("SELECT id, username FROM admins WHERE role='owner'")
    if existing.rows:
        row = existing.rows[0]
        print(f"\nWARNING: An owner account already exists: '{row[1]}' (ID: {row[0]})")
        answer = input("Do you want to create another owner? (y/N): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            db.close()
            sys.exit(0)

    # Check duplicate username
    dup = db.execute("SELECT id FROM admins WHERE username=?", [username])
    if dup.rows:
        print(f"ERROR: Username '{username}' already exists.")
        db.close()
        sys.exit(1)

    # Create owner
    hashed = pwd_context.hash(password)
    db.execute(
        "INSERT INTO admins (username, password_hash, role) VALUES (?, ?, 'owner')",
        [username, hashed],
    )

    created = db.execute("SELECT id FROM admins WHERE username=?", [username])
    db.close()

    print()
    print("✅ Owner account created successfully!")
    print(f"   Username: {username}")
    print(f"   ID:       {created.rows[0][0]}")
    print()
    print("You can now log in to the Desktop Admin Panel with these credentials.")


if __name__ == "__main__":
    main()
