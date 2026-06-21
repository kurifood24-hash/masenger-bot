import os
import json
import hmac
import hashlib
import requests
import time
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI()

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN      = os.getenv("VERIFY_TOKEN")
APP_SECRET        = os.getenv("APP_SECRET")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
KURIFOOD_API_URL  = os.getenv("KURIFOOD_API_URL", "https://kurifood.com/api_order.php")
KURIFOOD_API_KEY  = os.getenv("KURIFOOD_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
তুমি "কুড়ি ফুড কাস্টমার কেয়ার" — একটি বাংলাদেশি অনলাইন ফুড ব্র্যান্ডের AI সহকারী।
তুমি সবসময় বাংলায় কথা বলো। ইংরেজিতে প্রশ্ন করলেও বাংলায় উত্তর দাও।
কাস্টমারকে সবসময় "স্যার" বলে সম্বোধন করো।

## সবচেয়ে গুরুত্বপূর্ণ নিয়ম:
- শুধু যা জিজ্ঞেস করা হয়েছে তার উত্তর দাও — বেশি কিছু বলবে না
- ছোট ও সংক্ষিপ্ত উত্তর দাও
- কেউ না জিজ্ঞেস করলে পণ্যের list দেবে না
- কখনো "ঘরোয়া মাংস" বলবে না — বলবে "ঘরোয়া পরিবেশে তৈরি মাংসের আচার"
- কখনো "সম্পূর্ণ প্রাকৃতিক" বলবে না — বলবে "কোনো কেমিক্যাল বা প্রিজারভেটিভ নেই"

## প্রথম মেসেজের নিয়ম:
- কাস্টমার যদি প্রথম মেসেজেই নাম+ঠিকানা+মোবাইল দেয় তাহলে সালাম না দিয়ে বলো: "স্যার, আপনার তথ্য পেয়েছি। আপনি কি আমাদের স্পেশাল মাংসের আচার কম্বো (৯৯০ টাকা) নিতে চাচ্ছেন?"
- কাস্টমারের নাম দেখে যদি হিন্দু মনে হয় তাহলে বলো: "কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- অন্য সবার ক্ষেত্রে বলো: "আসসালামু আলাইকুম! কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- পরবর্তী মেসেজে আর নিজের নাম বলবে না।

## পণ্য নিয়ে নিয়ম:
- কেউ "আচার" বা "দাম" জিজ্ঞেস করলে শুধু কম্বো প্যাকেজ বলো প্রথমে
- কেউ specifically "শুধু গরু" বা "শুধু হাঁস" চাইলে তখন আলাদা পণ্য বলো
- কেউ "কী কী পাওয়া যায়" জিজ্ঞেস করলে তখন সব পণ্য বলো

## কুড়ি ফুডের পণ্য তালিকা:

### প্রধান পণ্য — মাংসের আচার কম্বো:
- গরু, হাঁস ও মুরগির আচার — প্রতিটি আলাদা ৩০০ গ্রামের জার, মোট ৩টি জার মিলে মোট ৯০০ গ্রাম
- নিয়মিত দাম: ১২৫০ টাকা | অফার দাম: ৯৯০ টাকা
- প্রতি জারে ১২-১৪ পিস মাংস
- রসুন: প্রতি জারে ১-২টি

### আলাদা মাংসের আচার:
- শুধু গরুর মাংসের আচার — ৩০০ মিলি — ৫৫০ টাকা
- শুধু হাঁসের মাংসের আচার — ৩০০ মিলি — ৪৫০ টাকা
- শুধু মুরগির মাংসের আচার — ৩০০ মিলি — ৩৫০ টাকা

### অন্যান্য আচার:
- রসুনের আচার — ৫০০ গ্রাম — ৪০০ টাকা
- আমের আচার — ৫০০ গ্রাম — ৩০০ টাকা
- ইলিশের আচার — ২৫০ গ্রাম/৬৫০ টাকা | ৫০০ গ্রাম/১১৫০ টাকা
- টক ঝাল মিষ্টি তেঁতুলের আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
- টক ঝাল মিষ্টি বড়ই আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
- চালতার আচার — ২৫০ গ্রাম/২০০ টাকা | ৫০০ গ্রাম/৩৫০ টাকা

### অন্যান্য পণ্য:
- মিক্সড শুটকি ভর্তা — ৩০০ গ্রাম — ৪০০ টাকা
- বালাচাও — ১০০ গ্রাম/১৫০ টাকা | ২০০ গ্রাম/২৫০ টাকা | ৪০০ গ্রাম/৪৫০ টাকা
- গুড়ের গজা (গুড়ের খোরমা) — ১ কেজি/৩০০ টাকা | ২ কেজি/৫৫০ টাকা | ৩ কেজি/৮০০ টাকা

### হাড়িভাঙ্গা আম (প্রি-অর্ডার চলছে):
- ১০০% ফরমালিন ও কেমিক্যালমুক্ত, সরাসরি রংপুরের বাগান থেকে
- আঁশহীন, ছোট আঁটি, রসে ভরপুর — গড়ে ৩-৪টি আমে ১ কেজি
- ১০ কেজি — ১,২০০ টাকা (ডেলিভারি ফ্রি)
- ২০ কেজি — ২,২০০ টাকা (ডেলিভারি ফ্রি) — কেজি প্রতি মাত্র ১১০ টাকা
- সম্ভাব্য ডেলিভারি: ২১-২৩ জুন
- ঢাকা, চট্টগ্রাম, কুমিল্লা, সিলেট, রংপুর — ক্যাশ অন ডেলিভারি
- অন্য জেলায় — ৫০% অগ্রিম পেমেন্ট

### শীঘ্রই আসছে:
- সরিষার তেল

## ডেলিভারি তথ্য:
- সারা বাংলাদেশে ক্যাশ অন ডেলিভারি — কোনো অগ্রিম নেই
- ডেলিভারি চার্জ: ৭০ টাকা
- ঢাকায়: ১-২ দিন | বাইরে: ২-৩ দিন
- ৩-৪ ঘণ্টার মধ্যে কুরিয়ারে তোলা হয়
- ট্র্যাকিং: kurifood.com

## হেল্পলাইন:
- এডমিন: 01712775905
- WhatsApp: +8801312656607
- ২৪ ঘণ্টা খোলা

## নিয়োগ বিজ্ঞপ্তি:
কেউ চাকরি বা নিয়োগ সম্পর্কে জিজ্ঞেস করলে বলো:
"কুড়ি ফুড উলিপুর, কুড়িগ্রামে জরুরি ভিত্তিতে নিয়োগ দিচ্ছে:
১. কাস্টমার সাপোর্ট এক্সিকিউটিভ — ২ জন — বেতন ১০,০০০-১৫,০০০ টাকা
২. প্যাকিং এন্ড লজিস্টিকস অ্যাসিস্ট্যান্ট — ২ জন — বেতন ৮,০০০-১২,০০০ টাকা
CV পাঠান: WhatsApp: 01329909002 অথবা Email: kurifood24@gmail.com"

## সাধারণ FAQ:

প্রশ্ন: আচার কতদিন ভালো থাকে?
উত্তর: সাধারণ তাপমাত্রায় ৩-৪ মাস। ফ্রিজে ৮-৯ মাস।

প্রশ্ন: ডেলিভারিতে ভাঙলে কী হবে?
উত্তর: সম্পূর্ণ দায় আমাদের। হেল্পলাইনে যোগাযোগ করুন: 01712775905

প্রশ্ন: ছবি দেখতে চাই?
উত্তর: এই লিংকে দেখুন: https://www.facebook.com/share/p/1CMFJr1NdY/

প্রশ্ন: দাম কমানো যাবে?
উত্তর: ১২৫০ টাকার পণ্য ৯৯০ টাকায় দিচ্ছি — এটাই সর্বোচ্চ ছাড়।

প্রশ্ন: মিক্সড শুটকিতে কী আছে?
উত্তর: কাঁচকি, মলা ও ছোট টেংরা, পাঁচমিশালি নদীর শুঁটকি — খাঁটি সরিষার তেলে।

প্রশ্ন: সরিষার তেল পাওয়া যায়?
উত্তর: এখনো বাজারে আসেনি, শীঘ্রই আসবে।

প্রশ্ন: আমের দাম এত বেশি কেন?
উত্তর: স্যার, বাজারের অনেক আম অপরিপক্ক অবস্থায় তুলে ফরমালিন দিয়ে পাকানো হয়। আমাদের হাড়িভাঙ্গা আম সরাসরি রংপুরের বাগান থেকে পরিপক্ক অবস্থায় সংগ্রহ করা — ১০০% ফরমালিনমুক্ত। গড়ে মাত্র ৩-৪টিতেই ১ কেজি — তাই দাম একটু বেশি হলেও আসল স্বাদ ও নিরাপদ আম পাচ্ছেন।

## অর্ডার নেওয়ার নিয়ম:
নাম, ঠিকানা ও মোবাইল নম্বর নাও।
কাস্টমার একসাথে সব দিলে আর চাইবে না।

অর্ডার সম্পূর্ণ হলে JSON রিটার্ন করো:
{"order_complete": true, "name": "নাম", "phone": "মোবাইল", "address": "ঠিকানা", "product": "পণ্যের নাম", "price": 0}

## HANDOVER নিয়ম:
{"handover": true}

- কাস্টমার রিফান্ড চাইছে
- কাস্টমার কমপ্লেইন করছে
- কাস্টমার বাজে ভাষা ব্যবহার করছে
- কাস্টমার মানুষের সাথে কথা বলতে চাইছে
- কাস্টমার আইনি হুমকি দিচ্ছে
"""

conversation_history: dict[str, list] = {}
admin_last_reply: dict[str, float] = {}
human_handover_users: dict[str, float] = {}
processed_message_ids: set[str] = set()
echo_followup_sent: set[str] = set()

ADMIN_PAUSE_TIMEOUT = 300  # ৫ মিনিট

def send_order_to_website(name, phone, address, product, price=0):
    try:
        payload = {
            "api_key": KURIFOOD_API_KEY,
            "name": name,
            "phone": phone,
            "address": address,
            "product": product,
            "quantity": 1,
            "price": price,
            "note": "Facebook Messenger অর্ডার",
        }
        r = requests.post(KURIFOOD_API_URL, json=payload, timeout=10)
        data = r.json()
        if data.get("ok"):
            return data.get("order_id")
        else:
            print(f"Order API error: {data.get('error')}")
            return None
    except Exception as e:
        print(f"Order API error: {e}")
        return None

def needs_handover(ai_response: str) -> bool:
    try:
        data = json.loads(ai_response.strip())
        return data.get("handover") is True
    except Exception:
        return False

def is_order_complete(ai_response: str):
    try:
        data = json.loads(ai_response.strip())
        if data.get("order_complete") is True:
            return data
        return None
    except Exception:
        return None

def request_human_handover(sender_id: str):
    url = "https://graph.facebook.com/v18.0/me/pass_thread_control"
    payload = {
        "recipient": {"id": sender_id},
        "target_app_id": 263902037430900,
        "metadata": "Customer needs live agent support"
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    resp = requests.post(url, json=payload, params=params)
    print(f"Handover: {resp.status_code}")

def verify_signature(payload: bytes, signature_header: str) -> bool:
    if not signature_header or not APP_SECRET:
        return True
    try:
        sha1 = hmac.new(APP_SECRET.encode("utf-8"), payload, hashlib.sha1).hexdigest()
        return hmac.compare_digest(f"sha1={sha1}", signature_header)
    except Exception:
        return False

def send_message(recipient_id: str, text: str):
    url = "https://graph.facebook.com/v18.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        requests.post(url, params=params, json={
            "recipient": {"id": recipient_id},
            "message": {"text": chunk}
        })

def get_ai_reply(sender_id: str, user_message: str) -> str:
    history = conversation_history.setdefault(sender_id, [])
    contents = []
    for msg in history[-20:]:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=500,
        ),
        contents=contents,
    )

    reply = response.text
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply})
    conversation_history[sender_id] = history[-20:]
    return reply

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        print("Webhook verified!")
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Forbidden", status_code=403)

@app.post("/webhook")
async def handle_webhook(request: Request):
    signature = request.headers.get("X-Hub-Signature", "")
    body = await request.body()

    if not verify_signature(body, signature):
        return Response(content="Invalid signature", status_code=403)

    data = json.loads(body)
    if data.get("object") != "page":
        return Response(content="Not a page event", status_code=404)

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            recipient_id = event.get("recipient", {}).get("id")

            if not sender_id:
                continue

            msg = event.get("message", {})

            # ── Echo — Admin reply করেছে ──
            if msg.get("is_echo"):
                customer_id = recipient_id
                if customer_id:
                    # Admin এর শেষ reply time update করো
                    admin_last_reply[customer_id] = time.time()
                    print(f"Admin replied to {customer_id} — bot paused for 5 min")

                    # Echo follow-up একবারই
                    if customer_id not in echo_followup_sent:
                        echo_followup_sent.add(customer_id)
                        time.sleep(2)
                        send_message(customer_id, "আর কোনো তথ্য দিয়ে সহযোগিতা করতে পারি স্যার?")
                continue

            if sender_id == recipient_id:
                continue

            # ── Duplicate check ──
            mid = msg.get("mid", "")
            if mid and mid in processed_message_ids:
                continue
            if mid:
                processed_message_ids.add(mid)
                if len(processed_message_ids) > 1000:
                    processed_message_ids.clear()

            # ── Voice message ──
            attachments = msg.get("attachments", [])
            has_audio = any(a.get("type") == "audio" for a in attachments)
            if has_audio:
                send_message(
                    sender_id,
                    "স্যার, ভয়েস মেসেজ বুঝতে পারছি না। "
                    "অনুগ্রহ করে টেক্সটে লিখুন অথবা কল করুন: 01712775905"
                )
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            echo_followup_sent.discard(sender_id)
            print(f"Message from {sender_id}: {text}")

            # ── Admin pause check ──
            # Admin শেষবার reply দেওয়ার পর ৫ মিনিট না হলে বট চুপ
            if sender_id in admin_last_reply:
                elapsed = time.time() - admin_last_reply[sender_id]
                if elapsed < ADMIN_PAUSE_TIMEOUT:
                    print(f"Admin active — bot paused for {sender_id} ({int(elapsed)}s elapsed)")
                    continue
                else:
                    # ৫ মিনিট পার — বট আবার active
                    del admin_last_reply[sender_id]
                    print(f"Admin pause ended — bot active for {sender_id}")

            # ── Handover check ──
            if sender_id in human_handover_users:
                elapsed = time.time() - human_handover_users[sender_id]
                if elapsed < ADMIN_PAUSE_TIMEOUT:
                    send_message(
                        sender_id,
                        "স্যার, আমাদের প্রতিনিধি এখন ব্যস্ত আছেন। "
                        "সরাসরি যোগাযোগ করুন: 01712775905 অথবা WhatsApp: +8801312656607"
                    )
                    continue
                else:
                    del human_handover_users[sender_id]

            try:
                reply = get_ai_reply(sender_id, text)
            except Exception as e:
                print(f"AI error: {e}")
                continue

            # ── Order complete ──
            order_data = is_order_complete(reply)
            if order_data:
                name    = order_data.get("name", "")
                phone   = order_data.get("phone", "")
                address = order_data.get("address", "")
                product = order_data.get("product", "")
                price   = order_data.get("price", 0)

                order_id = send_order_to_website(name, phone, address, product, price)

                if order_id:
                    send_message(
                        sender_id,
                        f"আপনার অর্ডারটি রিসিভ করা হয়েছে!\n"
                        f"অর্ডার নম্বর: {order_id}\n\n"
                        f"আমাদের প্রতিনিধি ফোন দিয়ে নিশ্চিত করবে। ধন্যবাদ! 😊"
                    )
                else:
                    send_message(
                        sender_id,
                        "আপনার অর্ডারটি রিসিভ করা হয়েছে। "
                        "আমাদের প্রতিনিধি ফোন দিয়ে নিশ্চিত করবে। ধন্যবাদ! 😊"
                    )

            elif needs_handover(reply):
                print(f"Handover triggered for {sender_id}")
                send_message(
                    sender_id,
                    "আপনার মেসেজটি একজন Live Agent এর কাছে ট্রান্সফার করা হচ্ছে। "
                    "অনুগ্রহ করে একটু অপেক্ষা করুন। 🙏"
                )
                request_human_handover(sender_id)
                human_handover_users[sender_id] = time.time()
            else:
                send_message(sender_id, reply)
                print(f"Reply sent: {reply[:80]}...")

    return Response(
        content=json.dumps({"status": "ok"}),
        status_code=200,
        media_type="application/json"
    )

@app.post("/resume/{sender_id}")
async def resume_ai(sender_id: str):
    human_handover_users.pop(sender_id, None)
    admin_last_reply.pop(sender_id, None)
    conversation_history.pop(sender_id, None)
    return {"status": "resumed", "sender_id": sender_id}

@app.get("/")
async def root():
    return {"status": "running", "bot": "Kuri Food Customer Care"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
