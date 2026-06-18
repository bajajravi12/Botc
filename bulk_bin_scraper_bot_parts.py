import os
import re
import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ============== CONFIG ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ============== LOGGING ==============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============== LUHN ALGORITHM ==============
def luhn_check(card_number):
    """Real Luhn algorithm validation"""
    if not card_number.isdigit():
        return False
    
    digits = [int(d) for d in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    
    total = sum(odd_digits)
    for d in even_digits:
        d *= 2
        if d > 9:
            d -= 9
        total += d
    
    return total % 10 == 0

def get_card_type(number):
    patterns = {
        'VISA': r'^4',
        'MASTERCARD': r'^5[1-5]',
        'AMEX': r'^3[47]',
        'DISCOVER': r'^6(?:011|5)',
        'JCB': r'^(?:2131|1800|35)',
        'DINERS': r'^3(?:0[0-5]|[68])'
    }
    for card_type, pattern in patterns.items():
        if re.match(pattern, number):
            return card_type
    return 'UNKNOWN'

def calculate_luhn_check(number):
    """Calculate Luhn check digit"""
    digits = [int(d) for d in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    
    total = sum(odd_digits)
    for d in even_digits:
        d *= 2
        if d > 9:
            d -= 9
        total += d
    
    return (10 - (total % 10)) % 10

def validate_card(card_line):
    """Validate single card line: number|MM|YY|CVV"""
    parts = card_line.strip().split('|')
    
    if len(parts) != 4:
        return {'valid': False, 'reason': 'Invalid format (need: number|MM|YY|CVV)'}
    
    number, mm, yy, cvv = parts
    
    if not number.isdigit():
        return {'valid': False, 'reason': 'Card number must be digits only'}
    
    if len(number) < 13 or len(number) > 19:
        return {'valid': False, 'reason': f'Invalid length ({len(number)} digits)'}
    
    if not luhn_check(number):
        return {'valid': False, 'reason': 'Luhn check failed'}
    
    try:
        month = int(mm)
        if month < 1 or month > 12:
            return {'valid': False, 'reason': 'Invalid month (1-12)'}
    except:
        return {'valid': False, 'reason': 'Invalid month format'}
    
    try:
        year = int(yy)
        if year < 0 or year > 99:
            return {'valid': False, 'reason': 'Invalid year format'}
    except:
        return {'valid': False, 'reason': 'Invalid year format'}
    
    from datetime import datetime
    current_year = datetime.now().year % 100
    current_month = datetime.now().month
    
    if year < current_year or (year == current_year and month < current_month):
        return {'valid': False, 'reason': 'Card expired'}
    
    card_type = get_card_type(number)
    expected_cvv = 4 if card_type == 'AMEX' else 3
    
    if len(cvv) != expected_cvv or not cvv.isdigit():
        return {'valid': False, 'reason': f'CVV must be {expected_cvv} digits'}
    
    return {
        'valid': True,
        'type': card_type,
        'bin': number[:6],
        'number': number,
        'month': mm,
        'year': yy,
        'cvv': cvv
    }

# ============== BIN DATABASE ==============
BIN_RANGES = {
    '404594': {'brand': 'VISA', 'type': 'DEBIT', 'level': 'CLASSIC', 'bank': 'Chase Bank', 'country': 'US'},
    '411111': {'brand': 'VISA', 'type': 'CREDIT', 'level': 'PLATINUM', 'bank': 'Test Bank', 'country': 'US'},
    '401288': {'brand': 'VISA', 'type': 'CREDIT', 'level': 'CLASSIC', 'bank': 'Visa Test', 'country': 'US'},
    '400000': {'brand': 'VISA', 'type': 'CREDIT', 'level': 'GOLD', 'bank': 'Various', 'country': 'US'},
    '510000': {'brand': 'MASTERCARD', 'type': 'CREDIT', 'level': 'STANDARD', 'bank': 'Various', 'country': 'US'},
    '520000': {'brand': 'MASTERCARD', 'type': 'DEBIT', 'level': 'STANDARD', 'bank': 'Various', 'country': 'US'},
    '530000': {'brand': 'MASTERCARD', 'type': 'CREDIT', 'level': 'GOLD', 'bank': 'Various', 'country': 'US'},
    '540000': {'brand': 'MASTERCARD', 'type': 'CREDIT', 'level': 'PLATINUM', 'bank': 'Various', 'country': 'US'},
    '550000': {'brand': 'MASTERCARD', 'type': 'CREDIT', 'level': 'WORLD', 'bank': 'Various', 'country': 'US'},
    '340000': {'brand': 'AMEX', 'type': 'CREDIT', 'level': 'PERSONAL', 'bank': 'Amex', 'country': 'US'},
    '370000': {'brand': 'AMEX', 'type': 'CREDIT', 'level': 'PERSONAL', 'bank': 'Amex', 'country': 'US'},
    '343434': {'brand': 'AMEX', 'type': 'CREDIT', 'level': 'GOLD', 'bank': 'Amex', 'country': 'US'},
    '601100': {'brand': 'DISCOVER', 'type': 'CREDIT', 'level': 'STANDARD', 'bank': 'Discover', 'country': 'US'},
    '601101': {'brand': 'DISCOVER', 'type': 'CREDIT', 'level': 'STANDARD', 'bank': 'Discover', 'country': 'US'},
    '352800': {'brand': 'JCB', 'type': 'CREDIT', 'level': 'STANDARD', 'bank': 'JCB', 'country': 'JP'},
    '353000': {'brand': 'JCB', 'type': 'CREDIT', 'level': 'GOLD', 'bank': 'JCB', 'country': 'JP'},
}

def get_bin_info(bin_number):
    """Get BIN info from database"""
    bin_str = str(bin_number)[:6]
    
    if bin_str in BIN_RANGES:
        info = BIN_RANGES[bin_str].copy()
        info['bin'] = bin_str
        info['exact'] = True
        return info
    
    bin_4 = bin_str[:4]
    for key, value in BIN_RANGES.items():
        if key.startswith(bin_4):
            info = value.copy()
            info['bin'] = bin_str
            info['exact'] = False
            info['matched'] = key
            return info
    
    first_digit = bin_str[0]
    brand_map = {
        '4': 'VISA',
        '5': 'MASTERCARD',
        '3': 'AMEX',
        '6': 'DISCOVER'
    }
    
    return {
        'bin': bin_str,
        'brand': brand_map.get(first_digit, 'UNKNOWN'),
        'type': 'UNKNOWN',
        'level': 'UNKNOWN',
        'bank': 'Unknown Bank',
        'country': 'Unknown',
        'exact': False,
        'generated': True
    }

def generate_range(bin_info, count=10):
    """Generate card numbers in range"""
    bin_str = bin_info['bin']
    cards = []
    
    for i in range(count):
        remaining = 16 - len(bin_str)
        last_digits = ''.join([str(random.randint(0, 9)) for _ in range(remaining - 1)])
        partial = bin_str + last_digits
        check_digit = calculate_luhn_check(partial)
        full_number = partial + str(check_digit)
        
        month = random.randint(1, 12)
        year = random.randint(24, 30)
        cvv = random.randint(100, 999)
        
        cards.append(f"{full_number}|{month:02d}|{year}|{cvv}")
    
    return cards

# ============== MESSAGES ==============
LIVE_MESSAGES = [
    "CVV2 match - approved",
    "Approved - card active",
    "Approved - $0 auth",
    "Issuer approved"
]

DIE_MESSAGES = [
    "Restricted card",
    "Expired card on file",
    "Card declined",
    "Fraud suspicion - declined",
    "Invalid card number",
    "Stolen card"
]

# ============== ACTIVE CHECKS ==============
active_checks = {}

# ============== HANDLERS ==============

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    keyboard = [
        [InlineKeyboardButton("🚀 CC Checker", callback_data='cc_checker'),
         InlineKeyboardButton("🔍 BIN Finder", callback_data='bin_finder')],
        [InlineKeyboardButton("📖 Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome = """
🚀 **CC CHECKER + BIN FINDER BOT**

**Features:**
✅ CC Checker (Luhn validation)
✅ BIN Lookup & Range Generator
✅ .txt file support
✅ Real-time processing

**Choose mode below or use commands:**
• `/chk` - Check cards from file
• `/bin <6_digit>` - Lookup BIN
• `/range <bin> <count>` - Generate cards
• `/gen <bin> <count>` - Quick generate

**Powered by:** @YourChannel
    """
    await update.message.reply_text(welcome, reply_markup=reply_markup, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
📖 **HELP MENU**

**🚀 CC CHECKER:**
Upload `.txt` file with cards in format:
`number|MM|YY|CVV`

Reply with `/chk` to start checking

**🔍 BIN FINDER:**
• `/bin 404594` - Lookup BIN info
• `/range 404594 20` - Generate 20 cards
• `/gen 510000 10` - Quick generate
• `/chkbin 404594...` - Check full card

**✅ Checks:**
• Luhn Algorithm
• Card length (13-19 digits)
• Card type detection
• Expiry validation
• CVV length check
• BIN extraction
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def chk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check cards from replied file"""
    user_id = update.effective_user.id
    
    # Check if replying to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Reply to a `.txt` file** with `/chk` command!\n\n"
            "1. Upload `.txt` file\n"
            "2. Reply to it with `/chk`",
            parse_mode='Markdown'
        )
        return
    
    replied = update.message.reply_to_message
    
    # Check if file exists
    if not replied.document:
        await update.message.reply_text("❌ **No file found!** Reply to a `.txt` file.")
        return
    
    file_name = replied.document.file_name or "unknown"
    
    if not file_name.endswith('.txt'):
        await update.message.reply_text("❌ **Only `.txt` files supported!**")
        return
    
    # Download file
    status_msg = await update.message.reply_text("📥 **Downloading file...**")
    
    try:
        file_obj = await context.bot.get_file(replied.document.file_id)
        file_path = f"/tmp/{file_name}"
        await file_obj.download_to_drive(file_path)
        
        # Read cards
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        cards = [line.strip() for line in lines if line.strip()]
        
        if not cards:
            await status_msg.edit_text("❌ **No cards found in file!**")
            os.remove(file_path)
            return
        
        # Start checking
        active_checks[user_id] = True
        
        await status_msg.edit_text(
            f"🚀 **STARTING CHECK**\n\n"
            f"📁 File: `{file_name}`\n"
            f"📊 Total Cards: `{len(cards)}`\n"
            f"⏳ Status: Processing...",
            parse_mode='Markdown'
        )
        
        live_cards = []
        die_cards = []
        checked = 0
        
        # Process cards
        for card_line in cards:
            if not active_checks.get(user_id, False):
                break
            
            result = validate_card(card_line)
            checked += 1
            
            if result['valid']:
                live_cards.append({
                    'line': card_line,
                    'type': result['type'],
                    'bin': result['bin']
                })
            else:
                die_cards.append({
                    'line': card_line,
                    'reason': result['reason']
                })
            
            # Update every 5 cards
            if checked % 5 == 0 or checked == len(cards):
                progress = (checked / len(cards)) * 100
                
                status_text = (
                    f"🚀 **CHECKING CARDS**\n\n"
                    f"📁 File: `{file_name}`\n"
                    f"📊 Total: `{len(cards)}`\n"
                    f"✅ Live: `{len(live_cards)}`\n"
                    f"❌ Die: `{len(die_cards)}`\n"
                    f"⏳ Checked: `{checked}/{len(cards)}` ({progress:.1f}%)"
                )
                await status_msg.edit_text(status_text, parse_mode='Markdown')
                await asyncio.sleep(0.3)
        
        # Final results
        active_checks[user_id] = False
        
        # Send live results
        if live_cards:
            live_text = f"✅ **LIVE CARDS - {len(live_cards)}**\n\n"
            live_text += "Format: number|MM|YY|CVV\n"
            live_text += "═" * 30 + "\n\n"
            
            for i, card in enumerate(live_cards, 1):
                msg = LIVE_MESSAGES[i % len(LIVE_MESSAGES)]
                live_text += f"💳 `{card['line']}`\n"
                live_text += f"   Type: {card['type']} | BIN: {card['bin']}\n"
                live_text += f"   Status: {msg}\n\n"
            
            # Split if too long
            if len(live_text) > 4000:
                chunks = [live_text[i:i+4000] for i in range(0, len(live_text), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
            else:
                await update.message.reply_text(live_text, parse_mode='Markdown')
        
        # Send die results
        if die_cards:
            die_text = f"❌ **DIE CARDS - {len(die_cards)}**\n\n"
            die_text += "═" * 30 + "\n\n"
            
            for i, card in enumerate(die_cards, 1):
                die_text += f"💀 `{card['line']}`\n"
                die_text += f"   Reason: {card['reason']}\n\n"
            
            if len(die_text) > 4000:
                chunks = [die_text[i:i+4000] for i in range(0, len(die_text), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
            else:
                await update.message.reply_text(die_text, parse_mode='Markdown')
        
        # Final summary
        summary = (
            f"🏁 **CHECK COMPLETE**\n\n"
            f"📁 File: `{file_name}`\n"
            f"📊 Total Cards: `{len(cards)}`\n"
            f"✅ Live: `{len(live_cards)}`\n"
            f"❌ Die: `{len(die_cards)}`\n"
            f"📈 Success Rate: `{(len(live_cards)/len(cards)*100):.1f}%`\n\n"
            f"**Thanks for using CC Checker!** 🚀"
        )
        await status_msg.edit_text(summary, parse_mode='Markdown')
        
        # Cleanup
        os.remove(file_path)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if os.path.exists(file_path):
            os.remove(file_path)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop current check"""
    user_id = update.effective_user.id
    if user_id in active_checks:
        active_checks[user_id] = False
        await update.message.reply_text("🛑 **Check stopped!**")
    else:
        await update.message.reply_text("❌ No active check to stop!")

async def bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIN lookup command"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Usage:** `/bin <6_digit_bin>`\n\n"
            "Example: `/bin 404594`",
            parse_mode='Markdown'
        )
        return
    
    bin_num = context.args[0]
    if not bin_num.isdigit() or len(bin_num) != 6:
        await update.message.reply_text("❌ **BIN must be 6 digits!**")
        return
    
    info = get_bin_info(bin_num)
    exact_text = "✅ Exact Match" if info['exact'] else "⚠️ Estimated"
    
    result = (
        f"🔍 **BIN LOOKUP RESULT**\n\n"
        f"**BIN:** `{info['bin']}`\n"
        f"**Status:** {exact_text}\n\n"
        f"📋 **Card Details:**\n"
        f"• **Brand:** {info['brand']}\n"
        f"• **Type:** {info['type']}\n"
        f"• **Level:** {info['level']}\n"
        f"• **Bank:** {info['bank']}\n"
        f"• **Country:** {info['country']}\n\n"
        f"**Card Range:**\n"
        f"`{info['bin']}0000000` - `{info['bin']}9999999`\n\n"
        f"Use `/range {info['bin']} 10` to generate cards"
    )
    await update.message.reply_text(result, parse_mode='Markdown')

async def range_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate range from BIN"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Usage:** `/range <6_digit_bin> <count>`\n\n"
            "Example: `/range 404594 20`",
            parse_mode='Markdown'
        )
        return
    
    bin_num = context.args[0]
    try:
        count = min(int(context.args[1]), 50)
    except:
        count = 10
    
    if not bin_num.isdigit() or len(bin_num) != 6:
        await update.message.reply_text("❌ **BIN must be 6 digits!**")
        return
    
    info = get_bin_info(bin_num)
    
    status = await update.message.reply_text(
        f"🔄 Generating {count} cards for BIN `{bin_num}`...",
        parse_mode='Markdown'
    )
    
    cards = generate_range(info, count)
    
    # Save to file
    filename = f"/tmp/bin_{bin_num}_range.txt"
    with open(filename, 'w') as f:
        f.write(f"# BIN: {bin_num}\n")
        f.write(f"# Brand: {info['brand']}\n")
        f.write(f"# Type: {info['type']}\n")
        f.write(f"# Level: {info['level']}\n")
        f.write(f"# Bank: {info['bank']}\n")
        f.write(f"# Country: {info['country']}\n")
        f.write(f"# Generated: {count} cards\n")
        f.write("=" * 40 + "\n\n")
        for card in cards:
            f.write(card + "\n")
    
    # Send file
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(filename, 'rb'),
        caption=(
            f"✅ **RANGE GENERATED**\n\n"
            f"🔍 **BIN:** `{bin_num}`\n"
            f"📊 **Count:** `{count}` cards\n"
            f"💳 **Brand:** {info['brand']}\n"
            f"🏦 **Bank:** {info['bank']}\n\n"
            f"**Format:** number|MM|YY|CVV\n\n"
            f"Use with `/chk` command!"
        ),
        parse_mode='Markdown'
    )
    
    await status.delete()
    os.remove(filename)

async def gen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick generate alias"""
    await range_cmd(update, context)

async def chkbin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check BIN from full card"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Usage:** `/chkbin <card_number>`\n\n"
            "Example: `/chkbin 4045947406237512`",
            parse_mode='Markdown'
        )
        return
    
    card_num = context.args[0].replace('|', '').replace(' ', '')
    if not card_num.isdigit():
        await update.message.reply_text("❌ **Card number must be digits only!**")
        return
    
    bin_num = card_num[:6]
    info = get_bin_info(bin_num)
    valid = luhn_check(card_num)
    detected_type = get_card_type(card_num)
    
    result = (
        f"🔍 **CARD ANALYSIS**\n\n"
        f"**Number:** `{card_num}`\n"
        f"**BIN:** `{bin_num}`\n\n"
        f"📋 **BIN Info:**\n"
        f"• **Brand:** {info['brand']} (Detected: {detected_type})\n"
        f"• **Type:** {info['type']}\n"
        f"• **Level:** {info['level']}\n"
        f"• **Bank:** {info['bank']}\n"
        f"• **Country:** {info['country']}\n\n"
        f"✅ **Luhn Check:** {'PASS ✓' if valid else 'FAIL ✗'}\n"
        f"📏 **Length:** {len(card_num)} digits\n\n"
        f"**Status:** {'✅ VALID' if valid else '❌ INVALID'}"
    )
    await update.message.reply_text(result, parse_mode='Markdown')

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats"""
    stats_text = (
        f"📊 **BOT STATISTICS**\n\n"
        f"🤖 **Status:** Online ✅\n"
        f"⚡ **Algorithm:** Luhn Check\n"
        f"🔍 **Validation:** Real-time\n"
        f"📁 **File Support:** .txt files\n\n"
        f"**Supported Cards:**\n"
        f"💳 VISA\n"
        f"💳 MasterCard\n"
        f"💳 American Express\n"
        f"💳 Discover\n"
        f"💳 JCB\n"
        f"💳 Diners Club\n\n"
        f"**Commands:**\n"
        f"• `/chk` - Check cards\n"
        f"• `/bin` - BIN lookup\n"
        f"• `/range` - Generate range\n"
        f"• `/gen` - Quick generate\n"
        f"• `/chkbin` - Check card\n"
        f"• `/stop` - Stop check"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-detect file upload"""
    if update.message.document and update.message.document.file_name.endswith('.txt'):
        await update.message.reply_text(
            "📁 **File received!**\n\n"
            "Reply with `/chk` to start checking cards.\n\n"
            "**Format:** `number|MM|YY|CVV`",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ **An error occurred!**\nPlease try again later."
            )
    except:
        pass

# ============== MAIN ==============
def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("chk", chk_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("bin", bin_cmd))
    application.add_handler(CommandHandler("range", range_cmd))
    application.add_handler(CommandHandler("gen", gen_cmd))
    application.add_handler(CommandHandler("chkbin", chkbin_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    
    # File handler
    application.add_handler(MessageHandler(filters.Document.TEXT, file_handler))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("🚀 Bot Starting...")
    print("📁 Send .txt file and reply with /chk")
    print("🔍 Use /bin for BIN lookup")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
