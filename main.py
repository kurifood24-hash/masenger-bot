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

PAGE_ACCESS_TOKEN   = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN        = os.getenv("VERIFY_TOKEN")
APP_SECRET          = os.getenv("APP_SECRET")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
তুমি "সেলিম ভাই" — একজন অভিজ্ঞ ও বিশ্বস্ত বাংলাদেশি ই-কমার্স সেলসম্যান।
তুমি বাংলায় কথা বলো। কাস্টমার ইংরেজিতে লিখলে বাংলায় উত্তর দাও।

তোমার কাজের ধরন:
- কাস্টমারকে উষ্ণভাবে স্বাগত জানাও।
- পণ্যের সুবিধা সহজ ভাষায় বোঝাও।
- দাম ও অফার সম্পর্কে সৎ ও স্পষ্ট থাকো।
- কাস্টমারের সমস্যা বুঝে সঠিক পণ্য সাজেস্ট করো।
- অর্ডার নিতে সাহায্য করো (নাম, ঠিকানা, ফোন নম্বর সংগ্রহ করো)।
- কখনো মিথ্যা বলো না বা অতিরিক্ত প্রতিশ্রুতি দিও না।

আমাদের স্টোর সম্পর্কে:
- স্টোরের নাম: "BD শপিং হাউস"
- ডেলিভারি: ঢাকায় ১-২ দিন, ঢাকার বাইরে ৩-৫ দিন
- পেমেন্ট: বিকাশ, নগদ, রকেট ও ক্যাশ অন ডেলিভারি
- রিটার্ন পলিসি: পণ্য পাওয়ার ৭ দিনের মধ্যে সমস্যা হলে রিটার্ন বা রিপ্লেসমেন্ট

পণ্য তালিকা:
1. স্মার্টফোন অ্যাক্সেসরিজ: কভার, চার্জার, ইয়ারফোন (৳১৫০-৳৮০০)
2. হোম অ্যাপ্লায়েন্স: ব্লেন্ডার, মিক্সার, ফ্যান (৳৫০০-৳৩০০০)
3. ফ্যাশন: পুরুষ/মহিলা পোশাক, ব্যাগ, জুতো (৳৩০০-৳২৫০০)
4. বিউটি প্রোডাক্ট: ক্রিম, সিরাম, মেকআপ আইটেম (৳২০০-৳১৫০০)
5. কিচেন আইটেম: কুকওয়্যার, স্টোরেজ বক্স (৳২৫০-৳২০০০)

অর্ডার নেওয়ার ধাপ:
1. কাস্টমার পণ্য পছন্দ করলে নাম জিজ্ঞেস করো।
2. ডেলিভারি ঠিকানা নাও (জেলা ও উপজেলা সহ)।
3. ফোন নম্বর নাও।
4. পেমেন্ট পদ্ধতি জিজ্ঞেস করো।
5. অর্ডার কনফার্ম করে বলো: "আপনার অর্ডার নেওয়া হয়েছে, শীঘ্রই আমাদের টিম যোগাযোগ করবে।"

HANDOVER নিয়ম - নিচের যেকোনো পরিস্থিতিতে শুধু এই JSON রিটার্ন করো:
{"handover": true}

- কাস্টমার রিফান্ড চাইছে
- কাস্টমার কমপ্লেইন করছে
- কাস্টমার বাজে ভাষা ব্যবহার করছে
- কাস্টমার মানুষের সাথে কথা বলতে চাইছে
- কাস্টমার আইনি হুমকি দিচ্ছে

অন্য সব ক্ষেত্রে স্বাভাবিকভাবে সেলসম্যান হিসেবে উত্তর দাও।
"""

conversation_history: dict[str, list] = {}
human_handover_users: set[str] = set()

def needs_handover(ai_response: str) -> bool:
    try:
        data = json.loads(ai_response.strip())
        return data.get("handover") is True
    except Exception:
        return False

def request_human_handover(sender_id: str):
    url = f"https://graph.facebook.com/v18.0/me/pass_thread_control"
    payload = {
        "recipient": {"id": sender_id},
        "target_app_id": 263902037430900,
        "metadata": "Customer needs live agent support"
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    resp = requests.post(url, json=payload, params=params)
    print(f"Handover API response: {resp.status_code} - {resp.text}")

def verify_signature(payload: bytes, signature_header: str) -> bool:
    if not signature_header or not APP_SECRET:
        return True
    try:
        sha1 = hmac.new(
            APP_SECRET.encode("utf-8"), payload, hashlib.sha1
        ).hexdigest()
        expected = f"sha1={sha1}"
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        return False

def send_message(recipient_id: str, text: str):
    url = "https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": PAGE_ACCESS_TOKEN}
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": chunk},
        }
        requests.post(url, headers=headers, params=params, json=payload)

def get_ai_reply(sender_id: str, user_message: str) -> str:
    history = conversation_history.setdefault(sender_id, [])

    contents = []
    for msg in history[-20:]:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
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
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)

@app.post("/webhook")
async def handle_webhook(request: Request):
    signature = request.headers.get("X-Hub-Signature", "")
    body      = await request.body()

    if not verify_signature(body, signature):
        return Response(content="Invalid signature", status_code=403)

    data = json.loads(body)
    if data.get("object") != "page":
        return Response(content="Not a page event", status_code=404)

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue

            msg = event.get("message", {})
            if msg.get("is_echo"):
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            print(f"Message from {sender_id}: {text}")

            if sender_id in human_handover_users:
                print(f"AI paused for {sender_id}")
                continue

            reply = get_ai_reply(sender_id, text)

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

    return {"status": "ok"}

@app.post("/resume/{sender_id}")
async def resume_ai(sender_id: str):
    if sender_id in human_handover_users:
        human_handover_users.discard(sender_id)
        conversation_history.pop(sender_id, None)
        return {"status": "resumed", "sender_id": sender_id}
    return {"status": "not_in_handover", "sender_id": sender_id}

@app.get("/")
async def root():
    return {
        "status": "running",
        "bot": "BD Shopping House AI Agent",
        "handover_active_users": len(human_handover_users)
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
