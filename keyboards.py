"""
keyboards.py — Telegram inline and reply keyboards.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Get Task"), KeyboardButton(text="💰 Balance")],
            [KeyboardButton(text="📤 Withdraw"), KeyboardButton(text="👤 Profile")],
            [KeyboardButton(text="📢 Channel"), KeyboardButton(text="ℹ️ Help")],
        ],
        resize_keyboard=True, is_persistent=True,
    )

def submission_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Normal", callback_data="submit_type:normal"),
         InlineKeyboardButton(text="🔐 2FA", callback_data="submit_type:2fa")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])

def withdrawal_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Binance Pay", callback_data="wd_method:binance_pay"),
         InlineKeyboardButton(text="🪙 BSC USDT", callback_data="wd_method:bsc_usdt")],
        [InlineKeyboardButton(text="📱 bKash", callback_data="wd_method:bkash"),
         InlineKeyboardButton(text="📱 Nagad", callback_data="wd_method:nagad")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])

def confirm_keyboard(prefix: str = "confirm") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data=f"{prefix}:yes"),
         InlineKeyboardButton(text="✏️ Edit", callback_data=f"{prefix}:edit")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])

def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Back to Menu", callback_data="back_to_menu")],
    ])
