import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import imaplib
import email
from email.header import decode_header
import io
import re
import html

# ================= কনফিগারেশন =================
API_TOKEN = '8526670393:AAGt_si_DtCAKjGF2Ht8uAmdQeO1rp1sOas'
ADMIN_ID = 6670461311

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

user_states = {} 
SERVICES = ['Instagram', 'Facebook', 'YouTube', 'TikTok', 'Twitter', 'Other']

# ================= ফায়ারবেস সেটআপ =================
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    settings_ref = db.collection('settings').document('payment_methods')
    if not settings_ref.get().exists:
        settings_ref.set({'bkash': 'Not Set', 'nagad': 'Not Set', 'binance': 'Not Set'})
        
    prices_ref = db.collection('settings').document('prices')
    if not prices_ref.get().exists:
        prices_ref.set({'Gmail': {'price': 6, 'validity': '6 Hours'}})
except Exception as e:
    print("Firebase Error:", e)

# ================= HTML রিমুভার & OTP এক্সট্রাক্টর =================
def strip_html(text):
    text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text) 
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_otp(text):
    clean_text = strip_html(text)
    # 6-8 ডিজিট কোড
    match = re.search(r'\b\d{3}\s?\d{3,5}\b', clean_text)
    if match: return match.group(0).strip()
    # আলফানিউমেরিক কোড
    match = re.search(r'(?i)(?:code|otp|password|pin).*?\b([A-Za-z0-9]{6,8})\b', clean_text.replace(" ", ""))
    if match: return match.group(1).strip()
    return None

# ================= ব্যাকগ্রাউন্ড চেকার (Duplicate Fix) =================
def return_to_inventory(email_addr, password, cooldowns):
    # ডাবল হওয়া রোধ করতে আগের মেইল আপডেট করবে, না থাকলে নতুন বানাবে
    inv_docs = list(db.collection('inventory').where('email', '==', email_addr).stream())
    if inv_docs:
        inv_docs[0].reference.update({'status': 'fresh', 'cooldowns': cooldowns, 'password': password})
    else:
        db.collection('inventory').add({'email': email_addr, 'password': password, 'category': 'Gmail', 'status': 'fresh', 'cooldowns': cooldowns})

def auto_inventory_manager():
    while True:
        time.sleep(60) 
        try:
            now = time.time()
            sales = db.collection('active_sales').stream()
            for sale in sales:
                data = sale.to_dict()
                buy_time = data.get('buy_timestamp', 0)
                msg_received = data.get('msg_received', False)
                elapsed = now - buy_time
                service = data.get('service', 'Other')
                cooldowns = data.get('cooldowns', {})
                
                # ২০ মিনিট ওভার এবং কোড আসেনি
                if elapsed >= 1200 and not msg_received:
                    user_ref = db.collection('users').document(str(data['user_id']))
                    cur_bal = user_ref.get().to_dict().get('balance', 0)
                    user_ref.update({'balance': cur_bal + data['price']})
                    
                    return_to_inventory(data['email'], data['password'], cooldowns)
                    try: bot.send_message(data['user_id'], f"⚠️ **অটো রিফান্ড!**\n২০ মিনিটে `{service}` এর কোড না আসায় `{data['email']}` বাতিল করে {data['price']} ৳ রিফান্ড করা হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
                    
                # ৬ ঘণ্টা ওভার 
                elif elapsed >= 21600:
                    if msg_received: cooldowns[service] = now
                    return_to_inventory(data['email'], data['password'], cooldowns)
                    try: bot.send_message(data['user_id'], f"⏳ **সময় শেষ!**\n৬ ঘণ্টা পার হয়ে যাওয়ায় `{data['email']}` মেইলটির মেয়াদ শেষ হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
        except: pass

threading.Thread(target=auto_inventory_manager, daemon=True).start()

# ================= সার্ভার =================
@app.route('/')
def home(): return "Waleya OTP Premium Bot is Running!"
def run_server(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# ================= মেনু =================
def user_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 Purchase Mail"), KeyboardButton("📧 My Gmail"),
        KeyboardButton("💳 Balance & Stock"), KeyboardButton("👤 My Profile"),
        KeyboardButton("ℹ️ Support")
    )
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📊 Admin Dashboard"), KeyboardButton("👥 User Management"),
        KeyboardButton("📧 Manage Inventory"), KeyboardButton("⚙️ Bot Settings"),
        KeyboardButton("📢 Global Notice")
    )
    return markup

def cancel_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Cancel Action"))
    return markup

def is_banned(user_id):
    try:
        doc = db.collection('users').document(str(user_id)).get()
        return doc.exists and doc.to_dict().get('status') == 'banned'
    except: return False

# ================= স্টার্ট কমান্ড =================
@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    if is_banned(user_id): return bot.send_message(user_id, "🚫 আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।")
        
    try:
        user_ref = db.collection('users').document(str(user_id))
        if not user_ref.get().exists: user_ref.set({'name': name, 'balance': 0, 'joined': time.time(), 'status': 'active'})
    except: pass
        
    if user_id == ADMIN_ID: bot.send_message(user_id, f"স্বাগতম অ্যাডমিন {name}!", reply_markup=admin_menu())
    else: bot.send_message(user_id, f"স্বাগতম {name}! প্রিমিয়াম OTP Verification সিস্টেমে আপনাকে স্বাগতম।", reply_markup=user_menu())

@bot.message_handler(func=lambda message: message.text == "❌ Cancel Action")
def cancel_action(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "❌ একশন বাতিল করা হয়েছে।", reply_markup=menu)

# ===================== ইউজার: BEAUTIFUL BALANCE =====================
@bot.message_handler(func=lambda message: message.text == "💳 Balance & Stock")
def balance_menu(message):
    if is_banned(message.chat.id): return
    bal = db.collection('users').document(str(message.chat.id)).get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    stock = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()))
    p = prices.get('Gmail', {}).get('price', 0)
    
    text = f"""
💳 **User Account Balance**
╔════════════════════╗
  💰 **{float(bal):.2f} TK**
╚════════════════════╝

📋 **Service Price List**
╔════════════════════╗
 📧 Any Service OTP ➔ {p}.00 TK
 ⏱ Validity: 6 Hours
╚════════════════════╝

📦 **Current Stock**
╔════════════════════╗
 📦 Total Fresh Mails: {stock}
╚════════════════════╝
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Fund / Deposit", callback_data="add_fund_start"))
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

# ===================== ইউজার: PURCHASE =====================
@bot.message_handler(func=lambda message: message.text == "🛒 Purchase Mail")
def purchase_service_selection(message):
    if is_banned(message.chat.id): return
    markup = InlineKeyboardMarkup(row_width=2)
    for srv in SERVICES: markup.add(InlineKeyboardButton(f"📌 {srv}", callback_data=f"buy_srv_{srv}"))
    bot.send_message(message.chat.id, "📧 **কোন সার্ভিসের জন্য মেইল বা OTP নিতে চান?**\n_নিচের লিস্ট থেকে সিলেক্ট করুন:_ ", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_srv_"))
def process_purchase(call):
    bot.answer_callback_query(call.id)
    user_id = call.message.chat.id
    service = call.data.split('_')[2]
    
    user_ref = db.collection('users').document(str(user_id))
    bal = user_ref.get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    price = prices.get('Gmail', {}).get('price', 0)
    
    if bal < price: return bot.send_message(user_id, f"❌ আপনার ব্যালেন্স পর্যাপ্ত নয়। দাম {price} ৳।")
        
    fresh_mails = db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()
    selected_mail_doc, selected_data, now = None, None, time.time()
    
    for m in fresh_mails:
        data = m.to_dict()
        last_used = data.get('cooldowns', {}).get(service, 0)
        if now - last_used > 432000: # ৫ দিনের রুল
            selected_mail_doc, selected_data = m, data
            break
            
    if selected_mail_doc:
        user_ref.update({'balance': bal - price})
        selected_mail_doc.reference.update({'status': 'sold'})
        db.collection('active_sales').add({
            'user_id': user_id, 'email': selected_data['email'], 'password': selected_data['password'], 
            'category': 'Gmail', 'price': price, 'buy_timestamp': now, 
            'msg_received': False, 'service': service, 'cooldowns': selected_data.get('cooldowns', {})
        })
        text = f"✅ **Mail Assigned Successfully!**\n━━━━━━━━━━━━━━━━━━━━\n📌 **Service:** {service}\n📧 **Email:** `{selected_data['email']}`\n\n_• Go to 'My Gmail' menu to get your OTP codes ⬇️_"
        bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.send_message(user_id, f"❌ এই মুহূর্তে **{service}** এর জন্য কোনো ফ্রেশ মেইল স্টকে নেই। একটু পর চেষ্টা করুন।")

# ===================== ইউজার: MY GMAIL LIST =====================
@bot.message_handler(func=lambda message: message.text == "📧 My Gmail")
def my_gmail_list(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    try:
        active_sales = db.collection('active_sales').where('user_id', '==', user_id).stream()
        markup = InlineKeyboardMarkup(row_width=1)
        found, now = False, time.time()
        
        for sale in active_sales:
            found = True
            data = sale.to_dict()
            remaining = int(21600 - (now - data.get('buy_timestamp', 0)))
            
            if remaining > 0:
                h, r = divmod(remaining, 3600)
                m, s = divmod(r, 60)
                btn_text = f"📌 {data.get('service', 'Mail')} | ⏳ {h:02d}:{m:02d}:{s:02d}"
                markup.add(InlineKeyboardButton(btn_text, callback_data=f"mailopt_{sale.id}"))
                
        if not found: bot.send_message(user_id, "আপনার কোনো সক্রিয় জিমেইল নেই।")
        else: bot.send_message(user_id, "📂 **আপনার কেনা জিমেইল তালিকা:**\n_বিস্তারিত দেখতে এবং OTP পেতে নিচের লিস্ট থেকে মেইলে ক্লিক করুন:_", reply_markup=markup, parse_mode='Markdown')
    except Exception as e: print(e)

@bot.callback_query_handler(func=lambda call: call.data.startswith("mailopt_"))
def mail_options_menu(call):
    bot.answer_callback_query(call.id)
    sale_id = call.data.split('_')[1]
    user_id = call.message.chat.id
    
    sale_doc = db.collection('active_sales').document(sale_id).get()
    if not sale_doc.exists: return bot.edit_message_text("❌ এই মেইলটির মেয়াদ শেষ বা এটি আর নেই।", chat_id=user_id, message_id=call.message.message_id)
        
    data = sale_doc.to_dict()
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📩 Check Inbox", callback_data=f"inbox_{sale_id}"),
        InlineKeyboardButton("🗑 Delete & Return", callback_data=f"retmail_{sale_id}")
    )
    text = f"⚙️ **Gmail Management**\n━━━━━━━━━━━━━━━━━━━━\n📌 **Service:** {data.get('service', 'Other')}\n📧 **Email:** `{data['email']}`\n\n_OTP দেখতে Check Inbox এ ক্লিক করুন।_"
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

# ===================== ইউজার: DELETE & RETURN =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("retmail_"))
def return_user_mail(call):
    bot.answer_callback_query(call.id)
    sale_id = call.data.split('_')[1]
    user_id = call.message.chat.id
    
    sale_ref = db.collection('active_sales').document(sale_id)
    sale_doc = sale_ref.get()
    
    if sale_doc.exists:
        data = sale_doc.to_dict()
        price = data.get('price', 0)
        msg_received = data.get('msg_received', False)
        service = data.get('service', 'Other')
        cooldowns = data.get('cooldowns', {})
        
        if msg_received: cooldowns[service] = time.time()
        return_to_inventory(data['email'], data['password'], cooldowns)
        
        if not msg_received:
            user_ref = db.collection('users').document(str(user_id))
            cur_bal = user_ref.get().to_dict().get('balance', 0)
            user_ref.update({'balance': cur_bal + price})
            msg_text = f"✅ মেইলটি ফেরত দেওয়া হয়েছে এবং আপনার ব্যালেন্স {price} ৳ রিফান্ড করা হয়েছে।"
        else:
            msg_text = f"✅ মেইলটি আপনার লিস্ট থেকে ডিলিট করা হয়েছে। (যেহেতু আপনি কোড রিসিভ করেছিলেন, তাই কোনো রিফান্ড হয়নি)।"
            
        sale_ref.delete()
        bot.edit_message_text(msg_text, chat_id=user_id, message_id=call.message.message_id)
    else: bot.send_message(user_id, "❌ মেইলটি ডাটাবেসে পাওয়া যায়নি।")

# ===================== ইনবক্স চেকিং ও অ্যানিমেশন =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox_"))
def check_inbox(call):
    bot.answer_callback_query(call.id)
    sale_id = call.data.split('_')[1]
    user_id = call.message.chat.id
    
    sale_ref = db.collection('active_sales').document(sale_id)
    sale_doc = sale_ref.get()
    if not sale_doc.exists: return bot.edit_message_text("❌ এই মেইলটির মেয়াদ শেষ।", chat_id=user_id, message_id=call.message.message_id)
        
    data = sale_doc.to_dict()
    email_addr, password, service_keyword = data['email'], data['password'], data.get('service', 'Other').lower()
    
    msg = bot.send_message(user_id, "⏳ Connecting to Server...")
    time.sleep(0.5)
    bot.edit_message_text("🔄 Scanning Inbox for Latest OTP...", chat_id=user_id, message_id=msg.message_id)
    time.sleep(0.5)
    
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(email_addr, password)
        mail.select('inbox')
        status, search_data = mail.search(None, 'ALL')
        mail_ids = search_data[0].split()

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔄 Refresh Code", callback_data=f"inbox_{sale_id}"),
            InlineKeyboardButton("🔙 Back to Options", callback_data=f"mailopt_{sale_id}")
        )

        if not mail_ids:
            bot.edit_message_text(f"❌ `{email_addr}`\nইনবক্সে কোনো মেসেজ নেই।\n\n_Refresh Code এ ক্লিক করে আবার চেক করুন।_", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown', reply_markup=markup)
            return

        found_msg = None
        for m_id in reversed(mail_ids[-10:]):
            status, msg_data = mail.fetch(m_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg_obj = email.message_from_bytes(response_part[1])
                    subject = decode_header(msg_obj["Subject"])[0][0]
                    if isinstance(subject, bytes): subject = subject.decode(errors='ignore')
                    sender = decode_header(msg_obj.get("From"))[0][0]
                    if isinstance(sender, bytes): sender = sender.decode(errors='ignore')

                    body = ""
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors='ignore')
                                break
                    else: body = msg_obj.get_payload(decode=True).decode(errors='ignore')
                    
                    if service_keyword == 'other' or service_keyword in sender.lower() or service_keyword in subject.lower():
                        found_msg = (sender, subject, body)
                        break
            if found_msg: break

        if not found_msg:
            bot.edit_message_text(f"❌ **{data.get('service')}** থেকে এখনো কোড আসেনি।\n\n_Refresh Code এ ক্লিক করে আবার চেক করুন।_", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            sender, subject, body = found_msg
            sale_ref.update({'msg_received': True})
            
            clean_body = strip_html(body)
            otp_code = extract_otp(subject + " " + clean_body)
            
            text = f"**SUPPORT WALEYA OTP**\n📧 Email: `{email_addr}`\n\n"
            if otp_code:
                text += f"╔════════════════════╗\n   🔑 Code: `{otp_code}`   \n╚════════════════════╝\n\n"
            
            snippet = clean_body[:100].strip()
            if snippet: text += f"❝ {snippet}... ❞\n"
            
            bot.edit_message_text(text, chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown', reply_markup=markup)
            
    except Exception as e:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Back to Options", callback_data=f"mailopt_{sale_id}"))
        bot.edit_message_text(f"❌ **Login Failed!** App Password চেক করুন।", chat_id=user_id, message_id=msg.message_id, reply_markup=markup)

# (Add fund, Profiles, Support blocks remain exactly the same as previously validated)
@bot.callback_query_handler(func=lambda call: call.data == "add_fund_start")
def ask_fund_amount(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "আপনি কত টাকা অ্যাড করতে চান? (যেমন: 100)", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, ask_payment_gateway)

def ask_payment_gateway(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    try:
        amount = int(message.text)
        user_states[message.chat.id] = {'amount': amount}
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🟣 bKash", callback_data="pay_bkash"), InlineKeyboardButton("🟠 Nagad", callback_data="pay_nagad"), InlineKeyboardButton("🟡 Binance", callback_data="pay_binance"))
        bot.send_message(message.chat.id, f"আপনি {amount} ৳ অ্যাড করতে চাচ্ছেন।\nদয়া করে পেমেন্ট মেথড সিলেক্ট করুন:", reply_markup=markup)
        bot.send_message(message.chat.id, "ক্যানসেল করতে চাইলে নিচের মেনু থেকে Cancel চাপুন।", reply_markup=cancel_markup())
    except: bot.send_message(message.chat.id, "❌ সঠিক টাকার পরিমাণ দিন।", reply_markup=user_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def show_payment_details(call):
    bot.answer_callback_query(call.id)
    method = call.data.split('_')[1]
    amount = user_states.get(call.message.chat.id, {}).get('amount', 0)
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    account_info = settings.get(method, "Not Setup Yet")
    user_states[call.message.chat.id]['method'] = method
    text = f"💳 **Payment details for {method.capitalize()}**\n━━━━━━━━━━━━━━\nপরিমাণ: {amount} ৳\nনম্বর/ID: `{account_info}` (কপি করতে ট্যাপ করুন)\n\nটাকা পাঠানোর পর আপনার Transaction ID নিচে লিখে দিন:"
    msg = bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_trx_id)

def process_trx_id(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    user_id = message.chat.id
    trx_id = message.text.strip()
    data = user_states.get(user_id, {})
    if not data: return bot.send_message(user_id, "সেশন এক্সপায়ার হয়েছে। আবার চেষ্টা করুন।", reply_markup=user_menu())
    request_id = f"req_{int(time.time())}"
    db.collection('payment_requests').document(request_id).set({'user_id': user_id, 'amount': data['amount'], 'method': data['method'], 'trx_id': trx_id, 'status': 'pending'})
    admin_text = f"🔔 **New Deposit Request**\n━━━━━━━━━━━━━━\n👤 User ID: `{user_id}`\n💰 Amount: {data['amount']} ৳\n🏦 Method: {data['method'].capitalize()}\n🏷 TrxID: `{trx_id}`"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"), InlineKeyboardButton("❌ Decline", callback_data=f"decline_{request_id}"))
    bot.send_message(ADMIN_ID, admin_text, parse_mode='Markdown', reply_markup=markup)
    bot.send_message(user_id, "✅ আপনার পেমেন্ট রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে। অ্যাপ্রুভ হওয়া পর্যন্ত অপেক্ষা করুন।", reply_markup=user_menu())
    user_states.pop(user_id, None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("decline_"))
def handle_payment_request(call):
    bot.answer_callback_query(call.id)
    action, req_id = call.data.split('_', 1)
    req_doc = db.collection('payment_requests').document(req_id)
    req_data = req_doc.get().to_dict()
    if req_data['status'] != 'pending': return bot.send_message(call.message.chat.id, "এই রিকোয়েস্টটি আগেই প্রসেস করা হয়েছে।")
    user_id, amount = req_data['user_id'], req_data['amount']
    if action == "approve":
        user_ref = db.collection('users').document(str(user_id))
        cur_bal = user_ref.get().to_dict().get('balance', 0)
        user_ref.update({'balance': cur_bal + amount})
        req_doc.update({'status': 'approved'})
        bot.edit_message_text(f"✅ Approved: {amount} ৳ added to `{user_id}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
        try: bot.send_message(user_id, f"🎉 **Payment Approved!**\nআপনার অ্যাকাউন্টে {amount} ৳ অ্যাড হয়েছে।")
        except: pass
    else:
        req_doc.update({'status': 'declined'})
        bot.edit_message_text(f"❌ Declined Request of `{user_id}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
        try: bot.send_message(user_id, f"❌ **Payment Declined!**\nআপনার {amount} ৳ এর পেমেন্ট রিকোয়েস্টটি বাতিল করা হয়েছে। সঠিক TrxID দিয়ে আবার চেষ্টা করুন।")
        except: pass

@bot.message_handler(func=lambda message: message.text == "👤 My Profile")
def user_profile(message):
    user_id = message.chat.id
    data = db.collection('users').document(str(user_id)).get().to_dict()
    bought = len(list(db.collection('active_sales').where('user_id', '==', user_id).stream()))
    text = f"💠 **PREMIUM USER PROFILE** 💠\n━━━━━━━━━━━━━━━━━━━━\n👤 **Name:** {data.get('name') or 'User'}\n🆔 **User ID:** `{user_id}`\n💰 **Balance:** {float(data.get('balance', 0)):.2f} TK\n🛒 **Total Bought:** {bought} Services\n🏆 **Status:** Verified Customer\n━━━━━━━━━━━━━━━━━━━━"
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "ℹ️ Support")
def bot_info(message):
    text = f"🌟 **WALEYA VERIFICATION SHOP** 🌟\n━━━━━━━━━━━━━━━━━━━━\n🚀 **বটের সুবিধাগুলো:**\n✓ ইনস্ট্যান্ট OTP ডেলিভারি\n✓ ৬ ঘণ্টার ভ্যালিডিটি এবং ৫ দিনের কুলডাউন\n✓ স্মার্ট অটো-রিফান্ড সিস্টেম\n✓ হাই-কোয়ালিটি প্রিমিয়াম সার্ভিস\n\n👨‍💻 **Developer:** [Waleya](tg://user?id={ADMIN_ID})\n📞 **Support:** [Contact Admin](tg://user?id={ADMIN_ID})\n━━━━━━━━━━━━━━━━━━━━"
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ===================== অ্যাডমিন: MANAGE INVENTORY (Single View & Search) =====================
@bot.message_handler(func=lambda message: message.text == "📧 Manage Inventory" and message.chat.id == ADMIN_ID)
def manage_mails(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Gmails", callback_data="add_mails"), InlineKeyboardButton("📋 Mail List", callback_data="view_mails"))
    markup.add(InlineKeyboardButton("🔍 Search Mail", callback_data="search_mail_admin"))
    bot.send_message(message.chat.id, "মেইল ম্যানেজমেন্ট মেনু:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "view_mails")
def view_mails(call):
    bot.answer_callback_query(call.id)
    mails = list(db.collection('inventory').stream())
    
    # ডাবল মেইল সিঙ্গেল করার লজিক
    unique_mails = {}
    for m in mails:
        d = m.to_dict()
        email_addr = d['email']
        if email_addr not in unique_mails: unique_mails[email_addr] = d
        else: unique_mails[email_addr]['cooldowns'].update(d.get('cooldowns', {}))
            
    if not unique_mails: return bot.send_message(call.message.chat.id, "স্টকে কোনো মেইল নেই।")
    
    text = "📋 **সর্বশেষ মেইলের লিস্ট:**\n\n"
    for email_addr, d in list(unique_mails.items())[:15]:
        sold_count = len(d.get('cooldowns', {}))
        tag = "🟢 Fresh" if sold_count == 0 else f"🔴 Sold: {sold_count} Times"
        text += f"📧 `{email_addr}` - {tag}\n"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📄 Export All to TXT File", callback_data="export_all_mails"))
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "search_mail_admin")
def ask_mail_search(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔎 মেইল অ্যাড্রেসটি লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_search_mail)

def process_search_mail(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    email_addr = message.text.strip()
    
    docs = list(db.collection('inventory').where('email', '==', email_addr).stream())
    if not docs: return bot.send_message(message.chat.id, "❌ এই মেইলটি স্টকে পাওয়া যায়নি।", reply_markup=admin_menu())
    
    all_cooldowns = {}
    for d in docs: all_cooldowns.update(d.to_dict().get('cooldowns', {}))
        
    sold_count = len(all_cooldowns)
    used_services = ", ".join(all_cooldowns.keys()) if sold_count > 0 else "None"
    
    text = f"🔎 **Mail Details**\n━━━━━━━━━━━━━━\n📧 **Email:** `{email_addr}`\n🛒 **Total Sold:** {sold_count} times\n📌 **Used Services:** {used_services}\n"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🗑 Delete this Mail", callback_data=f"delmailall_{email_addr}"))
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delmailall_"))
def delete_all_mail_instances(call):
    bot.answer_callback_query(call.id)
    email_addr = call.data.split('_')[1]
    docs = db.collection('inventory').where('email', '==', email_addr).stream()
    count = 0
    for doc in docs:
        doc.reference.delete()
        count += 1
    bot.edit_message_text(f"✅ ডাটাবেস থেকে `{email_addr}` সম্পূর্ণ মুছে ফেলা হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "add_mails")
def enter_mails_to_add(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"নতুন জিমেইলগুলো নিচে দিন।\nফরম্যাট: `email|password` (এখানে App Password দিবেন)", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_add_mails)

def process_add_mails(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email_addr, password = line.split('|')
            db.collection('inventory').add({'email': email_addr.strip(), 'password': password.strip(), 'category': 'Gmail', 'status': 'fresh', 'cooldowns': {}})
            added += 1
    bot.send_message(message.chat.id, f"✅ ডাটাবেসে {added} টি জিমেইল যুক্ত হয়েছে!", reply_markup=admin_menu(), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "export_all_mails")
def export_all_mails_txt(call):
    bot.answer_callback_query(call.id)
    mails = list(db.collection('inventory').stream())
    text_data = "Email | Password | Category | Status\n" + "-"*50 + "\n"
    for m in mails:
        d = m.to_dict()
        text_data += f"{d.get('email')} | {d.get('password')} | {d.get('category')} | {d.get('status')}\n"
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "Mail_Inventory.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 All Mails Exported")

# ===================== অ্যাডমিন: OTHER FUNCTIONS =====================
@bot.message_handler(func=lambda message: message.text == "📊 Admin Dashboard" and message.chat.id == ADMIN_ID)
def admin_dashboard(message):
    users = len(list(db.collection('users').stream()))
    fresh = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()))
    sold = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'sold').stream()))
    bot.send_message(message.chat.id, f"📊 **Admin Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users}\n✅ ফ্রেশ জিমেইল: {fresh}\n🛒 সোল্ড জিমেইল: {sold}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "👥 User Management" and message.chat.id == ADMIN_ID)
def user_management_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📋 User List", callback_data="userpage_0"), InlineKeyboardButton("🔍 Search User ID", callback_data="search_user"))
    bot.send_message(message.chat.id, "ইউজার ম্যানেজমেন্ট মেনু:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("userpage_"))
def show_user_list(call):
    bot.answer_callback_query(call.id)
    page = int(call.data.split('_')[1])
    users = list(db.collection('users').stream())
    total, start = len(users), page * 10
    chunk = users[start:start+10]
    
    text = f"👥 **Total Users: {total}**\n━━━━━━━━━━━━━━\n"
    for u in chunk:
        d = u.to_dict()
        text += f"👤 {d.get('name') or 'User'} | `{u.id}` | {d.get('balance', 0)}৳\n"
        
    markup = InlineKeyboardMarkup()
    nav = []
    if start > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"userpage_{page-1}"))
    if start + 10 < total: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"userpage_{page+1}"))
    if nav: markup.add(*nav)
    markup.add(InlineKeyboardButton("📄 Export to TXT", callback_data="export_users"))
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "export_users")
def export_users_txt(call):
    bot.answer_callback_query(call.id)
    users = list(db.collection('users').stream())
    text_data = "Name | ID | Balance | Status\n" + "-"*40 + "\n"
    for u in users:
        d = u.to_dict()
        text_data += f"{d.get('name') or 'User'} | {u.id} | {d.get('balance', 0)} | {d.get('status', 'active')}\n"
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "Users.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 Full User Database")

@bot.callback_query_handler(func=lambda call: call.data == "search_user")
def ask_user_search(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔎 User ID লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, search_user_details)

def search_user_details(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    target_id = message.text.strip()
    user_ref = db.collection('users').document(target_id).get()
    
    if user_ref.exists:
        data = user_ref.to_dict()
        bought_mails = list(db.collection('active_sales').where('user_id', '==', int(target_id)).stream())
        status_icon = "✅ Active" if data.get('status') != 'banned' else "🚫 Banned"
        text = f"👤 **User Details**\n━━━━━━━━━━━━\n🆔 ID: `{target_id}`\n👤 Name: {data.get('name') or 'User'}\n💰 Balance: {data.get('balance', 0)} ৳\n🛒 Total Bought: {len(bought_mails)}\n📌 Status: {status_icon}\n"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("✏️ Edit Balance", callback_data=f"editbal_{target_id}"), InlineKeyboardButton("🚫 Ban", callback_data=f"ban_{target_id}") if data.get('status') != 'banned' else InlineKeyboardButton("✅ Unban", callback_data=f"unban_{target_id}"))
        bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=admin_menu())
        bot.send_message(message.chat.id, "অ্যাকশন সিলেক্ট করুন:", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ এই ID ডাটাবেসে নেই।", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("ban_") or call.data.startswith("unban_"))
def toggle_ban(call):
    bot.answer_callback_query(call.id)
    action, target_id = call.data.split('_')
    db.collection('users').document(target_id).update({'status': 'banned' if action == 'ban' else 'active'})
    bot.edit_message_text(f"✅ ইউজারকে {action} করা হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editbal_"))
def ask_new_balance(call):
    bot.answer_callback_query(call.id)
    target_id = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"`{target_id}` এর জন্য নতুন ব্যালেন্স অ্যামাউন্ট লিখুন:", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_new_balance, target_id)

def save_new_balance(message, target_id):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    try:
        new_bal = int(message.text)
        db.collection('users').document(target_id).update({'balance': new_bal})
        bot.send_message(message.chat.id, f"✅ ব্যালেন্স আপডেট করে {new_bal} ৳ করা হয়েছে!", reply_markup=admin_menu())
        bot.send_message(target_id, f"🎉 অ্যাডমিন আপনার ব্যালেন্স আপডেট করে {new_bal} ৳ করেছেন!")
    except: bot.send_message(message.chat.id, "❌ শুধু সংখ্যা দিন।", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "⚙️ Bot Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Payment Gateway Setup", callback_data="setup_payments"), InlineKeyboardButton("🏷 Service Price Setup", callback_data="setprice_Gmail"))
    bot.send_message(message.chat.id, "⚙️ **Bot Settings Menu**", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "setup_payments")
def payment_setup(call):
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Bkash Setup", callback_data="set_bkash"), InlineKeyboardButton("Nagad Setup", callback_data="set_nagad"), InlineKeyboardButton("Binance Setup", callback_data="set_binance"))
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    text = f"⚙️ **Payment Gateways**\n━━━━━━━━━━━━\n🟣 bKash: `{settings.get('bkash')}`\n🟠 Nagad: `{settings.get('nagad')}`\n🟡 Binance: `{settings.get('binance')}`"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def update_payment_method(call):
    bot.answer_callback_query(call.id)
    method = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"নতুন {method.capitalize()} নম্বর/ID দিন:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_payment_method, method)

def save_payment_method(message, method):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    db.collection('settings').document('payment_methods').update({method: message.text.strip()})
    bot.send_message(message.chat.id, f"✅ {method.capitalize()} আপডেট করা হয়েছে!", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "setprice_Gmail")
def ask_price(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"**OTP Service** এর জন্য নতুন প্রাইস দিন।\n(যেমন: `6`)", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_price_validity)

def save_price_validity(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    try:
        price = int(message.text.strip())
        db.collection('settings').document('prices').update({'Gmail': {'price': price, 'validity': '6 Hours'}})
        bot.send_message(message.chat.id, f"✅ প্রাইস আপডেট হয়েছে!\nPrice: {price}৳", parse_mode='Markdown', reply_markup=admin_menu())
    except: bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল। শুধু সংখ্যা দিন।", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "📢 Global Notice" and message.chat.id == ADMIN_ID)
def send_notice_start(message):
    msg = bot.send_message(message.chat.id, "সব ইউজারের কাছে যে নোটিশ পাঠাতে চান, তা লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, broadcast_notice)

def broadcast_notice(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    notice_text = f"📢 **Admin Notice:**\n\n{message.text}"
    try:
        users = db.collection('users').stream()
        count = 0
        for user in users:
            try: bot.send_message(user.id, notice_text, parse_mode='Markdown'); count += 1
            except: pass
        bot.send_message(message.chat.id, f"✅ নোটিশ সফলভাবে {count} জন ইউজারকে পাঠানো হয়েছে।", reply_markup=admin_menu())
    except: bot.send_message(message.chat.id, "নোটিশ পাঠাতে এরর হয়েছে।", reply_markup=admin_menu())

# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print("Waiting 15 seconds to kill the old instance...")
    time.sleep(15) 
    
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("Starting Verification Bot...")
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except Exception as e:
        print("Bot Polling Error:", e)
