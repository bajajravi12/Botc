#!/usr/bin/env python3
# BULK BIN SCRAPER BOT v7.0 - RAILWAY READY
# Format: CC_NUMBER|MM|YY|CVV - One per line, no wrapping
# Pure synchronous - optimized for Railway/Render/Heroku deploy

import requests
import time
import random
import re
import os
from dataclasses import dataclass
from typing import Optional, List, Dict
from functools import wraps
from io import BytesIO
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ============================================
# CONFIGURATION - HARDCODED
# ============================================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # 🔴 CHANGE THIS
WEBHOOK_URL = ""  # Leave empty for polling (Railway mein polling best hai)
PORT = int(os.environ.get('PORT', '8080'))
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1
MAX_CC_PER_REQUEST = 1000
MAX_RANGE_SIZE = 500
CACHE_MAX_BINS = 5000
CACHE_MAX_CCS = 10000

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
        return f'{self.number}|{self.month}|{self.year}|{self.cvv}'

class RamCache:
    def __init__(self, max_bins=5000, max_ccs=10000):
        self.bins = {}
        self.ccs = []
        self.max_bins = max_bins
        self.max_ccs = max_ccs

    def add_bin(self, info):
        if len(self.bins) >= self.max_bins:
            oldest = next(iter(self.bins))
            del self.bins[oldest]
        self.bins[info.bin] = info

    def get_bin(self, bin_number):
        return self.bins.get(bin_number)

    def get_related(self, bank_name):
        return [b for b in self.bins.values() if bank_name.lower() in b.bank.lower()]

    def add_ccs(self, ccs):
        self.ccs.extend(ccs)
        if len(self.ccs) > self.max_ccs:
            self.ccs = self.ccs[-self.max_ccs:]

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
        if not number or not number.isdigit() or len(number) < 13:
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
        'DISCOVER': [(601100, 601109), (601120, 601149), (601174, 601174), 
                     (601177, 601179), (601186, 601199), (644000, 659999), (610000, 610999)],
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
        self.cache = RamCache(max_bins=CACHE_MAX_BINS, max_ccs=CACHE_MAX_CCS)

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
                defaults = {
                    'DISCOVER': 'Discover Financial Services',
                    'AMEX': 'American Express',
                    'JCB': 'JCB Co., Ltd.',
                    'VISA': 'Visa Inc.',
                    'MASTERCARD': 'Mastercard Inc.'
                }
                bank = defaults.get(brand, f'{brand} ISSUER')
            
            country_data = data.get('country', {})
            if isinstance(country_data, list):
                country_data = country_data[0] if country_data else {}
            
            is_real = bank not in ('Unknown', f'{brand} ISSUER', '')
            
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
                    defaults = {
                        'DISCOVER': 'Discover Financial Services',
                        'AMEX': 'American Express',
                        'JCB': 'JCB Co., Ltd.',
                        'VISA': 'Visa Inc.',
                        'MASTERCARD': 'Mastercard Inc.'
                    }
                    bank = defaults.get(brand, f'{brand} ISSUER')
                
                country_data = data.get('Country', {})
                if isinstance(country_data, list):
                    country_data = countryData[0] if country_data else {}
                
                is_real = bank not in ('Unknown', f'{brand} ISSUER', '')
                
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
            return [], '❌ Invalid BIN format (must be 6 digits)'
        
        bin_info = self.verify_bin(bin_number)
        if not bin_info:
            return [], f'🚫 BIN `{bin_number}` not found in any database'
        
        if not bin_info.is_real:
            return [], f'🚫 BIN `{bin_number}` is FAKE\n🏦 Bank: `{bin_info.bank}`\n❌ CC generation blocked for fake BINs!'
        
        brand = bin_info.brand
        length = self.validator.get_card_length(brand)
        cvv_len = self.validator.get_cvv_length(brand)
        ccs = []
        
        current_year = time.localtime().tm_year
        max_year = current_year + 5
        
        for _ in range(quantity):
            cc_num = self.luhn.generate_valid(bin_number, length)
            month = f'{random.randint(1, 12):02d}'
            year = str(random.randint(current_year + 1, max_year))[2:]
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
    welcome = (
        '🌹 *BULK BIN SCRAPER BOT v7.0* 🌹\n\n'
        '*Premium Commands:*\n'
        '🔍 `/verify 414720` — Check if BIN is real\n'
        '📋 `/range 400000 400100` — Scrape BIN range\n'
        '💳 `/cc 414720 10` — Generate CCs (real BIN only)\n'
        '🔥 `/mass 414720,510000,370000 5` — Mass CC gen\n'
        '📊 `/stats` — Session statistics\n\n'
        '*Rules:*\n'
        '✅ Real BIN = Bank info + CC generation\n'
        '❌ Fake BIN = Blocked\n'
        '🚀 Max 1000 CCs per request'
    )
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/verify 414720`', parse_mode='Markdown')
        return
    
    bin_num = context.args[0]
    if not re.match(r'^[0-9]{6}$', bin_num):
        await update.message.reply_text('❌ BIN must be exactly 6 digits!')
        return
    
    await update.message.reply_text(f'⏳ Verifying BIN `{bin_num}`...', parse_mode='Markdown')
    result = scraper.verify_bin(bin_num)
    
    if not result:
        await update.message.reply_text(f'🚫 BIN `{bin_num}` not found in any database!\n\n❌ No bank data available.', parse_mode='Markdown')
        return
    
    status = '✅ REAL' if result.is_real else '❌ FAKE'
    emoji = '🟢' if result.is_real else '🔴'
    
    msg = (
        f'{emoji} *BIN Information* [{status}]\n\n'
        f'🔢 *BIN:* `{result.bin}`\n'
        f'🏦 *Bank:* `{result.bank}`\n'
        f'🌍 *Country:* `{result.country} ({result.country_code})`\n'
        f'💎 *Brand:* `{result.brand}`\n'
        f'📋 *Type:* `{result.type}`\n'
        f'⭐ *Level:* `{result.level}`\n'
        f'💰 *Currency:* `{result.currency}`\n'
        f'📡 *Source:* `{result.source}`\n\n'
    )
    
    if result.is_real:
        msg += '✅ *This is a REAL BIN — CC generation allowed!* 🌹'
    else:
        msg += '❌ *This is a FAKE BIN — CC generation blocked!*'
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def range_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text('❌ Usage: `/range 400000 400100`', parse_mode='Markdown')
        return
    
    start, end = context.args[0], context.args[1]
    if not (start.isdigit() and end.isdigit()):
        await update.message.reply_text('❌ Invalid BIN range! Must be numbers.')
        return
    
    from_start, from_end = int(start), int(end)
    if from_end < from_start:
        await update.message.reply_text('❌ End must be greater than start!')
        return
    
    if from_end - from_start > MAX_RANGE_SIZE:
        from_end = from_start + MAX_RANGE_SIZE
        await update.message.reply_text(f'⚠️ Range capped to {MAX_RANGE_SIZE} BINs!', parse_mode='Markdown')
    
    msg = await update.message.reply_text(
        f'🔄 Scraping `{from_start:06d}` to `{from_end:06d}`...\n⏳ This may take a while...', 
        parse_mode='Markdown'
    )
    
    results = []
    for i in range(from_start, from_end + 1):
        bin_str = f"{i:06d}"
        result = scraper.verify_bin(bin_str)
        if result and result.is_real:
            results.append(
                f'✅ `{bin_str}` | 🏦 `{result.bank[:25]}` | '
                f'🌍 `{result.country[:15]}` | 💎 `{result.brand}`'
            )
        time.sleep(0.5)  # Rate limit protection
    
    if not results:
        await msg.edit_text('🚫 No real BINs found in range!\n\nAll BINs in this range are fake/unregistered.', parse_mode='Markdown')
        return
    
    header = f'🌹 *Real BINs Found ({len(results)}):*\n\n'
    chunks = []
    current_chunk = header
    
    for r in results:
        if len(current_chunk) + len(r) + 2 > 4000:
            chunks.append(current_chunk)
            current_chunk = r + '\n'
        else:
            current_chunk += r + '\n'
    chunks.append(current_chunk)
    
    await msg.delete()
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode='Markdown')

async def cc_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/cc 414720 10`', parse_mode='Markdown')
        return
    
    bin_num = context.args[0]
    try:
        qty = int(context.args[1]) if len(context.args) > 1 else 10
    except ValueError:
        qty = 10
    
    qty = max(1, min(qty, MAX_CC_PER_REQUEST))
    
    if not re.match(r'^[0-9]{6}$', bin_num):
        await update.message.reply_text('❌ BIN must be exactly 6 digits!')
        return
    
    msg = await update.message.reply_text(f'⏳ Verifying BIN `{bin_num}`...', parse_mode='Markdown')
    bin_info = scraper.verify_bin(bin_num)
    
    if not bin_info:
        await msg.edit_text(f'🚫 BIN `{bin_num}` not found in any database!', parse_mode='Markdown')
        return
    
    if not bin_info.is_real:
        await msg.edit_text(
            f'🚫 *BIN `{bin_num}` is FAKE!*\n'
            f'🏦 Bank: `{bin_info.bank}`\n'
            f'❌ CC generation blocked for fake BINs!', 
            parse_mode='Markdown'
        )
        return
    
    await msg.edit_text(
        f'✅ *REAL BIN confirmed!* 🌹\n'
        f'🏦 `{bin_info.bank}`\n'
        f'💎 `{bin_info.brand}`\n'
        f'⏳ Generating {qty} CCs...', 
        parse_mode='Markdown'
    )
    
    ccs, error = scraper.generate_valid_cc(bin_num, qty)
    if error:
        await msg.edit_text(error, parse_mode='Markdown')
        return
    
    lines = [cc.to_pipe_format() for cc in ccs]
    file_content = '\n'.join(lines)
    
    # FIXED: BytesIO for Railway compatibility
    file_bytes = BytesIO(file_content.encode('utf-8'))
    file_bytes.name = f'ccs_{bin_num}.txt'
    
    await msg.delete()
    await update.message.reply_document(
        document=file_bytes,
        filename=f'ccs_{bin_num}.txt',
        caption=(
            f'🌹 *{len(ccs)} CCs Generated*\n'
            f'🔢 BIN: `{bin_num}`\n'
            f'🏦 Bank: `{bin_info.bank}`\n'
            f'💎 Brand: `{bin_info.brand}`\n'
            f'💳 Format: `CC|MM|YY|CVV`'
        ),
        parse_mode='Markdown'
    )

async def mass_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('❌ Usage: `/mass 414720,510000,370000 5`', parse_mode='Markdown')
        return
    
    bins_str = context.args[0]
    try:
        qty = int(context.args[1]) if len(context.args) > 1 else 5
    except ValueError:
        qty = 5
    
    qty = max(1, min(qty, 100))
    
    bins_list = [b.strip() for b in bins_str.split(',') 
                 if b.strip().isdigit() and len(b.strip()) == 6]
    
    if not bins_list:
        await update.message.reply_text('❌ No valid BINs provided!')
        return
    
    if len(bins_list) > 20:
        bins_list = bins_list[:20]
        await update.message.reply_text('⚠️ Max 20 BINs for mass generation!', parse_mode='Markdown')
    
    msg = await update.message.reply_text(f'🔥 Processing {len(bins_list)} BINs... 🌹')
    
    all_ccs = []
    fake_bins = []
    real_bins = []
    
    for bin_num in bins_list:
        ccs, error = scraper.generate_valid_cc(bin_num, qty)
        if error:
            fake_bins.append(bin_num)
        else:
            all_ccs.extend(ccs)
            real_bins.append(bin_num)
    
    if not all_ccs:
        await msg.edit_text('🚫 No CCs generated! All BINs are fake/unregistered.', parse_mode='Markdown')
        return
    
    lines = [cc.to_pipe_format() for cc in all_ccs]
    file_content = '\n'.join(lines)
    
    file_bytes = BytesIO(file_content.encode('utf-8'))
    file_bytes.name = f'mass_ccs_{len(all_ccs)}.txt'
    
    caption = (
        f'🌹 *Mass CC Generation Complete* 🌹\n\n'
        f'✅ *Real BINs:* `{len(real_bins)}`\n'
        f'❌ *Fake BINs:* `{len(fake_bins)}`\n'
        f'💳 *Total CCs:* `{len(all_ccs)}`\n'
        f'📋 Format: `CC|MM|YY|CVV`'
    )
    
    if fake_bins:
        caption += f'\n\n🚫 Skipped fake BINs: `{", ".join(fake_bins)}`'
    
    await msg.delete()
    await update.message.reply_document(
        document=file_bytes,
        filename=f'mass_ccs_{len(all_ccs)}.txt',
        caption=caption,
        parse_mode='Markdown'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = scraper.cache.get_stats()
    msg = (
        f'📊 *Session Statistics* 🌹\n\n'
        f'✅ *Real BINs:* `{s["real_bins"]}`\n'
        f'❌ *Fake BINs:* `{s["fake_bins"]}`\n'
        f'💳 *Total CCs:* `{s["total_ccs"]}`\n\n'
        f'🏦 *Top Banks:*'
    )
    if s['banks']:
        for bank, count in s['banks']:
            msg += f'\n`{bank}`: `{count}` BINs'
    else:
        msg += '\n_No real BINs verified yet_'
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        '🌹 *BULK BIN SCRAPER - HELP* 🌹\n\n'
        '*What this bot does:*\n'
        'This bot verifies if a BIN is real by checking against multiple financial databases.\n\n'
        '*Commands:*\n'
        '`/verify <6-digit-BIN>` - Check if BIN is real\n'
        '`/range <start> <end>` - Scan a range of BINs\n'
        '`/cc <BIN> <quantity>` - Generate fake CCs (real BIN only)\n'
        '`/mass <BIN1,BIN2,...> <qty>` - Mass generation\n'
        '`/stats` - View session stats\n\n'
        '*Note:* Generated CCs are fake and for educational purposes only.'
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print('❌ ERROR: Please set your BOT_TOKEN in the code!')
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('verify', verify))
    application.add_handler(CommandHandler('range', range_scrape))
    application.add_handler(CommandHandler('cc', cc_gen))
    application.add_handler(CommandHandler('mass', mass_gen))
    application.add_handler(CommandHandler('stats', stats))
    application.add_handler(CommandHandler('help', help_cmd))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print('🤖 Bot starting...')
    
    if WEBHOOK_URL:
        print(f'🌐 Webhook mode: {WEBHOOK_URL}')
        application.run_webhook(
            listen='0.0.0.0', 
            port=PORT, 
            webhook_url=WEBHOOK_URL
        )
    else:
        print('🔄 Polling mode...')
        application.run_polling()

if __name__ == '__main__':
    main()
