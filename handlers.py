"""
handlers.py — All Telegram bot handlers: /start, tasks, balance, profile, withdrawals.
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, URLInputFile

from bot_client import api, APIError
from keyboards import (
    main_menu_keyboard, submission_type_keyboard, withdrawal_method_keyboard,
    confirm_keyboard, cancel_keyboard, back_to_menu_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="handlers")


# ==========================================================================
#  FSM STATES
# ==========================================================================
class SubmissionFSM(StatesGroup):
    choosing_type = State()
    waiting_email = State()
    waiting_password = State()
    waiting_2fa_key = State()
    confirming = State()

class WithdrawalFSM(StatesGroup):
    choosing_method = State()
    waiting_address = State()
    waiting_amount = State()
    confirming = State()

_METHOD_LABELS = {
    "binance_pay": "💳 Binance Pay", "bsc_usdt": "🪙 BSC USDT",
    "bkash": "📱 bKash", "nagad": "📱 Nagad",
}


# ==========================================================================
#  /start & /help
# ==========================================================================
@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id
    username = message.from_user.username
    try:
        await api.register_user(tg_id, username or "")
    except Exception:
        pass
    try:
        s = await api.get_settings()
    except Exception:
        s = {}

    desc = s.get("bot_description", "Welcome! Complete Gmail tasks and earn rewards. 💰")
    banner = s.get("banner_image_url", "")
    channel = s.get("news_channel", "")
    lines = [f"<b>👋 Welcome to Gmail Bot!</b>\n", desc]
    if channel:
        lines.append(f"\n📢 <b>Channel:</b> <a href=\"{channel}\">Join Here</a>")
    lines.append("\nUse the menu below to get started. ⬇️")
    text = "\n".join(lines)

    if banner:
        try:
            await message.answer_photo(URLInputFile(banner), caption=text, parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Help")
async def cmd_help(message: Message):
    await message.answer(
        "<b>ℹ️ How to use this bot</b>\n\n"
        "1️⃣ <b>Get Task</b> — receive a Gmail account to complete\n"
        "2️⃣ Complete the account following the instructions\n"
        "3️⃣ <b>Submit</b> the completed account (Normal or 2FA)\n"
        "4️⃣ Wait for admin approval\n"
        "5️⃣ <b>Withdraw</b> your earnings!\n\n"
        "⚠️ <b>Rules:</b> Submit valid accounts only • 3 strikes = 24h block • Fraud = permanent ban",
        parse_mode="HTML", reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "📢 Channel")
async def btn_channel(message: Message):
    try:
        s = await api.get_settings()
        link = s.get("news_channel", "")
    except Exception:
        link = ""
    if link:
        await message.answer(f"📢 <b>Join our channel:</b>\n<a href=\"{link}\">{link}</a>", parse_mode="HTML", reply_markup=back_to_menu_keyboard())
    else:
        await message.answer("📢 No channel link configured yet.", reply_markup=back_to_menu_keyboard())


@router.callback_query(F.data == "back_to_menu")
async def cb_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer("❌ Cancelled. Returning to menu.", reply_markup=main_menu_keyboard())


# ==========================================================================
#  BALANCE & PROFILE
# ==========================================================================
@router.message(F.text == "💰 Balance")
async def btn_balance(message: Message):
    try:
        d = await api.get_balance(message.from_user.id)
    except APIError as e:
        await message.answer(f"⚠️ {e.detail}"); return
    except Exception:
        await message.answer("❌ Connection error."); return
    await message.answer(
        f"💰 <b>Your Balance</b>\n\n💵 <b>Available:</b> ${d.get('main_balance',0):.2f}\n"
        f"⏳ <b>Pending:</b> ${d.get('pending_balance',0):.2f}\n\n"
        "<i>Pending balance is credited after admin approval.</i>",
        parse_mode="HTML", reply_markup=back_to_menu_keyboard(),
    )


@router.message(F.text == "👤 Profile")
async def btn_profile(message: Message):
    try:
        d = await api.get_user_info(message.from_user.id)
    except APIError as e:
        await message.answer(f"⚠️ {e.detail}"); return
    except Exception:
        await message.answer("❌ Connection error."); return

    created = d.get("created_at", "")
    age = "N/A"
    if created:
        try:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            days = max((datetime.now(dt.tzinfo) - dt).days, 0)
            age = f"{days} day{'s' if days != 1 else ''}"
        except Exception:
            pass
    strikes = d.get("total_strikes", 0)
    block = d.get("block_until")
    strike_line = f"⚠️ Strikes: {strikes}"
    if block:
        strike_line += f"\n🚫 Blocked until: <code>{block}</code>"

    await message.answer(
        f"👤 <b>Your Profile</b>\n\n🏷 <b>Username:</b> @{d.get('username','N/A')}\n"
        f"✅ <b>Completed:</b> {d.get('total_completed_gmails',0)}\n"
        f"{strike_line}\n📅 <b>Account Age:</b> {age}",
        parse_mode="HTML", reply_markup=back_to_menu_keyboard(),
    )


# ==========================================================================
#  TASK ASSIGNMENT & SUBMISSION (FSM)
# ==========================================================================
@router.message(F.text == "📋 Get Task")
async def btn_get_task(message: Message, state: FSMContext):
    wait = await message.answer("⏳ Assigning a task...")
    try:
        result = await api.assign_task(message.from_user.id)
    except APIError as e:
        await wait.edit_text(f"⚠️ {e.detail}"); return
    except Exception:
        await wait.edit_text("❌ Connection error."); return

    await wait.edit_text(
        f"📋 <b>Task Assigned!</b>\n\n📧 <b>Email:</b> <code>{result.get('email','N/A')}</code>\n"
        f"🔑 <b>Password:</b> <code>{result.get('password','N/A')}</code>\n"
        f"🔄 <b>Recovery:</b> <code>{result.get('recovery_email','N/A')}</code>\n\n"
        "Complete this account, then choose submission type:",
        parse_mode="HTML", reply_markup=submission_type_keyboard(),
    )
    await state.update_data(assigned_email=result.get("email"), assigned_password=result.get("password"))
    await state.set_state(SubmissionFSM.choosing_type)


@router.callback_query(SubmissionFSM.choosing_type, F.data.startswith("submit_type:"))
async def cb_sub_type(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    stype = cb.data.split(":")[1]
    await state.update_data(submission_type=stype)
    await cb.message.answer("📧 Send the <b>email address</b> of the completed account:", parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmissionFSM.waiting_email)


@router.message(SubmissionFSM.waiting_email)
async def fsm_email(message: Message, state: FSMContext):
    email = (message.text or "").strip()
    if not email or "@" not in email:
        await message.answer("⚠️ Invalid email. Try again:"); return
    await state.update_data(email=email)
    await message.answer("🔑 Now send the <b>password</b>:", parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmissionFSM.waiting_password)


@router.message(SubmissionFSM.waiting_password)
async def fsm_password(message: Message, state: FSMContext):
    pw = (message.text or "").strip()
    if not pw:
        await message.answer("⚠️ Password cannot be empty."); return
    await state.update_data(password=pw)
    data = await state.get_data()
    if data.get("submission_type") == "2fa":
        await message.answer("🔐 Now send the <b>2FA secret key</b>:", parse_mode="HTML", reply_markup=cancel_keyboard())
        await state.set_state(SubmissionFSM.waiting_2fa_key)
    else:
        await _show_sub_confirm(message, state)


@router.message(SubmissionFSM.waiting_2fa_key)
async def fsm_2fa(message: Message, state: FSMContext):
    key = (message.text or "").strip()
    if not key:
        await message.answer("⚠️ 2FA key cannot be empty."); return
    await state.update_data(secret_key_2fa=key)
    await _show_sub_confirm(message, state)


async def _show_sub_confirm(message: Message, state: FSMContext):
    d = await state.get_data()
    lines = [f"📝 <b>Submission Confirmation ({d.get('submission_type','').upper()})</b>\n",
             f"📧 Email: <code>{d.get('email')}</code>",
             f"🔑 Password: <code>{d.get('password')}</code>"]
    if d.get("secret_key_2fa"):
        lines.append(f"🔐 2FA Key: <code>{d['secret_key_2fa']}</code>")
    lines.append("\nPlease confirm:")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=confirm_keyboard("sub_confirm"))
    await state.set_state(SubmissionFSM.confirming)


@router.callback_query(SubmissionFSM.confirming, F.data == "sub_confirm:yes")
async def cb_confirm_sub(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d = await state.get_data()
    await cb.message.edit_text("⏳ Submitting...")
    try:
        await api.submit_account(cb.from_user.id, d["submission_type"], d["email"], d["password"], d.get("secret_key_2fa"))
    except APIError as e:
        await cb.message.edit_text(f"❌ {e.detail}"); await state.clear(); return
    except Exception:
        await cb.message.edit_text("❌ Connection error."); await state.clear(); return
    await cb.message.edit_text("✅ <b>Submitted successfully!</b>\nPending admin review. 🎉", parse_mode="HTML")
    await cb.message.answer("🏠 Returning to menu.", reply_markup=main_menu_keyboard())
    await state.clear()


@router.callback_query(SubmissionFSM.confirming, F.data == "sub_confirm:edit")
async def cb_edit_sub(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("📧 Re-enter the <b>email address</b>:", parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(SubmissionFSM.waiting_email)


# ==========================================================================
#  WITHDRAWAL FLOW (FSM)
# ==========================================================================
@router.message(F.text == "📤 Withdraw")
async def btn_withdraw(message: Message, state: FSMContext):
    try:
        bal = await api.get_balance(message.from_user.id)
    except Exception:
        await message.answer("❌ Connection error."); return
    mb = float(bal.get("main_balance", 0))
    if mb <= 0:
        await message.answer("💰 Your balance is <b>$0.00</b>.\nComplete tasks first!", parse_mode="HTML", reply_markup=back_to_menu_keyboard()); return
    await state.update_data(available_balance=mb)
    await message.answer(f"📤 <b>Withdrawal</b>\n\n💵 Available: <b>${mb:,.2f}</b>\n\nChoose method:",
                         parse_mode="HTML", reply_markup=withdrawal_method_keyboard())
    await state.set_state(WithdrawalFSM.choosing_method)


@router.callback_query(WithdrawalFSM.choosing_method, F.data.startswith("wd_method:"))
async def cb_wd_method(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    method = cb.data.split(":")[1]
    await state.update_data(method=method)
    prompt = "📱 Send your <b>phone number</b>:" if method in ("bkash", "nagad") else "🔗 Send your <b>wallet address</b>:"
    await cb.message.answer(prompt, parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(WithdrawalFSM.waiting_address)


@router.message(WithdrawalFSM.waiting_address)
async def fsm_addr(message: Message, state: FSMContext):
    addr = (message.text or "").strip()
    if not addr:
        await message.answer("⚠️ Enter a valid address/number:"); return
    await state.update_data(wallet_or_number=addr)
    d = await state.get_data()
    await message.answer(f"💲 Enter amount (max <b>${d['available_balance']:,.2f}</b>):", parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(WithdrawalFSM.waiting_amount)


@router.message(WithdrawalFSM.waiting_amount)
async def fsm_amount(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace("$", "").replace(",", "")
    try:
        amount = float(raw); assert amount > 0
    except (ValueError, AssertionError):
        await message.answer("⚠️ Enter a valid positive number:"); return
    d = await state.get_data()
    if amount > d["available_balance"]:
        await message.answer(f"⚠️ Exceeds balance (${d['available_balance']:,.2f})."); return
    await state.update_data(amount=amount)
    ml = _METHOD_LABELS.get(d["method"], d["method"])
    await message.answer(
        f"📤 <b>Withdrawal Summary</b>\n\n📌 Method: {ml}\n📍 Address: <code>{d['wallet_or_number']}</code>\n"
        f"💲 Amount: <b>${amount:,.2f}</b>\n\nPlease confirm:",
        parse_mode="HTML", reply_markup=confirm_keyboard("wd_confirm"),
    )
    await state.set_state(WithdrawalFSM.confirming)


@router.callback_query(WithdrawalFSM.confirming, F.data == "wd_confirm:yes")
async def cb_confirm_wd(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d = await state.get_data()
    await cb.message.edit_text("⏳ Processing withdrawal...")
    try:
        await api.request_withdrawal(cb.from_user.id, d["method"], d["wallet_or_number"], d["amount"])
    except APIError as e:
        await cb.message.edit_text(f"❌ {e.detail}"); await state.clear(); return
    except Exception:
        await cb.message.edit_text("❌ Connection error."); await state.clear(); return
    await cb.message.edit_text(f"✅ <b>Withdrawal submitted!</b>\n💲 Amount: <b>${d['amount']:,.2f}</b>\nProcessing... ⏳", parse_mode="HTML")
    await cb.message.answer("🏠 Returning to menu.", reply_markup=main_menu_keyboard())
    await state.clear()


@router.callback_query(WithdrawalFSM.confirming, F.data == "wd_confirm:edit")
async def cb_edit_wd(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d = await state.get_data()
    await cb.message.answer(f"📤 <b>Withdrawal</b>\n\n💵 Available: <b>${d['available_balance']:,.2f}</b>\n\nChoose method:",
                            parse_mode="HTML", reply_markup=withdrawal_method_keyboard())
    await state.set_state(WithdrawalFSM.choosing_method)
