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
    import psycopg2
    from passlib.context import CryptContext
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Run: pip install psycopg2-binary passlib[bcrypt]")
    sys.exit(1)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    print("=" * 50)
    print("  Gmail Bot — Owner Account Setup")
    print("=" * 50)
    print()

    # Check env vars
    db_url = os.environ.get("DATABASE_URL", "")

    if not db_url:
        print("ERROR: DATABASE_URL must be set.")
        print("Set it in your .env file or environment variables.")
        print("Format: postgresql://user:pass@host:port/dbname")
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
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
    except Exception as e:
        print(f"ERROR connecting to database: {e}")
        sys.exit(1)

    # Check if owner already exists
    cur.execute("SELECT id, username FROM admins WHERE role='owner'")
    existing = cur.fetchone()
    if existing:
        print(f"\nWARNING: An owner account already exists: '{existing[1]}' (ID: {existing[0]})")
        answer = input("Do you want to create another owner? (y/N): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            cur.close(); conn.close()
            sys.exit(0)

    # Check duplicate username
    cur.execute("SELECT id FROM admins WHERE username=%s", (username,))
    if cur.fetchone():
        print(f"ERROR: Username '{username}' already exists.")
        cur.close(); conn.close()
        sys.exit(1)

    # Create owner
    hashed = pwd_context.hash(password)
    cur.execute(
        "INSERT INTO admins (username, password_hash, role) VALUES (%s, %s, 'owner')",
        (username, hashed),
    )
    conn.commit()

    cur.execute("SELECT id FROM admins WHERE username=%s", (username,))
    created = cur.fetchone()
    cur.close()
    conn.close()

    print()
    print("✅ Owner account created successfully!")
    print(f"   Username: {username}")
    print(f"   ID:       {created[0]}")
    print()
    print("You can now log in to the Desktop Admin Panel with these credentials.")


if __name__ == "__main__":
    main()
