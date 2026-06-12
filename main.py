import os
import json
import hmac
import hashlib
import requests
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

প্রথম মেসেজের নিয়ম:
- কাস্টমারের নাম দেখে যদি হিন্দু মনে হয় তাহলে বলো: "নমস্কার! কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- অন্য সবার ক্ষেত্রে বলো: "আসসালামু আলাইকুম! কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- পরবর্তী মেসেজে আর নিজের নাম বলবে না, সরাসরি প্রাসঙ্গিক উত্তর দেবে।

কুড়ি ফুডের পণ্য:
স্পেশাল ঘরোয়া মাংসের আচার কম্বো
- গরু, হাঁস ও মুরগির আচার — প্রতিটি ৩০০ml জার, মোট ৩টি জার (৯০০ml)
- দাম: ৯৯০ টাকা
- বৈশিষ্ট্য: সম্পূর্ণ ঘরোয়া পরিবেশে তৈরি, কোনো প্রিজারভেটিভ নেই, খাঁটি সরিষার তেল, ঐতিহ্যবাহী হাতে গুঁড়ো করা মশলা

অর্ডার নেওয়ার নিয়ম:
কাস্টমার অর্ডার করতে চাইলে মিষ্টি করে একে একে ৩টি তথ্য নাও:
১. নাম
২. মোবাইল নম্বর
৩. পুরো ঠিকানা (জেলা ও উপজেলাসহ)

সব তথ্য পেলে বলো: "আপনার অর্ডারটি নেওয়া হয়েছে! আমাদের টিম শীঘ্রই আপনার সাথে যোগাযোগ করবে। ধন্যবাদ কুড়ি ফুড বেছে নেওয়ার জন্য।"

HANDOVER নিয়ম:
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
human_handover_users: set[str] = set()
processed_message_ids: set[str] = set()  # ডাবল মেসেজ রোধে

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
        model="gemini-2.0-flash",
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
    # ── Signature check ──
    signature = request.headers.get("X-Hub-Signature", "")
    body = await request.body()

    if not verify_signature(body, signature):
        return Response(content="Invalid signature", status_code=403)

    data = json.loads(body)

    # ── Facebook এর object type check ──
    if data.get("object") != "page":
        return Response(content="Not a page event", status_code=404)

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            recipient_id = event.get("recipient", {}).get("id")

            if not sender_id:
                continue

            # ── Echo বা Page নিজের message এড়াও (ডাবল রিপ্লাই বন্ধ) ──
            msg = event.get("message", {})
            if msg.get("is_echo"):
                continue

            # ── Page নিজে sender হলে skip ──
            if sender_id == recipient_id:
                continue

            # ── Duplicate message ID check ──
            mid = msg.get("mid", "")
            if mid and mid in processed_message_ids:
                print(f"Duplicate message skipped: {mid}")
                continue
            if mid:
                processed_message_ids.add(mid)
                # Memory overflow রোধে পুরনো IDs মুছো
                if len(processed_message_ids) > 1000:
                    processed_message_ids.clear()

            text = msg.get("text", "").strip()
            if not text:
                continue

            print(f"Message from {sender_id}: {text}")

            # ── Live Agent এ থাকলে AI চুপ ──
            if sender_id in human_handover_users:
                print(f"AI paused for {sender_id}")
                continue

            # ── AI Reply ──
            try:
                reply = get_ai_reply(sender_id, text)
            except Exception as e:
                print(f"AI error: {e}")
                continue

            if needs_handover(reply):
                print(f"Handover triggered for {sender_id}")
                send_message(
                    sender_id,
                    "আপনার মেসেজটি একজন Live Agent এর কাছে ট্রান্সফার করা হচ্ছে। অনুগ্রহ করে একটু অপেক্ষা করুন।"
                )
                request_human_handover(sender_id)
                human_handover_users.add(sender_id)
            else:
                send_message(sender_id, reply)
                print(f"Reply sent: {reply[:80]}...")

    # ── সবসময় 200 OK রিটার্ন করো, নইলে Facebook বারবার retry করবে ──
    return Response(content=json.dumps({"status": "ok"}), status_code=200, media_type="application/json")

@app.post("/resume/{sender_id}")
async def resume_ai(sender_id: str):
    human_handover_users.discard(sender_id)
    conversation_history.pop(sender_id, None)
    return {"status": "resumed", "sender_id": sender_id}

@app.get("/")
async def root():
    return {"status": "running", "bot": "Kuri Food Customer Care"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
