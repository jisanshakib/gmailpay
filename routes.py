"""
routes.py — All FastAPI routes in one file: bot-facing, admin, owner.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth import get_current_admin, require_owner, hash_password, verify_password, create_access_token
from db import core_db_dep, gmail_db_dep
from models import (
    AdminCreate, AdminLogin, AdminResponse, AssignTaskResponse,
    BalanceAdjustment, BalanceResponse, BotSettingsBulkUpdate,
    DashboardStats, ExportRequest, GmailPoolBulkUpload, GmailPoolResponse,
    MessageResponse, SubmissionCreate, SubmissionResponse, TokenResponse,
    UserBanAction, UserRegister, UserResponse, WithdrawalRequest,
    WithdrawalResponse,
)

# ==========================================================================
#  BOT-FACING ENDPOINTS  (/api/bot/*)
# ==========================================================================
bot_router = APIRouter(prefix="/api/bot", tags=["bot"])


@bot_router.post("/register-user", response_model=UserResponse)
def register_user(user: UserRegister, db=Depends(core_db_dep)):
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO users (telegram_id, username, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username",
        [user.telegram_id, user.username, now],
    )
    db.commit()
    r = db.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users WHERE telegram_id=?", [user.telegram_id],
    ).fetchone()
    return UserResponse(
        telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
        pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
        total_strikes=r[5] or 0, is_banned=bool(r[6]),
        block_until=r[7], created_at=r[8],
    )


@bot_router.get("/settings")
def get_bot_settings(db=Depends(core_db_dep)):
    rows = db.execute("SELECT key_name, key_value FROM bot_settings").fetchall()
    return {r[0]: r[1] for r in rows}


@bot_router.get("/assign-task/{telegram_id}", response_model=AssignTaskResponse)
def assign_task(telegram_id: int, core=Depends(core_db_dep), gmail=Depends(gmail_db_dep)):
    row = core.execute(
        "SELECT is_banned,total_strikes,block_until FROM users WHERE telegram_id=?",
        [telegram_id],
    ).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    is_banned, strikes, block_until = row

    if is_banned:
        raise HTTPException(403, "🚫 Your account has been banned.")

    if block_until:
        try:
            block_dt = datetime.fromisoformat(block_until).replace(tzinfo=timezone.utc)
        except ValueError:
            block_dt = datetime.min.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < block_dt:
            remaining = block_dt - now
            h, m = int(remaining.total_seconds() // 3600), int((remaining.total_seconds() % 3600) // 60)
            raise HTTPException(403, f"⏳ Temporarily blocked due to strikes. Unblocks in {h}h {m}m.")
        core.execute("UPDATE users SET block_until=NULL WHERE telegram_id=?", [telegram_id])
        core.commit()

    pending = gmail.execute(
        "SELECT id FROM submissions WHERE telegram_id=? AND status='pending'", [telegram_id],
    ).fetchone()
    if pending:
        raise HTTPException(409, "You already have a pending submission. Wait for review.")

    pool = gmail.execute(
        "SELECT id,email,password,recovery_email FROM gmail_pool WHERE is_assigned=0 LIMIT 1"
    ).fetchone()
    if not pool:
        raise HTTPException(404, "No available tasks right now. Try again later.")

    gmail.execute("UPDATE gmail_pool SET is_assigned=1 WHERE id=?", [pool[0]])
    gmail.commit()
    return AssignTaskResponse(email=pool[1], password=pool[2], recovery_email=pool[3])


@bot_router.post("/submit", response_model=MessageResponse)
def submit_account(sub: SubmissionCreate, core=Depends(core_db_dep), gmail=Depends(gmail_db_dep)):
    now = datetime.now(timezone.utc).isoformat()
    if sub.submission_type not in ("normal", "2fa"):
        raise HTTPException(400, "submission_type must be 'normal' or '2fa'")
    if sub.submission_type == "2fa" and not sub.secret_key_2fa:
        raise HTTPException(400, "secret_key_2fa required for 2fa submissions")

    if not core.execute("SELECT 1 FROM users WHERE telegram_id=?", [sub.telegram_id]).fetchone():
        raise HTTPException(404, "User not found")

    try:
        gmail.execute(
            "INSERT INTO submissions (telegram_id,submission_type,email,password,secret_key_2fa,status,submitted_at) "
            "VALUES (?,?,?,?,?,'pending',?)",
            [sub.telegram_id, sub.submission_type, sub.email, sub.password, sub.secret_key_2fa, now],
        )
        gmail.commit()
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(409, "This email has already been submitted")
        raise

    rate_key = "normal_rate" if sub.submission_type == "normal" else "two_fa_rate"
    rr = core.execute("SELECT key_value FROM bot_settings WHERE key_name=?", [rate_key]).fetchone()
    rate = float(rr[0]) if rr else 0.0
    core.execute("UPDATE users SET pending_balance=pending_balance+? WHERE telegram_id=?", [rate, sub.telegram_id])
    core.commit()
    return MessageResponse(message="Submission received successfully")


@bot_router.post("/withdraw-request", response_model=MessageResponse)
def withdraw_request(req: WithdrawalRequest, db=Depends(core_db_dep)):
    now = datetime.now(timezone.utc).isoformat()
    row = db.execute("SELECT main_balance FROM users WHERE telegram_id=?", [req.telegram_id]).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    bal = row[0] or 0.0
    if req.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    if req.amount > bal:
        raise HTTPException(400, f"Insufficient balance. Available: ${bal:.2f}")

    min_r = db.execute("SELECT key_value FROM bot_settings WHERE key_name='min_withdrawal'").fetchone()
    min_wd = float(min_r[0]) if min_r else 0.0
    if req.amount < min_wd:
        raise HTTPException(400, f"Minimum withdrawal is ${min_wd:.2f}")

    db.execute("UPDATE users SET main_balance=main_balance-? WHERE telegram_id=?", [req.amount, req.telegram_id])
    db.execute(
        "INSERT INTO withdrawals (telegram_id,method,wallet_or_number,amount,status,requested_at) "
        "VALUES (?,?,?,?,'pending',?)",
        [req.telegram_id, req.method, req.wallet_or_number, req.amount, now],
    )
    db.commit()
    return MessageResponse(message="Withdrawal request submitted")


@bot_router.get("/balance/{telegram_id}", response_model=BalanceResponse)
def get_balance(telegram_id: int, db=Depends(core_db_dep)):
    r = db.execute("SELECT main_balance,pending_balance FROM users WHERE telegram_id=?", [telegram_id]).fetchone()
    if not r:
        raise HTTPException(404, "User not found")
    return BalanceResponse(main_balance=r[0] or 0.0, pending_balance=r[1] or 0.0)


@bot_router.get("/user-info/{telegram_id}", response_model=UserResponse)
def get_user_info(telegram_id: int, db=Depends(core_db_dep)):
    r = db.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users WHERE telegram_id=?", [telegram_id],
    ).fetchone()
    if not r:
        raise HTTPException(404, "User not found")
    return UserResponse(
        telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
        pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
        total_strikes=r[5] or 0, is_banned=bool(r[6]),
        block_until=r[7], created_at=r[8],
    )


# ==========================================================================
#  ADMIN ENDPOINTS  (/api/admin/*)
# ==========================================================================
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@admin_router.post("/login", response_model=TokenResponse)
def admin_login(creds: AdminLogin, db=Depends(core_db_dep)):
    row = db.execute("SELECT id,username,password_hash,role FROM admins WHERE username=?", [creds.username]).fetchone()
    if not row:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(creds.password, row[2]):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(row[0]), "username": row[1], "role": row[3]})
    return TokenResponse(access_token=token)


@admin_router.get("/submissions", response_model=list[SubmissionResponse])
def list_submissions(
    type: Optional[str] = Query(None), status: Optional[str] = Query("pending"),
    admin: dict = Depends(get_current_admin), gmail=Depends(gmail_db_dep),
):
    q = "SELECT id,telegram_id,submission_type,email,password,secret_key_2fa,status,submitted_at FROM submissions WHERE 1=1"
    p: list = []
    if type:
        q += " AND submission_type=?"; p.append(type)
    if status and status.lower() != "all":
        q += " AND status=?"; p.append(status)
    q += " ORDER BY submitted_at DESC"
    return [
        SubmissionResponse(id=r[0], telegram_id=r[1], submission_type=r[2], email=r[3],
                           password=r[4], secret_key_2fa=r[5], status=r[6], submitted_at=r[7])
        for r in gmail.execute(q, p).fetchall()
    ]


@admin_router.post("/submissions/{sid}/approve", response_model=MessageResponse)
def approve_submission(sid: int, admin: dict = Depends(get_current_admin),
                       core=Depends(core_db_dep), gmail=Depends(gmail_db_dep)):
    row = gmail.execute("SELECT id,telegram_id,submission_type,status FROM submissions WHERE id=?", [sid]).fetchone()
    if not row: raise HTTPException(404, "Submission not found")
    if row[3] != "pending": raise HTTPException(400, f"Already {row[3]}")
    tid, stype = row[1], row[2]

    rk = "normal_rate" if stype == "normal" else "two_fa_rate"
    rr = core.execute("SELECT key_value FROM bot_settings WHERE key_name=?", [rk]).fetchone()
    rate = float(rr[0]) if rr else 0.0

    gmail.execute("UPDATE submissions SET status='approved' WHERE id=?", [sid]); gmail.commit()
    core.execute(
        "UPDATE users SET main_balance=main_balance+?, "
        "pending_balance=CASE WHEN pending_balance>=? THEN pending_balance-? ELSE 0 END, "
        "total_completed_gmails=total_completed_gmails+1 WHERE telegram_id=?",
        [rate, rate, rate, tid],
    ); core.commit()
    return MessageResponse(message=f"Submission {sid} approved")


@admin_router.post("/submissions/{sid}/reject", response_model=MessageResponse)
def reject_submission(sid: int, admin: dict = Depends(get_current_admin),
                      core=Depends(core_db_dep), gmail=Depends(gmail_db_dep)):
    row = gmail.execute("SELECT id,telegram_id,submission_type,status FROM submissions WHERE id=?", [sid]).fetchone()
    if not row: raise HTTPException(404, "Submission not found")
    if row[3] != "pending": raise HTTPException(400, f"Already {row[3]}")
    tid, stype = row[1], row[2]

    rk = "normal_rate" if stype == "normal" else "two_fa_rate"
    rr = core.execute("SELECT key_value FROM bot_settings WHERE key_name=?", [rk]).fetchone()
    rate = float(rr[0]) if rr else 0.0

    gmail.execute("UPDATE submissions SET status='rejected' WHERE id=?", [sid]); gmail.commit()
    core.execute(
        "UPDATE users SET total_strikes=total_strikes+1, "
        "pending_balance=CASE WHEN pending_balance>=? THEN pending_balance-? ELSE 0 END WHERE telegram_id=?",
        [rate, rate, tid],
    ); core.commit()

    new_strikes = core.execute("SELECT total_strikes FROM users WHERE telegram_id=?", [tid]).fetchone()[0]
    if new_strikes % 3 == 0:
        block_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        core.execute("UPDATE users SET block_until=? WHERE telegram_id=?", [block_until, tid]); core.commit()
    return MessageResponse(message=f"Submission {sid} rejected. Strikes: {new_strikes}")


@admin_router.get("/withdrawals", response_model=list[WithdrawalResponse])
def list_withdrawals(status: Optional[str] = Query("pending"),
                     admin: dict = Depends(get_current_admin), db=Depends(core_db_dep)):
    q = "SELECT id,telegram_id,method,wallet_or_number,amount,status,requested_at FROM withdrawals"
    p: list = []
    if status and status.lower() != "all":
        q += " WHERE status=?"; p.append(status)
    q += " ORDER BY requested_at DESC"
    return [WithdrawalResponse(id=r[0], telegram_id=r[1], method=r[2], wallet_or_number=r[3],
                               amount=r[4], status=r[5], requested_at=r[6])
            for r in db.execute(q, p).fetchall()]


@admin_router.post("/withdrawals/{wid}/approve", response_model=MessageResponse)
def approve_withdrawal(wid: int, admin: dict = Depends(get_current_admin), db=Depends(core_db_dep)):
    row = db.execute("SELECT id,status FROM withdrawals WHERE id=?", [wid]).fetchone()
    if not row: raise HTTPException(404, "Not found")
    if row[1] != "pending": raise HTTPException(400, f"Already {row[1]}")
    db.execute("UPDATE withdrawals SET status='approved' WHERE id=?", [wid]); db.commit()
    return MessageResponse(message=f"Withdrawal {wid} approved")


@admin_router.post("/withdrawals/{wid}/reject", response_model=MessageResponse)
def reject_withdrawal(wid: int, admin: dict = Depends(get_current_admin), db=Depends(core_db_dep)):
    row = db.execute("SELECT id,telegram_id,amount,status FROM withdrawals WHERE id=?", [wid]).fetchone()
    if not row: raise HTTPException(404, "Not found")
    if row[3] != "pending": raise HTTPException(400, f"Already {row[3]}")
    db.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", [wid])
    db.execute("UPDATE users SET main_balance=main_balance+? WHERE telegram_id=?", [row[2], row[1]])
    db.commit()
    return MessageResponse(message=f"Withdrawal {wid} rejected. ${row[2]:.2f} refunded.")


@admin_router.get("/users", response_model=list[UserResponse])
def list_users(admin: dict = Depends(get_current_admin), db=Depends(core_db_dep)):
    rows = db.execute(
        "SELECT telegram_id,username,main_balance,pending_balance,"
        "total_completed_gmails,total_strikes,is_banned,block_until,created_at "
        "FROM users ORDER BY created_at DESC"
    ).fetchall()
    return [UserResponse(telegram_id=r[0], username=r[1], main_balance=r[2] or 0.0,
                         pending_balance=r[3] or 0.0, total_completed_gmails=r[4] or 0,
                         total_strikes=r[5] or 0, is_banned=bool(r[6]),
                         block_until=r[7], created_at=r[8]) for r in rows]


@admin_router.post("/users/{tid}/ban", response_model=MessageResponse)
def ban_user(tid: int, action: UserBanAction, admin: dict = Depends(get_current_admin), db=Depends(core_db_dep)):
    if not db.execute("SELECT 1 FROM users WHERE telegram_id=?", [tid]).fetchone():
        raise HTTPException(404, "User not found")
    db.execute("UPDATE users SET is_banned=? WHERE telegram_id=?", [1 if action.ban else 0, tid]); db.commit()
    return MessageResponse(message=f"User {tid} {'banned' if action.ban else 'unbanned'}")


@admin_router.get("/gmail-pool", response_model=list[GmailPoolResponse])
def list_gmail_pool(assigned: Optional[bool] = Query(None),
                    admin: dict = Depends(get_current_admin), db=Depends(gmail_db_dep)):
    q = "SELECT id,email,password,recovery_email,is_assigned FROM gmail_pool"
    p: list = []
    if assigned is not None:
        q += " WHERE is_assigned=?"; p.append(1 if assigned else 0)
    q += " ORDER BY id DESC"
    return [GmailPoolResponse(id=r[0], email=r[1], password=r[2],
                              recovery_email=r[3], is_assigned=bool(r[4]))
            for r in db.execute(q, p).fetchall()]


@admin_router.post("/gmail-pool/upload", response_model=MessageResponse)
def upload_gmail_pool(bulk: GmailPoolBulkUpload, admin: dict = Depends(get_current_admin), db=Depends(gmail_db_dep)):
    added = skipped = 0
    for e in bulk.entries:
        try:
            db.execute("INSERT INTO gmail_pool (email,password,recovery_email) VALUES (?,?,?)",
                       [e.email, e.password, e.recovery_email])
            added += 1
        except Exception as ex:
            if "UNIQUE" in str(ex).upper(): skipped += 1
            else: raise
    db.commit()
    return MessageResponse(message=f"Added {added}, skipped {skipped} duplicate(s)")


@admin_router.post("/export")
def export_submissions(req: ExportRequest, admin: dict = Depends(get_current_admin), gmail=Depends(gmail_db_dep)):
    rows = gmail.execute(
        "SELECT id,telegram_id,submission_type,email,password,secret_key_2fa,submitted_at "
        "FROM submissions WHERE status='approved' AND submission_type=? ORDER BY submitted_at ASC",
        [req.submission_type],
    ).fetchall()
    if not rows: raise HTTPException(404, "No approved submissions found")

    out = io.StringIO()
    w = csv.writer(out)
    if req.submission_type == "2fa":
        w.writerow(["id", "telegram_id", "email", "password", "secret_key_2fa", "submitted_at"])
        for r in rows: w.writerow([r[0], r[1], r[3], r[4], r[5], r[6]])
    else:
        w.writerow(["id", "telegram_id", "email", "password", "submitted_at"])
        for r in rows: w.writerow([r[0], r[1], r[3], r[4], r[6]])

    out.seek(0)
    fn = f"submissions_{req.submission_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={fn}"})


@admin_router.get("/dashboard-stats", response_model=DashboardStats)
def dashboard_stats(admin: dict = Depends(get_current_admin),
                    core=Depends(core_db_dep), gmail=Depends(gmail_db_dep)):
    return DashboardStats(
        total_users=core.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        pending_submissions=gmail.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'").fetchone()[0],
        pending_withdrawals=core.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
        pool_size=gmail.execute("SELECT COUNT(*) FROM gmail_pool").fetchone()[0],
        pool_available=gmail.execute("SELECT COUNT(*) FROM gmail_pool WHERE is_assigned=0").fetchone()[0],
    )


# ==========================================================================
#  OWNER ENDPOINTS  (/api/owner/*)
# ==========================================================================
owner_router = APIRouter(prefix="/api/owner", tags=["owner"])


@owner_router.post("/settings", response_model=MessageResponse)
def update_settings(update: BotSettingsBulkUpdate, admin: dict = Depends(require_owner), db=Depends(core_db_dep)):
    for s in update.settings:
        db.execute("INSERT INTO bot_settings (key_name,key_value) VALUES (?,?) "
                   "ON CONFLICT(key_name) DO UPDATE SET key_value=excluded.key_value",
                   [s.key_name, s.key_value])
    db.commit()
    return MessageResponse(message=f"Updated {len(update.settings)} setting(s)")


@owner_router.post("/balance-adjust", response_model=MessageResponse)
def adjust_balance(adj: BalanceAdjustment, admin: dict = Depends(require_owner), db=Depends(core_db_dep)):
    owner_row = db.execute("SELECT password_hash FROM admins WHERE role='owner' LIMIT 1").fetchone()
    if not owner_row or not verify_password(adj.owner_password, owner_row[0]):
        raise HTTPException(403, "Invalid owner password")
    user_row = db.execute("SELECT main_balance FROM users WHERE telegram_id=?", [adj.telegram_id]).fetchone()
    if not user_row: raise HTTPException(404, "User not found")
    new_bal = (user_row[0] or 0.0) + adj.amount
    if new_bal < 0: raise HTTPException(400, "Resulting balance would be negative")
    db.execute("UPDATE users SET main_balance=? WHERE telegram_id=?", [new_bal, adj.telegram_id]); db.commit()
    return MessageResponse(message=f"Balance adjusted by {adj.amount:+.2f}. New: ${new_bal:.2f}")


@owner_router.post("/create-admin", response_model=AdminResponse)
def create_admin(na: AdminCreate, admin: dict = Depends(require_owner), db=Depends(core_db_dep)):
    if db.execute("SELECT 1 FROM admins WHERE username=?", [na.username]).fetchone():
        raise HTTPException(409, "Username already exists")
    db.execute("INSERT INTO admins (username,password_hash,role) VALUES (?,?,?)",
               [na.username, hash_password(na.password), na.role]); db.commit()
    r = db.execute("SELECT id,username,role FROM admins WHERE username=?", [na.username]).fetchone()
    return AdminResponse(id=r[0], username=r[1], role=r[2])


@owner_router.delete("/delete-admin/{aid}", response_model=MessageResponse)
def delete_admin(aid: int, admin: dict = Depends(require_owner), db=Depends(core_db_dep)):
    if aid == admin["id"]: raise HTTPException(400, "Cannot delete yourself")
    r = db.execute("SELECT username FROM admins WHERE id=?", [aid]).fetchone()
    if not r: raise HTTPException(404, "Admin not found")
    db.execute("DELETE FROM admins WHERE id=?", [aid]); db.commit()
    return MessageResponse(message=f"Admin '{r[0]}' deleted")


@owner_router.get("/admins", response_model=list[AdminResponse])
def list_admins(admin: dict = Depends(require_owner), db=Depends(core_db_dep)):
    return [AdminResponse(id=r[0], username=r[1], role=r[2])
            for r in db.execute("SELECT id,username,role FROM admins ORDER BY id").fetchall()]
