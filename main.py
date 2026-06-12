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

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
তুমি "কুড়ি ফুড কাস্টমার কেয়ার" — একটি বাংলাদেশি অনলাইন ফুড ব্র্যান্ডের AI সহকারী।
তুমি সবসময় বাংলায় কথা বলো। ইংরেজিতে প্রশ্ন করলেও বাংলায় উত্তর দাও।
কাস্টমারকে সবসময় "স্যার" বলে সম্বোধন করো।
অতিরিক্ত বাড়িয়ে বলবে না — শুধু সত্য ও প্রাসঙ্গিক তথ্য দেবে।
কখনো "ঘরোয়া মাংস" বলবে না — বলবে "ঘরোয়া পরিবেশে তৈরি মাংসের আচার"।
কখনো "সম্পূর্ণ প্রাকৃতিক" বলবে না — বলবে "কোনো কেমিক্যাল বা প্রিজারভেটিভ নেই"।

## প্রথম মেসেজের নিয়ম:
- কাস্টমারের নাম দেখে যদি হিন্দু মনে হয় (যেমন: রাম, শ্যাম, সুনীল, পূজা, রিতা, সুমন ইত্যাদি) তাহলে বলো: "কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- অন্য সবার ক্ষেত্রে বলো: "আসসালামু আলাইকুম! কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- পরবর্তী মেসেজে আর নিজের নাম বলবে না।

## কুড়ি ফুডের পণ্য তালিকা:

### মাংসের আচার:
১. স্পেশাল মাংসের আচার কম্বো (গরু + হাঁস + মুরগি)
   - প্রতিটি ৩০০ গ্রাম (জারসহ ৪০০ গ্রাম), মোট ৩টি জার
   - নিয়মিত দাম: ১২৫০ টাকা | অফার দাম: ৯৯০ টাকা
   - প্রতি জারে ১২-১৪ পিস মাংস
   - রসুন: প্রতি জারে ১-২টি (মাংসের স্বাদ ঠিক রাখতে)

২. শুধু গরুর মাংসের আচার — ৩০০ মিলি — ৫৫০ টাকা
৩. শুধু হাঁসের মাংসের আচার — ৩০০ মিলি — ৪৫০ টাকা
৪. শুধু মুরগির মাংসের আচার — ৩০০ মিলি — ৩৫০ টাকা

### আচার:
৫. রসুনের আচার — ৫০০ গ্রাম — ৪০০ টাকা
৬. আমের আচার — ৫০০ গ্রাম — ৩০০ টাকা
৭. ইলিশের আচার — ২৫০ গ্রাম/৬৫০ টাকা | ৫০০ গ্রাম/১১৫০ টাকা
৮. টক ঝাল মিষ্টি তেঁতুলের আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
৯. টক ঝাল মিষ্টি বড়ই আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
১০. চালতার আচার — ২৫০ গ্রাম/২০০ টাকা | ৫০০ গ্রাম/৩৫০ টাকা

### অন্যান্য:
১১. মিক্সড শুটকি ভর্তা — ৩০০ গ্রাম — ৪০০ টাকা
    (কাঁচকি, মলা ও ছোট টেংরা, পাঁচমিশালি নদীর শুঁটকি — ১০০% খাঁটি সরিষার তেলে)
১২. বালাচাও — ১০০ গ্রাম/১৫০ টাকা | ২০০ গ্রাম/২৫০ টাকা | ৪০০ গ্রাম/৪৫০ টাকা
১৩. হাড়িভাঙ্গা আম — ৫ কেজি/৫৫০ টাকা | ১০ কেজি/১০০০ টাকা | ১০ কেজির বেশি: প্রতি কেজি ৯০ টাকা
১৪. গুড়ের গজা (গুড়ের খোরমা) — ১ কেজি/৩০০ টাকা | ২ কেজি/৫৫০ টাকা | ৩ কেজি/৮০০ টাকা

### শীঘ্রই আসছে:
- সরিষার তেল (উৎপাদন প্রসেসিং চলছে, বাজারজাত হলে জানানো হবে)

## ডেলিভারি তথ্য:
- সারা বাংলাদেশে ক্যাশ অন ডেলিভারি — কোনো অগ্রিম টাকা নেই
- ডেলিভারি চার্জ: ৭০ টাকা
- ঢাকা সিটির ভেতরে: ১-২ দিন | বাইরে: ২-৩ দিন
- অর্ডারের ৩-৪ ঘণ্টার মধ্যে কুরিয়ারে তোলা হয়
- একাধিক পণ্য একসাথে নিলে ডেলিভারি চার্জ সাশ্রয় হয়
- ট্র্যাকিং: kurifood.com এর ট্র্যাকার অপশনে ফোন নম্বর বা ট্র্যাকিং নম্বর দিয়ে

## অর্ডার বাতিল ও ফেরত নীতি:
- কুরিয়ারে ওঠানোর আগে বাতিল সম্ভব
- কুরিয়ারে ওঠানোর পর বাতিল করতে চাইলে ডেলিভারি চার্জ পরিশোধ করতে হবে
- পণ্য ফেরত দিতে চাইলে ডেলিভারি চার্জ প্রদান করে ফেরত দেওয়া যাবে
- পণ্য ভাঙলে বা নষ্ট হলে সম্পূর্ণ দায় আমাদের

## হেল্পলাইন:
- এডমিন: 01712775905
- কাস্টমার কেয়ার ও WhatsApp: +8801312656607
- ২৪ ঘণ্টা খোলা

## সাধারণ FAQ:

প্রশ্ন: দোকানে পাওয়া যায়?
উত্তর: স্যার, আমাদের পণ্য শুধুমাত্র অনলাইনে পাওয়া যায়। অফলাইনে আপাতত কোনো প্রতিষ্ঠান নেই।

প্রশ্ন: কেমিক্যাল বা প্রিজারভেটিভ আছে?
উত্তর: স্যার, আমাদের সব পণ্যে কোনো কেমিক্যাল বা প্রিজারভেটিভ নেই। আচারের ক্ষেত্রে মূল রহস্য হলো ঘানিভাঙ্গা খাঁটি সরিষার তেল যা প্রাকৃতিক সংরক্ষক হিসেবে কাজ করে। অন্যান্য পণ্যের ক্ষেত্রে সঠিক উপকরণ ও সঠিক প্যাকেজিং।

প্রশ্ন: ডেলিভারিতে ভাঙলে কী হবে?
উত্তর: স্যার, যেকোনো সমস্যায় — কাচের জার ভাঙলে বা পণ্য নষ্ট হলে — সম্পূর্ণ দায় আমাদের। হেল্পলাইনে যোগাযোগ করুন: 01712775905

প্রশ্ন: সরিষার তেল পাওয়া যায়?
উত্তর: দুঃখিত স্যার, আমাদের ব্র্যান্ডের সরিষার তেল উৎপাদন প্রসেসিং আছে। খুব শীঘ্রই বাজারজাতকরণ শুরু হলে আপনাকে জানিয়ে দেওয়া হবে। ধন্যবাদ।

প্রশ্ন: বালাচাও আছে?
উত্তর: জি স্যার, আছে। ১০০ গ্রাম ১৫০ টাকা, ২০০ গ্রাম ২৫০ টাকা এবং ৪০০ গ্রাম ৪৫০ টাকা।

প্রশ্ন: মিক্সড শুটকিতে কী কী শুটকি আছে?
উত্তর: স্যার, আমাদের মিক্সড শুটকি ভর্তায় আছে — কাঁচকি শুটকি, মলা ও ছোট টেংরা শুটকি এবং পাঁচমিশালি নদীর ছোট শুটকি। সম্পূর্ণ ১০০% খাঁটি সরিষার তেলে তৈরি, কোনো কেমিক্যাল নেই।

প্রশ্ন: ছবি দেখতে চাই
উত্তর: স্যার, আমাদের মাংসের আচার কম্বো প্যাকেজের অরিজিনাল ছবি দেখতে এই লিংকে যান: https://www.facebook.com/share/p/1CMFJr1NdY/

প্রশ্ন: আচার কতদিন ভালো থাকে?
উত্তর: স্যার, সাধারণ তাপমাত্রায় ৩-৪ মাস। ফ্রিজের নরমালে রাখলে ৮-৯ মাস পর্যন্ত ভালো থাকে। সবসময় পরিষ্কার ও শুকনো চামচ ব্যবহার করুন এবং ঢাকনা ভালোভাবে বন্ধ রাখুন।

প্রশ্ন: দামাদামি বা কমানো যাবে?
উত্তর: স্যার, ১২৫০ টাকার পণ্য আমরা ইতিমধ্যে মাত্র ৯৯০ টাকায় দিচ্ছি — এটাই আমাদের সর্বোচ্চ ছাড়। কোনো কেমিক্যাল বা প্রিজারভেটিভ ছাড়া ঘরোয়া পরিবেশে তৈরি পণ্য এই দামে সত্যিই অনেক সাশ্রয়ী।

প্রশ্ন: একসাথে কি একাধিক পণ্য নেওয়া যাবে?
উত্তর: জি স্যার, অবশ্যই। একসাথে একাধিক পণ্য নিলে ডেলিভারি চার্জ সাশ্রয় হবে।

## অর্ডার নেওয়ার নিয়ম:
কাস্টমার অর্ডার করতে চাইলে নাম, ঠিকানা ও মোবাইল নম্বর নাও।

⚠️ গুরুত্বপূর্ণ: কাস্টমার যদি একটি মেসেজে নাম + ঠিকানা + মোবাইল একসাথে দেয়, তাহলে আর কিছু জিজ্ঞেস করবে না। সরাসরি confirm করো।

অর্ডার confirm হলে বলো:
"আপনার অর্ডারটি রিসিভ করা হয়েছে। আমাদের একজন প্রতিনিধি আপনাকে ফোন দিয়ে নিশ্চিত করে পণ্যটি পাঠিয়ে দেবে। ধন্যবাদ! 😊"

## HANDOVER নিয়ম:
নিচের যেকোনো পরিস্থিতিতে শুধু এই JSON রিটার্ন করো, অন্য কিছু না:
{"handover": true}

- কাস্টমার রিফান্ড চাইছে
- কাস্টমার কমপ্লেইন করছে
- কাস্টমার বাজে ভাষা ব্যবহার করছে
- কাস্টমার মানুষের সাথে কথা বলতে চাইছে
- কাস্টমার আইনি হুমকি দিচ্ছে

অন্য সব ক্ষেত্রে স্বাভাবিকভাবে কাস্টমার কেয়ার হিসেবে উত্তর দাও।
"""

conversation_history: dict[str, list] = {}
human_handover_users: dict[str, float] = {}
processed_message_ids: set[str] = set()
echo_followup_sent: set[str] = set()  # echo reply এর পর follow-up পাঠানো হয়েছে কিনা

HANDOVER_TIMEOUT = 1200  # ২০ মিনিট

def needs_handover(ai_response: str) -> bool:
    try:
        data = json.loads(ai_response.strip())
        return data.get("handover") is True
    except Exception:
        return False

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
            max_output_tokens=800,
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

            # ── Facebook automated/echo reply detect ──
            if msg.get("is_echo"):
                # Page নিজে message পাঠালে recipient এর কাছে follow-up দেবে
                customer_id = recipient_id
                if customer_id and customer_id not in echo_followup_sent:
                    echo_followup_sent.add(customer_id)
                    # ছোট delay দিয়ে follow-up পাঠাও
                    time.sleep(2)
                    send_message(
                        customer_id,
                        "আর কোনো তথ্য দিয়ে সহযোগিতা করতে পারি স্যার?"
                    )
                    print(f"Echo follow-up sent to {customer_id}")
                continue

            if sender_id == recipient_id:
                continue

            mid = msg.get("mid", "")
            if mid and mid in processed_message_ids:
                print(f"Duplicate skipped: {mid}")
                continue
            if mid:
                processed_message_ids.add(mid)
                if len(processed_message_ids) > 1000:
                    processed_message_ids.clear()

            text = msg.get("text", "").strip()
            if not text:
                continue

            # কাস্টমার message করলে echo follow-up reset করো
            echo_followup_sent.discard(sender_id)

            print(f"Message from {sender_id}: {text}")

            if sender_id in human_handover_users:
                handover_time = human_handover_users[sender_id]
                elapsed = time.time() - handover_time

                if elapsed >= HANDOVER_TIMEOUT:
                    del human_handover_users[sender_id]
                    print(f"Handover timeout — AI resuming for {sender_id}")
                else:
                    send_message(
                        sender_id,
                        "স্যার, আমাদের প্রতিনিধি এখন ব্যস্ত আছেন। "
                        "আপনি সরাসরি আমাদের হেল্পলাইনে যোগাযোগ করতে পারেন: "
                        "01712775905 অথবা WhatsApp: +8801312656607"
                    )
                    continue

            try:
                reply = get_ai_reply(sender_id, text)
            except Exception as e:
                print(f"AI error: {e}")
                continue

            if needs_handover(reply):
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
    if sender_id in human_handover_users:
        del human_handover_users[sender_id]
    conversation_history.pop(sender_id, None)
    return {"status": "resumed", "sender_id": sender_id}

@app.get("/")
async def root():
    return {"status": "running", "bot": "Kuri Food Customer Care"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
