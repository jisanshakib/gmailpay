"""
routes.py — All FastAPI routes in one file: bot-facing, admin, owner.
Uses single Supabase PostgreSQL database via psycopg2.

UPDATED: Gmail Pool replaced with Recovery Emails.
         assign_task now auto-generates gmail + password,
         picks a random unassigned recovery email, and returns all three.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth import get_current_admin, require_owner, hash_password, verify_password, create_access_token
from db import get_db, generate_gmail_credentials
from models import (
    AdminCreate, AdminLogin, AdminResponse, AssignTaskResponse,
    BalanceAdjustment, BalanceResponse, BotSettingsBulkUpdate,
    DashboardStats, ExportRequest, RecoveryEmailBulkUpload, RecoveryEmailResponse,
    MessageResponse, SubmissionCreate, SubmissionResponse, TokenResponse,
    UserBanAction, UserRegister, UserResponse, WithdrawalRequest,
    WithdrawalResponse,
)

# ==========================================================================
#  BOT-FACING ENDPOINTS  (/api/bot/*)
# ==========================================================================
bot_router = APIRouter(prefix="/api/bot", tags=["bot"])


@bot_router.post("/register-user", response_model=UserResponse)
def register_user(user: UserRegister, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s, %s) "
        "ON CONFLICT(telegram_id) DO UPDATE SET username = EXCLUDED.username",
        (user.telegram_id, user.username),
    )
    cur.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users WHERE telegram_id=%s", (user.telegram_id,),
    )
    r = cur.fetchone()
    cur.close()
    return UserResponse(
        telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
        pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
        total_strikes=r[5] or 0, is_banned=bool(r[6]),
        block_until=str(r[7]) if r[7] else None, created_at=str(r[8]) if r[8] else None,
    )


@bot_router.get("/settings")
def get_bot_settings(db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT key_name, key_value FROM bot_settings")
    rows = cur.fetchall()
    cur.close()
    return {r[0]: r[1] for r in rows}


@bot_router.get("/assign-task/{telegram_id}", response_model=AssignTaskResponse)
def assign_task(telegram_id: int, db=Depends(get_db)):
    cur = db.cursor()

    # 1. Check user exists
    cur.execute(
        "SELECT is_banned,total_strikes,block_until FROM users WHERE telegram_id=%s",
        (telegram_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "User not found. Send /start first.")
    is_banned, strikes, block_until = row

    # 2. Ban check
    if is_banned:
        cur.close(); raise HTTPException(403, "🚫 Your account has been banned.")

    # 3. Block check (3-strike rule)
    if block_until:
        try:
            if hasattr(block_until, 'tzinfo'):
                block_dt = block_until if block_until.tzinfo else block_until.replace(tzinfo=timezone.utc)
            else:
                block_dt = datetime.fromisoformat(str(block_until)).replace(tzinfo=timezone.utc)
        except ValueError:
            block_dt = datetime.min.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < block_dt:
            remaining = block_dt - now
            h, m = int(remaining.total_seconds() // 3600), int((remaining.total_seconds() % 3600) // 60)
            cur.close(); raise HTTPException(403, f"⏳ Temporarily blocked due to strikes. Unblocks in {h}h {m}m.")
        cur.execute("UPDATE users SET block_until=NULL WHERE telegram_id=%s", (telegram_id,))

    # 4. Zero Duplicate — check if user already has a pending submission
    cur.execute(
        "SELECT id FROM submissions WHERE telegram_id=%s AND status='pending'", (telegram_id,),
    )
    if cur.fetchone():
        cur.close(); raise HTTPException(409, "⏳ You already have a pending submission. Wait for admin review.")

    # 5. Pick a RANDOM unassigned recovery email
    cur.execute(
        "SELECT id, email FROM recovery_emails "
        "WHERE is_assigned=FALSE ORDER BY RANDOM() LIMIT 1"
    )
    recovery_row = cur.fetchone()
    if not recovery_row:
        cur.close(); raise HTTPException(404, "😔 No available tasks right now. Try again later!")

    # 6. Mark recovery email as assigned
    cur.execute("UPDATE recovery_emails SET is_assigned=TRUE WHERE id=%s", (recovery_row[0],))

    # 7. Auto-generate gmail credentials
    gen_email, gen_password = generate_gmail_credentials()

    # 8. Fetch current rates from bot_settings
    cur.execute("SELECT key_name, key_value FROM bot_settings WHERE key_name IN ('normal_rate','two_fa_rate')")
    rate_rows = cur.fetchall()
    rates = {r[0]: r[1] for r in rate_rows}
    normal_rate = float(rates.get("normal_rate", "0.30"))
    two_fa_rate = float(rates.get("two_fa_rate", "0.50"))

    cur.close()
    return AssignTaskResponse(
        email=gen_email,
        password=gen_password,
        recovery_email=recovery_row[1],
        normal_rate=normal_rate,
        two_fa_rate=two_fa_rate,
    )


@bot_router.post("/submit", response_model=MessageResponse)
def submit_account(sub: SubmissionCreate, db=Depends(get_db)):
    if sub.submission_type not in ("normal", "2fa"):
        raise HTTPException(400, "submission_type must be 'normal' or '2fa'")
    if sub.submission_type == "2fa" and not sub.secret_key_2fa:
        raise HTTPException(400, "secret_key_2fa required for 2fa submissions")

    cur = db.cursor()
    cur.execute("SELECT 1 FROM users WHERE telegram_id=%s", (sub.telegram_id,))
    if not cur.fetchone():
        cur.close(); raise HTTPException(404, "User not found")

    try:
        cur.execute(
            "INSERT INTO submissions (telegram_id,submission_type,email,password,recovery_email,secret_key_2fa,status) "
            "VALUES (%s,%s,%s,%s,%s,%s,'pending')",
            (sub.telegram_id, sub.submission_type, sub.email, sub.password, sub.recovery_email, sub.secret_key_2fa),
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            db.rollback()
            cur.close(); raise HTTPException(409, "This email has already been submitted")
        raise

    rate_key = "normal_rate" if sub.submission_type == "normal" else "two_fa_rate"
    cur.execute("SELECT key_value FROM bot_settings WHERE key_name=%s", (rate_key,))
    rr = cur.fetchone()
    rate = float(rr[0]) if rr else 0.0
    cur.execute("UPDATE users SET pending_balance=pending_balance+%s WHERE telegram_id=%s", (rate, sub.telegram_id))
    cur.close()
    return MessageResponse(message="Submission received successfully")


@bot_router.post("/withdraw-request", response_model=MessageResponse)
def withdraw_request(req: WithdrawalRequest, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT main_balance FROM users WHERE telegram_id=%s", (req.telegram_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "User not found")
    bal = row[0] or 0.0
    if req.amount <= 0:
        cur.close(); raise HTTPException(400, "Amount must be positive")
    if req.amount > bal:
        cur.close(); raise HTTPException(400, f"Insufficient balance. Available: ${bal:.2f}")

    cur.execute("SELECT key_value FROM bot_settings WHERE key_name='min_withdrawal'")
    min_r = cur.fetchone()
    min_wd = float(min_r[0]) if min_r else 0.0
    if req.amount < min_wd:
        cur.close(); raise HTTPException(400, f"Minimum withdrawal is ${min_wd:.2f}")

    cur.execute("UPDATE users SET main_balance=main_balance-%s WHERE telegram_id=%s", (req.amount, req.telegram_id))
    cur.execute(
        "INSERT INTO withdrawals (telegram_id,method,wallet_or_number,amount,status) "
        "VALUES (%s,%s,%s,%s,'pending')",
        (req.telegram_id, req.method, req.wallet_or_number, req.amount),
    )
    cur.close()
    return MessageResponse(message="Withdrawal request submitted")


@bot_router.get("/balance/{telegram_id}", response_model=BalanceResponse)
def get_balance(telegram_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT main_balance,pending_balance FROM users WHERE telegram_id=%s", (telegram_id,))
    r = cur.fetchone()
    cur.close()
    if not r:
        raise HTTPException(404, "User not found")
    return BalanceResponse(main_balance=r[0] or 0.0, pending_balance=r[1] or 0.0)


@bot_router.get("/user-info/{telegram_id}", response_model=UserResponse)
def get_user_info(telegram_id: int, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users WHERE telegram_id=%s", (telegram_id,),
    )
    r = cur.fetchone()
    cur.close()
    if not r:
        raise HTTPException(404, "User not found")
    return UserResponse(
        telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
        pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
        total_strikes=r[5] or 0, is_banned=bool(r[6]),
        block_until=str(r[7]) if r[7] else None, created_at=str(r[8]) if r[8] else None,
    )


# ==========================================================================
#  ADMIN ENDPOINTS  (/api/admin/*)
# ==========================================================================
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@admin_router.post("/login", response_model=TokenResponse)
def admin_login(creds: AdminLogin, db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,username,password_hash,role FROM admins WHERE username=%s", (creds.username,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(creds.password, row[2]):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(row[0]), "username": row[1], "role": row[3]})
    return TokenResponse(access_token=token)


@admin_router.get("/submissions", response_model=list[SubmissionResponse])
def list_submissions(
    type: Optional[str] = Query(None), status: Optional[str] = Query("pending"),
    admin: dict = Depends(get_current_admin), db=Depends(get_db),
):
    q = ("SELECT id,telegram_id,submission_type,email,password,recovery_email,"
         "secret_key_2fa,status,submitted_at FROM submissions WHERE 1=1")
    p: list = []
    if type:
        q += " AND submission_type=%s"; p.append(type)
    if status and status.lower() != "all":
        q += " AND status=%s"; p.append(status)
    q += " ORDER BY submitted_at DESC"

    cur = db.cursor()
    cur.execute(q, p)
    rows = cur.fetchall()
    cur.close()
    return [
        SubmissionResponse(id=r[0], telegram_id=r[1], submission_type=r[2], email=r[3],
                           password=r[4], recovery_email=r[5], secret_key_2fa=r[6],
                           status=r[7], submitted_at=str(r[8]) if r[8] else None)
        for r in rows
    ]


@admin_router.post("/submissions/{sid}/approve", response_model=MessageResponse)
def approve_submission(sid: int, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,telegram_id,submission_type,status FROM submissions WHERE id=%s", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "Submission not found")
    if row[3] != "pending":
        cur.close(); raise HTTPException(400, f"Already {row[3]}")
    tid, stype = row[1], row[2]

    rk = "normal_rate" if stype == "normal" else "two_fa_rate"
    cur.execute("SELECT key_value FROM bot_settings WHERE key_name=%s", (rk,))
    rr = cur.fetchone()
    rate = float(rr[0]) if rr else 0.0

    cur.execute("UPDATE submissions SET status='approved' WHERE id=%s", (sid,))
    cur.execute(
        "UPDATE users SET main_balance=main_balance+%s, "
        "pending_balance=CASE WHEN pending_balance>=%s THEN pending_balance-%s ELSE 0 END, "
        "total_completed_gmails=total_completed_gmails+1 WHERE telegram_id=%s",
        (rate, rate, rate, tid),
    )
    cur.close()
    return MessageResponse(message=f"Submission {sid} approved")


@admin_router.post("/submissions/{sid}/reject", response_model=MessageResponse)
def reject_submission(sid: int, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,telegram_id,submission_type,status FROM submissions WHERE id=%s", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "Submission not found")
    if row[3] != "pending":
        cur.close(); raise HTTPException(400, f"Already {row[3]}")
    tid, stype = row[1], row[2]

    rk = "normal_rate" if stype == "normal" else "two_fa_rate"
    cur.execute("SELECT key_value FROM bot_settings WHERE key_name=%s", (rk,))
    rr = cur.fetchone()
    rate = float(rr[0]) if rr else 0.0

    cur.execute("UPDATE submissions SET status='rejected' WHERE id=%s", (sid,))
    cur.execute(
        "UPDATE users SET total_strikes=total_strikes+1, "
        "pending_balance=CASE WHEN pending_balance>=%s THEN pending_balance-%s ELSE 0 END WHERE telegram_id=%s",
        (rate, rate, tid),
    )

    cur.execute("SELECT total_strikes FROM users WHERE telegram_id=%s", (tid,))
    new_strikes = cur.fetchone()[0]
    if new_strikes % 3 == 0:
        block_until = (datetime.now(timezone.utc) + timedelta(hours=24))
        cur.execute("UPDATE users SET block_until=%s WHERE telegram_id=%s", (block_until, tid))
    cur.close()
    return MessageResponse(message=f"Submission {sid} rejected. Strikes: {new_strikes}")


@admin_router.get("/withdrawals", response_model=list[WithdrawalResponse])
def list_withdrawals(status: Optional[str] = Query("pending"),
                     admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    q = "SELECT id,telegram_id,method,wallet_or_number,amount,status,requested_at FROM withdrawals"
    p: list = []
    if status and status.lower() != "all":
        q += " WHERE status=%s"; p.append(status)
    q += " ORDER BY requested_at DESC"
    cur = db.cursor()
    cur.execute(q, p)
    rows = cur.fetchall()
    cur.close()
    return [WithdrawalResponse(id=r[0], telegram_id=r[1], method=r[2], wallet_or_number=r[3],
                               amount=r[4], status=r[5], requested_at=str(r[6]) if r[6] else None)
            for r in rows]


@admin_router.post("/withdrawals/{wid}/approve", response_model=MessageResponse)
def approve_withdrawal(wid: int, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,status FROM withdrawals WHERE id=%s", (wid,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "Not found")
    if row[1] != "pending":
        cur.close(); raise HTTPException(400, f"Already {row[1]}")
    cur.execute("UPDATE withdrawals SET status='approved' WHERE id=%s", (wid,))
    cur.close()
    return MessageResponse(message=f"Withdrawal {wid} approved")


@admin_router.post("/withdrawals/{wid}/reject", response_model=MessageResponse)
def reject_withdrawal(wid: int, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,telegram_id,amount,status FROM withdrawals WHERE id=%s", (wid,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise HTTPException(404, "Not found")
    if row[3] != "pending":
        cur.close(); raise HTTPException(400, f"Already {row[3]}")
    cur.execute("UPDATE withdrawals SET status='rejected' WHERE id=%s", (wid,))
    cur.execute("UPDATE users SET main_balance=main_balance+%s WHERE telegram_id=%s", (row[2], row[1]))
    cur.close()
    return MessageResponse(message=f"Withdrawal {wid} rejected. ${row[2]:.2f} refunded.")


@admin_router.get("/users", response_model=list[UserResponse])
def list_users(admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users ORDER BY created_at DESC"
    )
    rows = cur.fetchall()
    cur.close()
    return [UserResponse(telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
                         pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
                         total_strikes=r[5] or 0, is_banned=bool(r[6]),
                         block_until=str(r[7]) if r[7] else None,
                         created_at=str(r[8]) if r[8] else None) for r in rows]


@admin_router.post("/users/{tid}/ban", response_model=MessageResponse)
def ban_user(tid: int, action: UserBanAction, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT 1 FROM users WHERE telegram_id=%s", (tid,))
    if not cur.fetchone():
        cur.close(); raise HTTPException(404, "User not found")
    cur.execute("UPDATE users SET is_banned=%s WHERE telegram_id=%s", (action.ban, tid))
    cur.close()
    return MessageResponse(message=f"User {tid} {'banned' if action.ban else 'unbanned'}")


# ── Recovery Emails (replaces Gmail Pool) ────────────────────────

@admin_router.get("/recovery-emails", response_model=list[RecoveryEmailResponse])
def list_recovery_emails(assigned: Optional[bool] = Query(None),
                         admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    q = "SELECT id, email, is_assigned FROM recovery_emails"
    p: list = []
    if assigned is not None:
        q += " WHERE is_assigned=%s"; p.append(assigned)
    q += " ORDER BY id DESC"
    cur = db.cursor()
    cur.execute(q, p)
    rows = cur.fetchall()
    cur.close()
    return [RecoveryEmailResponse(id=r[0], email=r[1], is_assigned=bool(r[2]))
            for r in rows]


@admin_router.post("/recovery-emails/upload", response_model=MessageResponse)
def upload_recovery_emails(bulk: RecoveryEmailBulkUpload,
                           admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    added = skipped = 0
    for e in bulk.entries:
        try:
            cur.execute("INSERT INTO recovery_emails (email) VALUES (%s)", (e.email,))
            db.commit()
            added += 1
        except Exception as ex:
            db.rollback()
            if "unique" in str(ex).lower() or "duplicate" in str(ex).lower():
                skipped += 1
            else:
                raise
    cur.close()
    return MessageResponse(message=f"Added {added}, skipped {skipped} duplicate(s)")


@admin_router.post("/export")
def export_submissions(req: ExportRequest, admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute(
        "SELECT id,telegram_id,submission_type,email,password,recovery_email,secret_key_2fa,submitted_at "
        "FROM submissions WHERE status='approved' AND submission_type=%s ORDER BY submitted_at ASC",
        (req.submission_type,),
    )
    rows = cur.fetchall()
    cur.close()
    if not rows:
        raise HTTPException(404, "No approved submissions found")

    out = io.StringIO()
    w = csv.writer(out)
    if req.submission_type == "2fa":
        w.writerow(["id", "telegram_id", "email", "password", "recovery_email", "secret_key_2fa", "submitted_at"])
        for r in rows: w.writerow([r[0], r[1], r[3], r[4], r[5], r[6], r[7]])
    else:
        w.writerow(["id", "telegram_id", "email", "password", "recovery_email", "submitted_at"])
        for r in rows: w.writerow([r[0], r[1], r[3], r[4], r[5], r[7]])

    out.seek(0)
    fn = f"submissions_{req.submission_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={fn}"})


@admin_router.get("/dashboard-stats", response_model=DashboardStats)
def dashboard_stats(admin: dict = Depends(get_current_admin), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'")
    pending_submissions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending_withdrawals = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM recovery_emails")
    recovery_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM recovery_emails WHERE is_assigned=FALSE")
    recovery_available = cur.fetchone()[0]
    cur.close()
    return DashboardStats(
        total_users=total_users,
        pending_submissions=pending_submissions,
        pending_withdrawals=pending_withdrawals,
        recovery_total=recovery_total,
        recovery_available=recovery_available,
    )


# ==========================================================================
#  OWNER ENDPOINTS  (/api/owner/*)
# ==========================================================================
owner_router = APIRouter(prefix="/api/owner", tags=["owner"])


@owner_router.post("/settings", response_model=MessageResponse)
def update_settings(update: BotSettingsBulkUpdate, admin: dict = Depends(require_owner), db=Depends(get_db)):
    cur = db.cursor()
    for s in update.settings:
        cur.execute(
            "INSERT INTO bot_settings (key_name,key_value) VALUES (%s,%s) "
            "ON CONFLICT(key_name) DO UPDATE SET key_value=EXCLUDED.key_value",
            (s.key_name, s.key_value),
        )
    cur.close()
    return MessageResponse(message=f"Updated {len(update.settings)} setting(s)")


@owner_router.post("/balance-adjust", response_model=MessageResponse)
def adjust_balance(adj: BalanceAdjustment, admin: dict = Depends(require_owner), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT password_hash FROM admins WHERE role='owner' LIMIT 1")
    owner_row = cur.fetchone()
    if not owner_row or not verify_password(adj.owner_password, owner_row[0]):
        cur.close(); raise HTTPException(403, "Invalid owner password")
    cur.execute("SELECT main_balance FROM users WHERE telegram_id=%s", (adj.telegram_id,))
    user_row = cur.fetchone()
    if not user_row:
        cur.close(); raise HTTPException(404, "User not found")
    new_bal = (user_row[0] or 0.0) + adj.amount
    if new_bal < 0:
        cur.close(); raise HTTPException(400, "Resulting balance would be negative")
    cur.execute("UPDATE users SET main_balance=%s WHERE telegram_id=%s", (new_bal, adj.telegram_id))
    cur.close()
    return MessageResponse(message=f"Balance adjusted by {adj.amount:+.2f}. New: ${new_bal:.2f}")


@owner_router.post("/create-admin", response_model=AdminResponse)
def create_admin(na: AdminCreate, admin: dict = Depends(require_owner), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT 1 FROM admins WHERE username=%s", (na.username,))
    if cur.fetchone():
        cur.close(); raise HTTPException(409, "Username already exists")
    cur.execute("INSERT INTO admins (username,password_hash,role) VALUES (%s,%s,%s)",
                (na.username, hash_password(na.password), na.role))
    cur.execute("SELECT id,username,role FROM admins WHERE username=%s", (na.username,))
    r = cur.fetchone()
    cur.close()
    return AdminResponse(id=r[0], username=r[1], role=r[2])


@owner_router.delete("/delete-admin/{aid}", response_model=MessageResponse)
def delete_admin(aid: int, admin: dict = Depends(require_owner), db=Depends(get_db)):
    if aid == admin["id"]:
        raise HTTPException(400, "Cannot delete yourself")
    cur = db.cursor()
    cur.execute("SELECT username FROM admins WHERE id=%s", (aid,))
    r = cur.fetchone()
    if not r:
        cur.close(); raise HTTPException(404, "Admin not found")
    cur.execute("DELETE FROM admins WHERE id=%s", (aid,))
    cur.close()
    return MessageResponse(message=f"Admin '{r[0]}' deleted")


@owner_router.get("/admins", response_model=list[AdminResponse])
def list_admins(admin: dict = Depends(require_owner), db=Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id,username,role FROM admins ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    return [AdminResponse(id=r[0], username=r[1], role=r[2]) for r in rows]
