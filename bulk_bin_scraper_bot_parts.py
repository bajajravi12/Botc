#!/usr/bin/env python3
# BULK BIN SCRAPER TELEGRAM BOT v6.1 - FORMAT FIXED
# Format: CC_NUMBER|MM|YY|CVV - One per line, no wrapping

import requests
import time
import random
import re
import os
from dataclasses import dataclass
from typing import Optional, List, Dict
from functools import wraps
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ============================================
# CONFIGURATION - FROM ENVIRONMENT VARIABLES
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')
PORT = int(os.environ.get('PORT', '8080'))
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1

@dataclass
class BinInfo:
    bin: str
    bank: str
    country: str
    country_code: str
    brand: str
    type: str
    level: str
    currency: str
    source: str
    is_real: bool = False

@dataclass
class CCInfo:
    number: str
    bin: str
    month: str
    year: str
    cvv: str
    brand: str
    bank: str
    is_valid: bool

    def to_pipe_format(self):
        # EXACT FORMAT: CC_NUMBER|MM|YY|CVV
        # No spaces, no newlines inside
        return f'{self.number}|{self.month}|{self.year}|{self.cvv}'

class RamCache:
    def __init__(self):
        self.bins = {}
        self.ccs = []

    def add_bin(self, info):
        self.bins[info.bin] = info

    def get_bin(self, bin_number):
        return self.bins.get(bin_number)

    def get_related(self, bank_name):
        return [b for b in self.bins.values() if bank_name.lower() in b.bank.lower()]

    def add_ccs(self, ccs):
        self.ccs.extend(ccs)

    def get_stats(self):
        real = sum(1 for b in self.bins.values() if b.is_real)
        fake = len(self.bins) - real
        banks = {}
        for b in self.bins.values():
            if b.is_real:
                banks[b.bank] = banks.get(b.bank, 0) + 1
        return {
            'real_bins': real,
            'fake_bins': fake,
            'total_ccs': len(self.ccs),
            'banks': sorted(banks.items(), key=lambda x: x[1], reverse=True)[:10]
        }

def retry_on_failure(max_attempts=MAX_RETRIES, delay=RETRY_DELAY):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, requests.Timeout):
                    if attempt < max_attempts - 1:
                        time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

class LuhnValidator:
    @staticmethod
    def generate_valid(bin_number, length=16):
        bin_number = str(bin_number)[:6]
        remaining = length - len(bin_number) - 1
        random_digits = ''.join(str(random.randint(0, 9)) for _ in range(remaining))
        partial = bin_number + random_digits
        total = 0
        for i, d in enumerate(partial[::-1]):
            n = int(d)
            if i % 2 == 0:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        check_digit = (10 - (total % 10)) % 10
        return partial + str(check_digit)

    @staticmethod
    def validate(number):
        if not number.isdigit() or len(number) < 13:
            return False
        total = 0
        for i, d in enumerate(number[::-1]):
            n = int(d)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return total % 10 == 0

class BinValidator:
    BRAND_RANGES = {
        'VISA': [(400000, 499999)],
        'MASTERCARD': [(510000, 559999), (222100, 272099)],
        'AMEX': [(340000, 349999), (370000, 379999)],
        'DISCOVER': [(601100, 601109), (601120, 601149), (601174, 601174), (601177, 601179), (601186, 601199), (644000, 659999), (610000, 610999)],
        'JCB': [(352800, 358999)],
        'DINERS': [(300000, 305999), (309500, 309599), (360000, 369999), (380000, 399999)]
    }

    CARD_LENGTHS = {'VISA': 16, 'MASTERCARD': 16, 'AMEX': 15, 'DISCOVER': 16, 'JCB': 16, 'DINERS': 14}
    CVV_LENGTHS = {'VISA': 3, 'MASTERCARD': 3, 'AMEX': 4, 'DISCOVER': 3, 'JCB': 3, 'DINERS': 3}

    @staticmethod
    def validate_format(bin_number):
        return bool(re.match(r'^[0-9]{6}$', str(bin_number)))

    @staticmethod
    def detect_brand(bin_number):
        try:
            num = int(str(bin_number)[:6])
            for brand, ranges in BinValidator.BRAND_RANGES.items():
                for start, end in ranges:
                    if start <= num <= end:
                        return brand
            return None
        except ValueError:
            return None

    @staticmethod
    def get_card_length(brand):
        return BinValidator.CARD_LENGTHS.get(brand, 16)

    @staticmethod
    def get_cvv_length(brand):
        return BinValidator.CVV_LENGTHS.get(brand, 3)

def safe_get(data, key, default='Unknown'):
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(key, default)
    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            return data[0].get(key, default)
    return default

class BulkBinScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        self.luhn = LuhnValidator()
        self.validator = BinValidator()
        self.cache = RamCache()

    @retry_on_failure()
    def _fetch_binlist(self, bin_number):
        url = f'https://lookup.binlist.net/{bin_number}'
        r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            bank_data = data.get('bank', {})
            if isinstance(bank_data, list):
                bank_data = bank_data[0] if bank_data else {}
            bank = bank_data.get('name', '') if isinstance(bank_data, dict) else 'Unknown'
            brand = (data.get('scheme') or 'Unknown').upper()
            if bank in ('Unknown', '', None):
                defaults = {'DISCOVER': 'Discover Financial Services', 'AMEX': 'American Express', 'JCB': 'JCB Co., Ltd.', 'VISA': 'Visa Inc.', 'MASTERCARD': 'Mastercard Inc.'}
                bank = defaults.get(brand, f'{brand} ISSUER')
            country_data = data.get('country', {})
            if isinstance(country_data, list):
                country_data = country_data[0] if country_data else {}
            is_real = bank != 'Unknown' and bank != f'{brand} ISSUER'
            return BinInfo(
                bin=bin_number, bank=bank,
                country=safe_get(country_data, 'name', 'Unknown'),
                country_code=safe_get(country_data, 'alpha2', 'XX'),
                brand=brand,
                type=(data.get('type') or 'Unknown').capitalize(),
                level=data.get('brand', 'Unknown'),
                currency=safe_get(country_data, 'currency', 'Unknown'),
                source='binlist',
                is_real=is_real
            )
        return None

    @retry_on_failure()
    def _fetch_handyapi(self, bin_number):
        url = f'https://data.handyapi.com/bin/{bin_number}'
        r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('Status') == 'SUCCESS':
                issuer = data.get('Issuer', '')
                if isinstance(issuer, list):
                    issuer = issuer[0] if issuer else 'Unknown'
                bank = str(issuer) if issuer else 'Unknown'
                brand = (data.get('Scheme') or 'Unknown').upper()
                if bank in ('Unknown', '', None):
                    defaults = {'DISCOVER': 'Discover Financial Services', 'AMEX': 'American Express', 'JCB': 'JCB Co., Ltd.', 'VISA': 'Visa Inc.', 'MASTERCARD': 'Mastercard Inc.'}
                    bank = defaults.get(brand, f'{brand} ISSUER')
                country_data = data.get('Country', {})
                if isinstance(country_data, list):
                    country_data = country_data[0] if country_data else {}
                is_real = bank != 'Unknown' and bank != f'{brand} ISSUER'
                return BinInfo(
                    bin=bin_number, bank=bank,
                    country=safe_get(country_data, 'Name', 'Unknown'),
                    country_code=safe_get(country_data, 'A2', 'XX'),
                    brand=brand,
                    type=(data.get('Type') or 'Unknown').capitalize(),
                    level=data.get('CardTier', 'Unknown'),
                    currency=safe_get(country_data, 'Currency', 'Unknown'),
                    source='handyapi',
                    is_real=is_real
                )
        return None

    def verify_bin(self, bin_number):
        if not self.validator.validate_format(bin_number):
            return None
        cached = self.cache.get_bin(bin_number)
        if cached:
            return cached
        for source in [self._fetch_binlist, self._fetch_handyapi]:
            try:
                result = source(bin_number)
                if result:
                    self.cache.add_bin(result)
                    return result
            except Exception:
                continue
        return None

    def generate_valid_cc(self, bin_number, quantity=1):
        if not self.validator.validate_format(bin_number):
            return [], 'Invalid BIN format'
        bin_info = self.verify_bin(bin_number)
        if not bin_info:
            return [], f'❌ BIN {bin_number} is FAKE — No bank data found'
        if not bin_info.is_real:
            return [], f'❌ BIN {bin_number} is FAKE — Bank: {bin_info.bank}'
        brand = bin_info.brand
        length = self.validator.get_card_length(brand)
        cvv_len = self.validator.get_cvv_length(brand)
        ccs = []
        for _ in range(quantity):
            cc_num = self.luhn.generate_valid(bin_number, length)
            month = f'{random.randint(1, 12):02d}'
            year = f'{random.randint(2026, 2030)}'[2:]
            cvv = ''.join(str(random.randint(0, 9)) for _ in range(cvv_len))
            ccs.append(CCInfo(
                number=cc_num, bin=bin_number,
                month=month, year=year, cvv=cvv,
                brand=brand, bank=bin_info.bank, is_valid=True
            ))
        self.cache.add_ccs(ccs)
        return ccs, None

# ============================================
# TELEGRAM BOT HANDLERS
# ============================================
scraper = BulkBinScraper()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = '🎯 *BULK BIN SCRAPER BOT v6.1*\n\n*Commands:*\n🔍 `/verify 414720` — Check if BIN is real\n📋 `/range 400000 400100` — Scrape BIN range\n💳 `/cc 414720 10` — Generate CCs (real BIN only)\n🔥 `/mass 414720,510000,370000 5` — Mass CC gen\n📊 `/stats` — Session statistics\n\n*Rules:*\n✅ Real BIN = Bank info + CC generation\n❌ Fake BIN = Blocked\n🚀 No limit on CC generation'
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/verify 414720`', parse_mode='Markdown')
        return
    bin_num = context.args[0]
    if not re.match(r'^[0-9]{6}$', bin_num):
        await update.message.reply_text('❌ BIN must be 6 digits!')
        return
    await update.message.reply_text(f'⏳ Verifying BIN `{bin_num}`...', parse_mode='Markdown')
    result = scraper.verify_bin(bin_num)
    if not result:
        await update.message.reply_text(f'❌ BIN `{bin_num}` verification failed!', parse_mode='Markdown')
        return
    status = '✅ REAL' if result.is_real else '❌ FAKE'
    msg = f'💳 *BIN Information* [{status}]\n\n🔢 *BIN:* `{result.bin}`\n🏦 *Bank:* `{result.bank}`\n🌍 *Country:* `{result.country} ({result.country_code})`\n💎 *Brand:* `{result.brand}`\n📋 *Type:* `{result.type}`\n⭐ *Level:* `{result.level}`\n💰 *Currency:* `{result.currency}`\n📡 *Source:* `{result.source}`'
    if result.is_real:
        msg += '\n\n✅ *This is a REAL BIN — CC generation allowed!*'
    else:
        msg += '\n\n❌ *This is a FAKE BIN — CC generation blocked!*'
    await update.message.reply_text(msg, parse_mode='Markdown')

async def range_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text('❌ Usage: `/range 400000 400100`', parse_mode='Markdown')
        return
    start, end = context.args[0], context.args[1]
    if not (start.isdigit() and end.isdigit()):
        await update.message.reply_text('❌ Invalid BIN range!')
        return
    from_start, from_end = int(start), int(end)
    if from_end - from_start > 500:
        await update.message.reply_text('⚠️ Max 500 BINs per request!')
        from_end = from_start + 500
    await update.message.reply_text(f'🔄 Scraping `{from_start}` to `{from_end}`...', parse_mode='Markdown')
    results = []
    for i in range(from_start, from_end + 1):
        bin_str = str(i).zfill(6)
        result = scraper.verify_bin(bin_str)
        if result and result.is_real:
            results.append(f'✅ `{bin_str}` | 🏦 `{result.bank[:25]}` | 🌍 `{result.country[:15]}` | 💎 `{result.brand}`')
        time.sleep(1)
    if not results:
        await update.message.reply_text('❌ No real BINs found in range!')
        return
    msg = '📋 *Real BINs Found:*\n\n' + '\n'.join(results[:50])
    await update.message.reply_text(msg, parse_mode='Markdown')
    if len(results) > 50:
        msg2 = '\n'.join(results[50:])
        await update.message.reply_text(msg2, parse_mode='Markdown')

async def cc_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/cc 414720 10`', parse_mode='Markdown')
        return
    bin_num = context.args[0]
    qty = int(context.args[1]) if len(context.args) > 1 else 10
    if not re.match(r'^[0-9]{6}$', bin_num):
        await update.message.reply_text('❌ BIN must be 6 digits!')
        return
    if qty > 999999:
        await update.message.reply_text('⚠️ Max 999999 CCs per request!')
        qty = 999999
    await update.message.reply_text(f'⏳ Verifying BIN `{bin_num}`...', parse_mode='Markdown')
    bin_info = scraper.verify_bin(bin_num)
    if not bin_info:
        await update.message.reply_text(f'❌ BIN `{bin_num}` verification failed!', parse_mode='Markdown')
        return
    if not bin_info.is_real:
        await update.message.reply_text(f'🚫 *BIN `{bin_num}` is FAKE!*\n🏦 Bank: `{bin_info.bank}`\n❌ CC generation blocked!', parse_mode='Markdown')
        return
    await update.message.reply_text(f'✅ *REAL BIN confirmed!*\n🏦 `{bin_info.bank}`\n💎 `{bin_info.brand}`\n⏳ Generating {qty} CCs...', parse_mode='Markdown')
    ccs, error = scraper.generate_valid_cc(bin_num, qty)
    if error:
        await update.message.reply_text(error)
        return
    
    # FIXED: Always send as file to avoid text wrapping issues
    from io import StringIO
    lines = []
    for cc in ccs:
        lines.append(cc.to_pipe_format())
    file_content = '\n'.join(lines)
    file = StringIO(file_content)
    await update.message.reply_document(
        document=file,
        filename=f'ccs_{bin_num}.txt',
        caption=f'✅ {len(ccs)} CCs for `{bin_num}`\n💳 Format: CC|MM|YY|CVV'
    )

async def mass_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/mass 414720,510000,370000 5`', parse_mode='Markdown')
        return
    bins_str = context.args[0]
    qty = int(context.args[1]) if len(context.args) > 1 else 5
    bins_list = [b.strip() for b in bins_str.split(',') if b.strip().isdigit() and len(b.strip()) == 6]
    if not bins_list:
        await update.message.reply_text('❌ No valid BINs provided!')
        return
    if qty > 999999:
        qty = 999999
    await update.message.reply_text(f'🔥 Processing {len(bins_list)} BINs...')
    all_ccs = []
    for bin_num in bins_list:
        ccs, error = scraper.generate_valid_cc(bin_num, qty)
        if not error:
            all_ccs.extend(ccs)
    if not all_ccs:
        await update.message.reply_text('❌ No CCs generated! All BINs might be fake.')
        return
    
    # FIXED: Always send as file
    from io import StringIO
    lines = []
    for cc in all_ccs:
        lines.append(cc.to_pipe_format())
    file_content = '\n'.join(lines)
    file = StringIO(file_content)
    await update.message.reply_document(
        document=file,
        filename=f'mass_ccs_{len(all_ccs)}.txt',
        caption=f'✅ {len(all_ccs)} CCs generated from {len(bins_list)} BINs\n💳 Format: CC|MM|YY|CVV'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = scraper.cache.get_stats()
    msg = f'📊 *Session Statistics*\n\n✅ *Real BINs:* `{s["real_bins"]}`\n❌ *Fake BINs:* `{s["fake_bins"]}`\n💳 *Total CCs:* `{s["total_ccs"]}`\n\n🏦 *Top Banks:*'
    for bank, count in s['banks']:
        msg += f'\n`{bank}`: `{count}` BINs'
    await update.message.reply_text(msg, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'verify':
        await query.edit_message_text('Send: `/verify 414720`', parse_mode='Markdown')
    elif query.data == 'range':
        await query.edit_message_text('Send: `/range 400000 400100`', parse_mode='Markdown')
    elif query.data == 'cc':
        await query.edit_message_text('Send: `/cc 414720 10`', parse_mode='Markdown')

def main():
    if not BOT_TOKEN:
        print('❌ ERROR: BOT_TOKEN not set!')
        print('Set environment variable: BOT_TOKEN=your_token_here')
        return
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('verify', verify))
    application.add_handler(CommandHandler('range', range_scrape))
    application.add_handler(CommandHandler('cc', cc_gen))
    application.add_handler(CommandHandler('mass', mass_gen))
    application.add_handler(CommandHandler('stats', stats))
    application.add_handler(CallbackQueryHandler(button_callback))
    print('🤖 Bot starting...')
    if WEBHOOK_URL:
        print(f'🌐 Webhook mode: {WEBHOOK_URL}')
        application.run_webhook(listen='0.0.0.0', port=PORT, webhook_url=WEBHOOK_URL)
    else:
        print('🔄 Polling mode...')
        application.run_polling()

if __name__ == '__main__':
    main()
