import os
import json
import hmac
import hashlib
import requests
import time
import re
import threading
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
FB_PAGE_ID        = os.getenv("FB_PAGE_ID", "61580033922376")  # Kuri Food Page ID
ADMIN_FB_IDS      = set(x.strip() for x in os.getenv("ADMIN_FB_IDS", "").split(",") if x.strip())
BOT_APP_ID        = os.getenv("BOT_APP_ID", "")  # এই বটের Facebook App ID (ঐচ্ছিক, দিলে বটের নিজের echo আরও নিশ্চিতভাবে চেনা যায়)
AUTO_REPLY_WAIT   = float(os.getenv("AUTO_REPLY_WAIT", "6"))    # কাস্টমারের মেসেজের পর বট কত সেকেন্ড অপেক্ষা করবে
AUTO_REPLY_WINDOW = float(os.getenv("AUTO_REPLY_WINDOW", "10")) # এর মধ্যে পেজ থেকে উত্তর এলে সেটা অটো রিপ্লাই ধরা হবে

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
তুমি "কুড়ি ফুড কাস্টমার কেয়ার" — একটি বাংলাদেশি অনলাইন ফুড ব্র্যান্ডের AI সহকারী।
তুমি সবসময় বাংলায় কথা বলো। ইংরেজিতে প্রশ্ন করলেও বাংলায় উত্তর দাও।
কাস্টমারকে সবসময় "স্যার" বলে সম্বোধন করো।

## সবচেয়ে গুরুত্বপূর্ণ নিয়ম:
- শুধু যা জিজ্ঞেস করা হয়েছে তার উত্তর দাও — এক বাক্যে হলেও চলবে
- কখনো অতিরিক্ত তথ্য দেবে না — কেউ না চাইলে দেবে না
- একই প্রশ্ন বারবার করবে না
- কেউ না জিজ্ঞেস করলে পণ্যের list দেবে না
- অর্ডার confirm হওয়ার পর আর কোনো প্রশ্ন করবে না
- কাস্টমার "জি", "হ্যাঁ", "করবো", "ঠিক আছে" বললে context দেখে বুঝবে — আগের প্রশ্নের উত্তর হিসেবে নেবে
- Greeting "আসসালামু আলাইকুম" শুধু প্রথমবার দেবে — পরে আর দেবে না
- কখনো "ঘরোয়া মাংস" বলবে না — বলবে "ঘরোয়া পরিবেশে তৈরি মাংসের আচার"
- কখনো "সম্পূর্ণ প্রাকৃতিক" বলবে না — বলবে "কোনো কেমিক্যাল বা প্রিজারভেটিভ নেই"

## সরাসরি প্রশ্নের উত্তর দেওয়ার নিয়ম — অত্যন্ত গুরুত্বপূর্ণ:
⛔ কাস্টমার কোনো প্রশ্ন করলে কখনো "আপনাকে কীভাবে সহযোগিতা করতে পারি?" বা "কীভাবে সাহায্য করতে পারি?" দিয়ে উত্তর দেবে না।
⛔ কাস্টমার যদি সরাসরি কিছু জিজ্ঞেস করে — দাম, পণ্য, ডেলিভারি, যেকোনো কিছু — সেটার সরাসরি উত্তর দাও।

❌ ভুল:
Customer: গরুর আচারের দাম কত?
Bot: স্যার, আমি আপনাকে কীভাবে সহযোগিতা করতে পারি? ← এটা কখনো করবে না

✅ সঠিক:
Customer: গরুর আচারের দাম কত?
Bot: স্যার, গরুর আচার ৩০০ গ্রাম ৩৫০ টাকা।

❌ ভুল:
Customer: আচার কি কুরিয়ারে পাঠান?
Bot: জি স্যার! আপনাকে কীভাবে সহযোগিতা করতে পারি? ← এটা কখনো করবে না

✅ সঠিক:
Customer: আচার কি কুরিয়ারে পাঠান?
Bot: জি স্যার, সারা বাংলাদেশে কুরিয়ারে পাঠাই।

## পুনরাবৃত্তি প্রশ্ন এড়ানোর কঠোর নিয়ম — অত্যন্ত গুরুত্বপূর্ণ:
প্রতিটি উত্তর লেখার আগে অবশ্যই উপরে দেওয়া পুরো কথোপকথনের history মন দিয়ে পড়ো।

- History-তে যদি কোনো প্রশ্নের উত্তর কাস্টমার ইতিমধ্যে দিয়ে থাকে (নাম, ফোন, ঠিকানা, কোন পণ্য, কোন স্বাদ ইত্যাদি) — সেই প্রশ্ন আর কখনোই দ্বিতীয়বার করবে না।
- তুমি (বট) নিজে আগে যে প্রশ্ন একবার জিজ্ঞেস করেছ, সেই একই বা প্রায় একই অর্থের প্রশ্ন আর দ্বিতীয়বার করবে না।
- "আর কিছু জানতে চান?", "কীভাবে সাহায্য করতে পারি?" — এই ধরনের generic প্রশ্ন একই কথোপকথনে একবারের বেশি ব্যবহার করবে না।
- প্রতি উত্তর দেওয়ার আগে নিজেকে জিজ্ঞেস করো: "এই কথাটা/প্রশ্নটা কি আমি বা কাস্টমার ইতিমধ্যে বলেছি?" উত্তর হ্যাঁ হলে — সেটা আর বলবে না।

❌ ভুল (করা যাবে না):
Bot: আপনাকে কীভাবে সাহায্য করতে পারি?
Customer: আচার নিতে চাই → Bot: কোন আচার? → Customer: গরু → Bot: আর কিছু জানতে চান?
Customer: না → Bot: আচ্ছা, আপনাকে কীভাবে সাহায্য করতে পারি? ← ভুল! আগেই করা হয়েছে

✅ সঠিক:
Customer: না → Bot: ঠিক আছে স্যার, অর্ডারের জন্য আপনার নাম, ঠিকানা ও মোবাইল নম্বরটি দিন।

## প্রথম মেসেজের নিয়ম:
- কাস্টমার যদি প্রথম মেসেজেই নাম+ঠিকানা+মোবাইল দেয় তাহলে সালাম না দিয়ে বলো: "স্যার, আপনার তথ্য পেয়েছি। আপনি কি আমাদের স্পেশাল মাংসের আচার কম্বো (৯৯০ টাকা) নিতে চাচ্ছেন?"
- কাস্টমারের নাম দেখে যদি হিন্দু মনে হয় তাহলে বলো: "কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- অন্য সবার ক্ষেত্রে বলো: "আসসালামু আলাইকুম! কুড়ি ফুড কাস্টমার কেয়ার থেকে বলছি। আপনাকে কীভাবে সাহায্য করতে পারি?"
- পরবর্তী মেসেজে আর নিজের নাম বলবে না।

## বিজ্ঞাপন থেকে আসা কাস্টমার — অত্যন্ত গুরুত্বপূর্ণ:
- কাস্টমারের মেসেজের শুরুতে যদি [বিজ্ঞাপন: ...] লেখা থাকে, তাহলে কাস্টমার ওই বিজ্ঞাপন দেখে মেসেজ দিয়েছে।
- তখন "দাম কত?", "অর্ডার করতে চাই", "বিস্তারিত বলুন", "এটা কী?" — এমন প্রশ্নের উত্তর ওই বিজ্ঞাপনের পণ্য নিয়েই দেবে, অন্য পণ্য বলবে না।
- বিজ্ঞাপনে "৬ রকম" বা "দেড় কেজি" থাকলে → ৬ রকম আচার কম্বো।
- বিজ্ঞাপনে "৪ রকম" বা "২ কেজি" থাকলে → ৪ রকম আচার কম্বো।
- বিজ্ঞাপনে মাংস / গরু / হাঁস / মুরগি থাকলে → মাংসের আচার কম্বো।
- [বিজ্ঞাপন: ...] অংশটা কাস্টমারকে কখনো দেখাবে বা উল্লেখ করবে না।

## পণ্য নিয়ে নিয়ম:
- কেউ "৬ রকম আচার", "দেড় কেজি", "পাঁচমিশালী" বা "তেঁতুল-বড়ই মিক্সড" বললে → ৬ রকম আচার কম্বোর তথ্য দাও।
- কেউ "৪ রকম আচার" বা "২ কেজি আচার" বললে → ৪ রকম আচার কম্বোর তথ্য দাও।
- কেউ তেঁতুল / বড়ই / জলপাই / চালতার আচার বা "ফলের আচার" চাইলে কিন্তু কোন কম্বো বলেনি, এবং বিজ্ঞাপনের তথ্যও নেই → একবার জিজ্ঞেস করো: "স্যার, ৬ রকম আচার কম্বো (দেড় কেজি) নাকি ৪ রকম আচার কম্বো (২ কেজি) নিতে চান? দুটোই ৯৯০ টাকা, ডেলিভারি ফ্রি।"
- কেউ দুটোর পার্থক্য জানতে চাইলে বলো: "স্যার, ৬ রকম কম্বোতে ৬ ধরনের আচার, প্রতিটি ২৫০ গ্রাম, মোট দেড় কেজি। ৪ রকম কম্বোতে ৪ ধরনের আচার, মোট ২ কেজি। দুটোই ৯৯০ টাকা, সারা বাংলাদেশে ডেলিভারি ফ্রি। বেশি স্বাদ চেখে দেখতে চাইলে ৬ রকম, বেশি পরিমাণ চাইলে ৪ রকম।"
- কেউ "আচার" বা "দাম" জিজ্ঞেস করলে শুধু কম্বো প্যাকেজ বলো প্রথমে
- কেউ specifically "শুধু গরু" বা "শুধু হাঁস" চাইলে তখন আলাদা পণ্য বলো
- কেউ "কী কী পাওয়া যায়" জিজ্ঞেস করলে তখন সব পণ্য বলো

## কুড়ি ফুডের পণ্য তালিকা:

### প্রধান পণ্য:

**মাংসের আচার কম্বো প্যাকেজ:**
- গরু, হাঁস ও মুরগির আচার — প্রতিটি আলাদা ৩০০ গ্রামের জার, মোট ৩টি জার মিলে মোট ৯০০ গ্রাম
- নিয়মিত দাম: ১২৫০ টাকা | অফার দাম: ৯৯০ টাকা
- প্রতি জারে ১২-১৪ পিস মাংস
- রসুন: প্রতি জারে ১-২টি
- ডেলিভারি: ৭০ টাকা (সারা বাংলাদেশ)

⚠️ মাংসের আচার কম্বো ডেলিভারি — কখনো ভুল করবে না:
মাংসের আচার কম্বোতে সবসময় ৭০ টাকা ডেলিভারি চার্জ। এটা কখনো ফ্রি না।
কেউ জিজ্ঞেস করলে সরাসরি বলো: "স্যার, মাংসের আচার কম্বোতে ডেলিভারি চার্জ ৭০ টাকা, সারা বাংলাদেশ।"

**৬ রকম আচার কম্বো (ডেলিভারি ফ্রি):**
- চালতার আচার, জলপাই আচার, পাঁচমিশালী মিক্সড আচার, তেঁতুল-বড়ই মিক্সড আচার, তেঁতুলের আচার, বড়ই আচার
- প্রতিটি ২৫০ গ্রামের আলাদা বয়াম — মোট ৬টি বয়াম, মোট দেড় কেজি (১.৫ কেজি)
- দাম: ৯৯০ টাকা (৬টি মিলিয়ে)
- ডেলিভারি: সারা বাংলাদেশে সম্পূর্ণ ফ্রি
- ক্যাশ অন ডেলিভারি — পণ্য হাতে পেয়ে টাকা
- স্বাদ: টক-ঝাল-মিষ্টি, ঘরোয়া পরিবেশে তৈরি
- ওয়েবসাইটে অর্ডার: https://kurifood.com/page.php?s=achar6

**৪ রকম আচার কম্বো (ডেলিভারি ফ্রি):**
- তেঁতুলের আচার, বড়ই আচার, জলপাই আচার, চালতার আচার
- প্রতিটি ৫০০ গ্রাম — মোট ৪টি বয়াম, মোট ২ কেজি
- দাম: ৯৯০ টাকা (৪টি মিলিয়ে)
- ডেলিভারি: সারা বাংলাদেশে সম্পূর্ণ ফ্রি
- ক্যাশ অন ডেলিভারি — পণ্য হাতে পেয়ে টাকা
- স্বাদ: টক-ঝাল-মিষ্টি, ঘরোয়া পরিবেশে তৈরি
- ওয়েবসাইটে অর্ডার: https://kurifood.com/page.php?s=offer5

⚠️ ৬ রকম ও ৪ রকম আচার কম্বো নিয়ে নিয়ম:
- এই দুই কম্বোতে ডেলিভারি সবসময় ফ্রি — কখনো ৭০ টাকা বলবে না।
- জলপাই, পাঁচমিশালী মিক্সড ও তেঁতুল-বড়ই মিক্সড আচার আলাদা বিক্রির দাম তোমার জানা নেই — কেউ আলাদা দাম জানতে চাইলে বানিয়ে বলবে না। বলো: "স্যার, এগুলো এখন কম্বো অফারে পাওয়া যাচ্ছে — ৬ রকম কম্বো ৯৯০ টাকা, ডেলিভারি ফ্রি।" তারপরও আলাদা চাইলে HANDOVER করো।
- কম্বোর ভেতরের আচার বদলানো যাবে কিনা কেউ জানতে চাইলে বানিয়ে বলবে না — HANDOVER করো।

**আমের আচার কম্বো প্যাকেজ:**
- আমের আচার — ৫০০ গ্রাম
- রসুনের আচার — ৫০০ গ্রাম
- আম-রসুন-তেঁতুল মিক্সড আচার — ৫০০ গ্রাম
- মোট: ১.৫ কেজি (৩টি জারে)
- দাম: ৯৯০ টাকা
- ডেলিভারি: ৭০ টাকা (সারা বাংলাদেশ)

### আলাদা মাংসের আচার:
- শুধু গরুর মাংসের আচার — ৩০০ মিলি — ৫৫০ টাকা
- শুধু হাঁসের মাংসের আচার — ৩০০ মিলি — ৪৫০ টাকা
- শুধু মুরগির মাংসের আচার — ৩০০ মিলি — ৩৫০ টাকা

### অন্যান্য আচার:
- রসুনের আচার — ৫০০ গ্রাম/৩৯৯ টাকা | ১ কেজি/৭৪৯ টাকা
- আমের আচার — ৫০০ গ্রাম — ৪৫০ টাকা
- ইলিশের আচার — ২৫০ গ্রাম/৬৫০ টাকা | ৫০০ গ্রাম/১১৫০ টাকা
- টক ঝাল মিষ্টি তেঁতুলের আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
- টক ঝাল মিষ্টি বড়ই আচার — ২৫০ গ্রাম/২৫০ টাকা | ৫০০ গ্রাম/৪০০ টাকা
- চালতার আচার — ২৫০ গ্রাম/২০০ টাকা | ৫০০ গ্রাম/৩৫০ টাকা

### অন্যান্য পণ্য:
- ইলিশ শুটকি ভর্তা — ৩০০ গ্রাম — ৪০০ টাকা

**শুটকি ভর্তা কম্বো:**
- ইলিশ শুটকি ভর্তা — ২৫০ গ্রাম
- চিংড়ি বালাচাও — ১০০ গ্রাম
- মিক্স শুটকি ভর্তা — ২৫০ গ্রাম
- মোট: ৬০০ গ্রাম (৩টি আইটেম)
- দাম: ৯৯০ টাকা
- মেয়াদ: ৩-৪ মাস
- ডেলিভারি: ৭০ টাকা (সারা বাংলাদেশ)

**বালাচাও ট্রাইও মিনি কম্বো (ডেলিভারি ফ্রি):**
- বিফ বালাচাও ১০০গ্রাম + চিকেন বালাচাও ১০০গ্রাম + চিংড়ি বালাচাও ১০০গ্রাম = মোট ৩০০গ্রাম
- দাম: ৬৯০ টাকা | ডেলিভারি: সম্পূর্ণ ফ্রি

**বালাচাও ট্রাইও ফ্যামিলি কম্বো (ডেলিভারি ফ্রি):**
- বিফ বালাচাও ২০০গ্রাম + চিকেন বালাচাও ২০০গ্রাম + চিংড়ি বালাচাও ২০০গ্রাম = মোট ৬০০গ্রাম
- দাম: ১২৯০ টাকা | ডেলিভারি: সম্পূর্ণ ফ্রি

উভয় প্যাকেজে:
- ১০০% খাঁটি সরিষার তেলে তৈরি, কোনো প্রিজারভেটিভ নেই
- বিফ বালাচাও: হাড় ও চর্বিহীন গরুর মাংস
- চিকেন বালাচাও: হাড় ছাড়া প্রিমিয়াম মুরগির মাংস
- চিংড়ি বালাচাও: বালু ও লবণমুক্ত চিংড়ি শুঁটকি

**আলাদা বালাচাও (ডেলিভারি ৭০ টাকা):**
- চিংড়ি বালাচাও: ১০০গ্রাম = ২২০ টাকা | ২০০গ্রাম = ৪০০ টাকা
- চিকেন বালাচাও: ১০০গ্রাম = ৩০০ টাকা | ২০০গ্রাম = ৫৫০ টাকা
- বিফ বালাচাও: ১০০গ্রাম = ৫০০ টাকা | ২০০গ্রাম = ৯৫০ টাকা

⚠️ বালাচাও দাম নিয়ে নিয়ম:
- কেউ শুধু "বালাচাও দাম কত" জিজ্ঞেস করলে শুধু কম্বো প্যাকেজের দাম বলো
- কেউ specifically "চিংড়ি বালাচাও দাম" বা "চিকেন বালাচাও দাম" জিজ্ঞেস করলে তখন আলাদা দাম বলো
- সব বালাচাওর দাম একসাথে list করবে না
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
- ঢাকায়: ১-২ দিন | বাইরে: ২-৩ দিন
- ৩-৪ ঘণ্টার মধ্যে কুরিয়ারে তোলা হয়
- ট্র্যাকিং: kurifood.com

## ডেলিভারি চার্জ — অত্যন্ত গুরুত্বপূর্ণ:
⚠️ প্রতিটি পণ্যের ডেলিভারি চার্জ আলাদা — কখনো ভুল তথ্য দেবে না।

ফ্রি ডেলিভারি (এই পণ্যগুলোতে ডেলিভারি সম্পূর্ণ ফ্রি):
- বালাচাও ট্রাইও মিনি কম্বো (৩০০গ্রাম) — ডেলিভারি ফ্রি
- বালাচাও ট্রাইও ফ্যামিলি কম্বো (৬০০গ্রাম) — ডেলিভারি ফ্রি
- হাড়িভাঙ্গা আম — ডেলিভারি ফ্রি
- ৬ রকম আচার কম্বো (দেড় কেজি) — ডেলিভারি ফ্রি
- ৪ রকম আচার কম্বো (২ কেজি) — ডেলিভারি ফ্রি

৭০ টাকা ডেলিভারি চার্জ (এই পণ্যগুলোতে ৭০ টাকা চার্জ আছে):
- মাংসের আচার কম্বো — ডেলিভারি ৭০ টাকা
- আমের আচার কম্বো — ডেলিভারি ৭০ টাকা
- আলাদা মাংসের আচার (গরু/হাঁস/মুরগি) — ডেলিভারি ৭০ টাকা
- রসুনের আচার, আমের আচার, ইলিশের আচার, আলাদা তেঁতুল/বড়ই/চালতার আচার ইত্যাদি — ডেলিভারি ৭০ টাকা
- ইলিশ শুটকি ভর্তা — ডেলিভারি ৭০ টাকা
- শুটকি ভর্তা কম্বো — ডেলিভারি ৭০ টাকা
- গুড়ের গজা — ডেলিভারি ৭০ টাকা
- আলাদা বালাচাও (কম্বো ছাড়া) — ডেলিভারি ৭০ টাকা

## হেল্পলাইন:
- এডমিন: 01712775905
- WhatsApp: +8801312656607
- ২৪ ঘণ্টা খোলা

## নিয়োগ বিজ্ঞপ্তি — FAQ:
কেউ চাকরি বা নিয়োগ সম্পর্কে জিজ্ঞেস করলে বলো:
"দুঃখিত স্যার, এই মুহূর্তে আবেদনের সময়সীমা শেষ হয়ে গেছে। নতুন সার্কুলার হলে আমাদের Facebook Page এ জানানো হবে। আমাদের Page follow করে রাখুন।"

তারপরও বিস্তারিত জানতে চাইলে নিচের তথ্য দাও।
নিচের প্রশ্নের বাইরে কিছু জিজ্ঞেস করলে Live Agent এ transfer করো।

পদ ও বেতন:
- কাস্টমার সাপোর্ট এক্সিকিউটিভ — ২ জন — বেতন ১০,০০০-১৫,০০০ টাকা (মেয়েদের অগ্রাধিকার)
- প্যাকিং এন্ড লজিস্টিকস অ্যাসিস্ট্যান্ট — ২ জন — বেতন ৮,০০০-১২,০০০ টাকা

প্রশ্ন: কাজের সময় কী?
উত্তর: সকাল ৯টা থেকে বিকাল ৫টা — ৮ ঘণ্টা।

প্রশ্ন: অফিস কোথায়?
উত্তর: উপজেলা গেট, পল্লী বিদ্যুৎ অফিস সংলগ্ন, উলিপুর, কুড়িগ্রাম।

প্রশ্ন: বাসা থেকে কাজ করা যাবে?
উত্তর: না, অফিসে এসে কাজ করতে হবে।

প্রশ্ন: নতুনরা আবেদন করতে পারবে?
উত্তর: হ্যাঁ, নতুনরাও পারবে। কাজে আগ্রহ থাকলেই হবে।

প্রশ্ন: শিক্ষাগত যোগ্যতা কী লাগবে?
উত্তর: সর্বনিম্ন এসএসসি পাস।

প্রশ্ন: মোবাইল বা কম্পিউটার জানতে হবে?
উত্তর: হ্যাঁ, দুটোই জানতে হবে। ডিজিটাল মার্কেটিং জানলে অগ্রাধিকার পাবেন।

প্রশ্ন: বেতন কখন দেওয়া হয়?
উত্তর: প্রতি মাসের ৩-৬ তারিখের মধ্যে।

প্রশ্ন: ছুটি কতদিন?
উত্তর: সাপ্তাহিক ছুটি শুধু শুক্রবার।

প্রশ্ন: বোনাস আছে?
উত্তর: হ্যাঁ, বছরে একবার উৎসব বোনাস এবং কর্মদক্ষতার ভিত্তিতে ইনক্রিমেন্ট।

প্রশ্ন: চাকরি কি পার্মানেন্ট?
উত্তর: প্রথম ৬ মাস কন্ট্রাক্ট বেসিস, এরপর পার্মানেন্ট করা হবে।

প্রশ্ন: ইন্টারভিউ কীভাবে হবে?
উত্তর: সরাসরি অফিসে আসতে হবে। তারিখ পরে জানানো হবে।

প্রশ্ন: আবেদনের শেষ তারিখ কখন?
উত্তর: ২৩ জুন ২০২৬।

প্রশ্ন: কীভাবে আবেদন করব?
উত্তর: CV পাঠান — WhatsApp: 01329909002 অথবা Email: kurifood24@gmail.com

## সাধারণ FAQ:

প্রশ্ন: আচার কতদিন ভালো থাকে?
উত্তর: সাধারণ তাপমাত্রায় ৩-৪ মাস। ফ্রিজে ৮-৯ মাস।

প্রশ্ন: ডেলিভারিতে ভাঙলে কী হবে?
উত্তর: সম্পূর্ণ দায় আমাদের। হেল্পলাইনে যোগাযোগ করুন: 01712775905

প্রশ্ন: ছবি দেখতে চাই?
উত্তর: কোন পণ্যের ছবি বুঝে নিচের "ছবি পাঠানোর নিয়ম" অনুযায়ী ট্যাগ দাও। (মাংসের আচার কম্বো হলে: "স্যার, ছবি পাঠাচ্ছি 👇 [[ছবি:meatcombo]]")

প্রশ্ন: দাম কমানো যাবে?
উত্তর (মাংসের আচার কম্বো): ১২৫০ টাকার পণ্য ৯৯০ টাকায় দিচ্ছি — এটাই সর্বোচ্চ ছাড়।
উত্তর (৬ রকম / ৪ রকম আচার কম্বো): স্যার, ৯৯০ টাকায় ডেলিভারি চার্জ ছাড়াই সারা বাংলাদেশে পৌঁছে দিচ্ছি — এটাই সর্বোচ্চ ছাড়।

প্রশ্ন: ৬ রকম আচার কম্বোতে কী কী আছে?
উত্তর: স্যার, চালতা, জলপাই, পাঁচমিশালী মিক্সড, তেঁতুল-বড়ই মিক্সড, তেঁতুল ও বড়ই আচার — প্রতিটি ২৫০ গ্রাম, মোট দেড় কেজি। দাম ৯৯০ টাকা, ডেলিভারি ফ্রি।

প্রশ্ন: ৪ রকম আচার কম্বোতে কী কী আছে?
উত্তর: স্যার, তেঁতুল, বড়ই, জলপাই ও চালতার আচার — মোট ২ কেজি। দাম ৯৯০ টাকা, ডেলিভারি ফ্রি।

প্রশ্ন: আচার কি খুব টক / ঝাল?
উত্তর: স্যার, টক-ঝাল-মিষ্টি মিলিয়ে ঘরোয়া স্বাদ — খুব বেশি ঝাল না।

প্রশ্ন: ৬ রকম বা ৪ রকম কম্বোর ছবি দেখতে চাই?
উত্তর: স্যার, ছবি পাঠাচ্ছি 👇 [[ছবি:combo6]] (৪ রকম হলে [[ছবি:combo4]])

প্রশ্ন: ইলিশ শুটকি ভর্তায় কী আছে?
উত্তর: ইলিশ শুঁটকি — খাঁটি সরিষার তেলে তৈরি।

প্রশ্ন: সরিষার তেল পাওয়া যায়?
উত্তর: এখনো বাজারে আসেনি, শীঘ্রই আসবে।

প্রশ্ন: বালাচাও কম্বো প্যাকেজে কী আছে?
উত্তর: স্যার, আমাদের বালাচাও ট্রাইও কম্বো প্যাকেজে আছে বিফ বালাচাও, চিকেন বালাচাও ও চিংড়ি বালাচাও — প্রতিটি ১০০ গ্রাম করে মোট ৩০০ গ্রাম। দাম মাত্র ৬৯০ টাকা এবং ডেলিভারি সম্পূর্ণ ফ্রি।

প্রশ্ন: বালাচাও কম্বোর ছবি দেখতে চাই?
উত্তর: স্যার, ছবি পাঠাচ্ছি 👇 [[ছবি:balachao]]

প্রশ্ন: বালাচাও কম্বোতে কি ডেলিভারি ফ্রি?
উত্তর: জি স্যার, শুধুমাত্র বালাচাও ট্রাইও কম্বো প্যাকেজে ডেলিভারি সম্পূর্ণ ফ্রি। অন্য পণ্যে ৭০ টাকা ডেলিভারি চার্জ প্রযোজ্য।

প্রশ্ন: আমের দাম এত বেশি কেন?
উত্তর: স্যার, বাজারের অনেক আম অপরিপক্ক অবস্থায় তুলে ফরমালিন দিয়ে পাকানো হয়। আমাদের হাড়িভাঙ্গা আম সরাসরি রংপুরের বাগান থেকে পরিপক্ক অবস্থায় সংগ্রহ করা — ১০০% ফরমালিনমুক্ত। গড়ে মাত্র ৩-৪টিতেই ১ কেজি — তাই দাম একটু বেশি হলেও আসল স্বাদ ও নিরাপদ আম পাচ্ছেন।

## ছবি পাঠানোর নিয়ম — গুরুত্বপূর্ণ:
কাস্টমার কোনো পণ্যের ছবি দেখতে চাইলে ("ছবি দিন", "পিক দেন", "দেখতে কেমন", "ছবি দেখান", "picture" ইত্যাদি) — লিংক দেবে না।
একটা ছোট বাক্য লিখে শেষে ট্যাগ দাও, যেমন: "স্যার, ছবি পাঠাচ্ছি 👇 [[ছবি:combo6]]"
সিস্টেম নিজেই ট্যাগ সরিয়ে ছবিটা মেসেঞ্জারে পাঠিয়ে দেবে। ট্যাগ ছাড়া কখনো "ছবি পাঠাচ্ছি" লিখবে না।

ট্যাগের তালিকা (শুধু এগুলোই ব্যবহার করবে):
- combo6 = ৬ রকম আচার কম্বো
- combo4 = ৪ রকম আচার কম্বো
- meatcombo = মাংসের আচার কম্বো (গরু, হাঁস, মুরগি)
- mangocombo = আমের আচার কম্বো (আম, রসুন, মিক্সড)
- balachao = বালাচাও ট্রাইও কম্বো
- shutkicombo = শুটকি ভর্তা কম্বো
- beef = গরুর মাংসের আচার
- duck = হাঁসের মাংসের আচার
- mango = আমের আচার
- garlic = রসুনের আচার
- mixed = আম-রসুন-তেঁতুল মিক্সড আচার
- naga = নাগা মরিচের আচার
- ilishbhorta = ইলিশ শুটকি ভর্তা
- mixedbhorta = মিক্সড শুটকি ভর্তা

নিয়ম:
- একসাথে সর্বোচ্চ ২টি পণ্যের ট্যাগ দেবে, যেমন [[ছবি:combo6,combo4]]
- কোন পণ্যের ছবি চায় বোঝা না গেলে — বিজ্ঞাপনের তথ্য বা আগের কথোপকথন দেখে ঠিক করো; তাও না বুঝলে একবার জিজ্ঞেস করো কোন পণ্যের ছবি।
- তালিকায় নেই এমন পণ্যের ছবি চাইলে (যেমন মুরগির আচার, ইলিশের আচার, গুড়ের গজা, হাড়িভাঙ্গা আম) — বলো: "স্যার, এই পণ্যের ছবি এখন আমার কাছে নেই, আমাদের প্রতিনিধি পাঠিয়ে দেবে।"

## অর্ডার নেওয়ার নিয়ম — অত্যন্ত গুরুত্বপূর্ণ:

⚠️ কাস্টমার নাম + ঠিকানা + মোবাইল দিলে — আর কোনো প্রশ্ন করবে না, সাথে সাথে JSON রিটার্ন করো।
⚠️ কাস্টমার আলাদা আলাদা মেসেজে নাম, ঠিকানা, মোবাইল দিলেও — সব পেলে JSON রিটার্ন করো।
⚠️ একই তথ্য বারবার চাইবে না।

⚠️ কোন পণ্য নিচ্ছে নিশ্চিত না হলে JSON দেওয়ার আগে একবার জিজ্ঞেস করো। product-এ পণ্যের নাম হুবহু লিখবে, যেমন: "৬ রকম আচার কম্বো", "৪ রকম আচার কম্বো", "মাংসের আচার কম্বো"। price-এ পণ্যের দাম (যেমন ৯৯০) দেবে।

অর্ডার সম্পূর্ণ হলে শুধু এই JSON রিটার্ন করো, অন্য কিছু লিখবে না:
{"order_complete": true, "name": "নাম", "phone": "মোবাইল", "address": "ঠিকানা", "product": "পণ্যের নাম", "price": 0}

## AI পরিচয় নিয়ে প্রশ্ন:
কাস্টমার যদি জিজ্ঞেস করে "আপনি কি AI?", "আপনি তো AI", "আপনি রোবট?" ইত্যাদি — তাহলে বলো:
"জি স্যার, আমি কুড়ি ফুডের AI সহকারী। আপনাকে দ্রুত ও সঠিক তথ্য দিতে সবসময় প্রস্তুত। 😊 কীভাবে সাহায্য করতে পারি?"

## ডেলিভারি স্ট্যাটাস নিয়ে অত্যন্ত গুরুত্বপূর্ণ নিয়ম:
⛔ কখনো ডেলিভারি স্ট্যাটাস, ট্র্যাকিং নম্বর, বা "কবে আসবে" এই বিষয়ে কোনো তথ্য বানিয়ে বলবে না।
⛔ তোমার কাছে কোনো অর্ডারের বর্তমান অবস্থা জানার সুযোগ নেই।
⛔ কাস্টমার "পণ্য পাইনি", "কবে আসবে", "কোথায় আছে", "হাতে পাইনি", "কুরিয়ার কোথায়" বললে — কোনো উত্তর দেবে না, সাথে সাথে HANDOVER করবে।

## HANDOVER নিয়ম:
নিচের যেকোনো পরিস্থিতিতে শুধু এই JSON রিটার্ন করো:
{"handover": true}

- কাস্টমার রিফান্ড চাইছে
- কাস্টমার কমপ্লেইন করছে
- কাস্টমার বাজে ভাষা ব্যবহার করছে
- কাস্টমার মানুষের সাথে কথা বলতে চাইছে
- কাস্টমার আইনি হুমকি দিচ্ছে
- চাকরি সম্পর্কে এমন প্রশ্ন করছে যার উত্তর উপরে নেই
- কাস্টমার বলছে পণ্য পাইনি / হাতে পাইনি / ডেলিভারি আসেনি
- কাস্টমার জিজ্ঞেস করছে ডেলিভারি কবে আসবে / কখন আসবে (নির্দিষ্ট অর্ডারের বিষয়ে)
- কাস্টমার জিজ্ঞেস করছে পণ্য এখন কোথায় / কুরিয়ার কোথায়
- কাস্টমার ট্র্যাকিং নম্বর চাইছে
- কাস্টমার বলছে অর্ডার করেছে কিন্তু কোনো আপডেট নেই
"""

conversation_history: dict[str, list] = {}
admin_last_reply: dict[str, float] = {}
human_handover_users: dict[str, float] = {}
processed_message_ids: set[str] = set()
echo_followup_sent: set[str] = set()
order_done_users: set[str] = set()  # একবার অর্ডার হলে আর অর্ডার নেবে না
bot_sent_message_ids: set[str] = set()  # বটের নিজের পাঠানো message ID track করতে
ad_context: dict[str, str] = {}  # কোন বিজ্ঞাপন থেকে কাস্টমার এসেছে
last_customer_msg_time: dict[str, float] = {}  # কাস্টমারের শেষ মেসেজের সময়
auto_reply_seen: dict[str, float] = {}         # পেজের অটো রিপ্লাই কখন এসেছে

def extract_ad_title(ref: dict) -> str:
    """Click-to-Messenger বিজ্ঞাপনের referral থেকে বিজ্ঞাপনের শিরোনাম বের করা"""
    if not isinstance(ref, dict) or ref.get("source") != "ADS":
        return ""
    ctx = ref.get("ads_context_data") or {}
    title = (ctx.get("ad_title") or "").strip()
    return title or f"ad_id {ref.get('ad_id', '')}".strip()

ADMIN_PAUSE_TIMEOUT = 300  # ৫ মিনিট

# ── প্রোডাক্টের ছবি (ওয়েবসাইট থেকে) — কাস্টমার ছবি চাইলে বট সরাসরি মেসেঞ্জারে পাঠাবে ──
SITE = "https://kurifood.com/"
IMAGE_CATALOG = {
    "combo6":      {"name": "৬ রকম আচার কম্বো",         "images": [SITE+"uploads/img_6af0d117b937c.webp"], "link": SITE+"page.php?s=achar6"},
    "combo4":      {"name": "৪ রকম আচার কম্বো",         "images": [SITE+"uploads/img_6aeedb0472eec.jpg"],  "link": SITE+"page.php?s=offer5"},
    "meatcombo":   {"name": "মাংসের আচার কম্বো",         "images": [SITE+"uploads/img_6aee2bb6c21a2.jpg"],  "link": SITE+"page.php?s=main"},
    "mangocombo":  {"name": "আমের আচার কম্বো",          "images": [SITE+"uploads/img_6a4245e2e5d27.jpg"],  "link": SITE+"page.php?s=acharcombo"},
    "balachao":    {"name": "বালাচাও ট্রাইও কম্বো",       "images": [SITE+"uploads/img_6aeedbb976039.jpg"],  "link": SITE+"page.php?s=balachou"},
    "shutkicombo": {"name": "শুটকি ভর্তা কম্বো",         "images": [SITE+"uploads/img_6a57cc2093002.jpg"],  "link": SITE+"page.php?s=combo-offer"},
    "beef":        {"name": "গরুর মাংসের আচার",         "images": [SITE+"uploads/products/prod_6a424337934c7.jpg"], "link": SITE+"product.php?s=kuri-food"},
    "duck":        {"name": "হাঁসের মাংসের আচার",        "images": [SITE+"uploads/products/prod_6a4243b3a6dde.jpg"], "link": SITE+"product.php?s=duck-"},
    "mango":       {"name": "আমের আচার",               "images": [SITE+"uploads/products/prod_6a42416d503d6.jpg"], "link": SITE+"product.php?s=amerachar"},
    "garlic":      {"name": "রসুনের আচার",              "images": [SITE+"uploads/products/prod_6a2eafe21ff61.jpg", SITE+"uploads/products/prod_6a31a5a4731f2.png"], "link": SITE+"product.php?s=rosun-achar"},
    "mixed":       {"name": "আম-রসুন-তেঁতুল মিক্সড আচার",  "images": [SITE+"uploads/products/prod_6a4241eaee413.png"], "link": SITE+"product.php?s=mixedachar"},
    "naga":        {"name": "নাগা মরিচের আচার",          "images": [SITE+"uploads/products/prod_6a385b3559769.png"], "link": SITE+"product.php?s=naga-moric"},
    "ilishbhorta": {"name": "ইলিশ শুটকি ভর্তা",          "images": [SITE+"uploads/products/prod_6a54fff14ec1f.jpg"], "link": SITE+"product.php?s=hilsashutkibharta"},
    "mixedbhorta": {"name": "মিক্সড শুটকি ভর্তা",         "images": [SITE+"uploads/products/prod_6a4243a29474b.jpg"], "link": SITE+"product.php?s=mixedshutkibhorta"},
}
IMG_TAG_RE = re.compile(r"\[\[\s*ছবি\s*:\s*([A-Za-z0-9_,\s]+)\]\]")

def split_image_tags(reply: str):
    """AI-এর উত্তর থেকে [[ছবি:key]] ট্যাগ আলাদা করা"""
    keys = []
    for m in IMG_TAG_RE.finditer(reply):
        for k in m.group(1).split(","):
            k = k.strip().lower()
            if k in IMAGE_CATALOG and k not in keys:
                keys.append(k)
    clean = IMG_TAG_RE.sub("", reply).strip()
    return clean, keys[:3]

def send_image(recipient_id: str, url: str) -> bool:
    try:
        resp = requests.post("https://graph.facebook.com/v18.0/me/messages",
            params={"access_token": PAGE_ACCESS_TOKEN},
            json={"recipient": {"id": recipient_id},
                  "message": {"attachment": {"type": "image", "payload": {"url": url, "is_reusable": True}}}},
            timeout=30)
        data = resp.json()
    except Exception as e:
        data = {"error": str(e)}
    mid = data.get("message_id")
    if mid:
        bot_sent_message_ids.add(mid)
        return True
    print(f"Image send failed ({url}): {data}")
    return False

def send_product_images(recipient_id: str, keys: list):
    for k in keys:
        item = IMAGE_CATALOG[k]
        ok = False
        for url in item["images"]:
            ok = send_image(recipient_id, url) or ok
        if not ok:  # ছবি পাঠানো না গেলে লিংক দাও
            send_message(recipient_id, f"স্যার, {item['name']}-এর ছবি ও বিস্তারিত এখানে দেখুন: {item['link']}")

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
        resp = requests.post(url, params=params, json={
            "recipient": {"id": recipient_id},
            "message": {"text": chunk}
        })
        try:
            data = resp.json()
            mid = data.get("message_id")
            if mid:
                bot_sent_message_ids.add(mid)
                if len(bot_sent_message_ids) > 2000:
                    bot_sent_message_ids.clear()
                print(f"Bot sent tracked: {mid[:25]}...")
        except Exception:
            pass

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
            max_output_tokens=300,
        ),
        contents=contents,
    )

    reply = response.text
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply})
    conversation_history[sender_id] = history[-20:]
    return reply

def handle_customer_message(sender_id: str, msg: dict):
    """কাস্টমারের একটি মেসেজ প্রসেস করা (ভয়েস → টেক্সট → AI → উত্তর)"""
    # ── Voice message — Gemini দিয়ে transcription ──
    attachments = msg.get("attachments", [])
    has_audio = any(a.get("type") == "audio" for a in attachments)

    if has_audio:
        audio_att = next((a for a in attachments if a.get("type") == "audio"), None)
        audio_url = audio_att.get("payload", {}).get("url") if audio_att else None
        transcribed_text = None

        if audio_url:
            try:
                audio_resp = requests.get(audio_url, timeout=20)
                if audio_resp.status_code == 200:
                    audio_bytes = audio_resp.content
                    mime_type = audio_resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
                    tr = client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        contents=[types.Content(role="user", parts=[
                            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                            types.Part.from_text(
                                "এই অডিওতে কী বলা হয়েছে বাংলায় লিখে দাও। "
                                "শুধু transcription দাও, অন্য কিছু না।"
                            )
                        ])]
                    )
                    transcribed_text = tr.text.strip()
                    print(f"Voice transcribed for {sender_id}: {transcribed_text}")
            except Exception as e:
                print(f"Audio transcription error: {e}")

        if not transcribed_text:
            send_message(sender_id, "স্যার, ভয়েস মেসেজটা বুঝতে সমস্যা হচ্ছে। একটু টেক্সটে লিখুন।")
            return

        text = transcribed_text

    else:
        text = msg.get("text", "").strip()
        if not text:
            return

    echo_followup_sent.discard(sender_id)
    print(f"Message from {sender_id}: {text}")

    # ── Admin pause check ──
    if sender_id in admin_last_reply:
        elapsed = time.time() - admin_last_reply[sender_id]
        if elapsed < ADMIN_PAUSE_TIMEOUT:
            print(f"Admin active — bot paused for {sender_id} ({int(elapsed)}s)")
            return
        else:
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
            return
        else:
            del human_handover_users[sender_id]

    ai_text = text
    if sender_id in ad_context:
        ai_text = f"[বিজ্ঞাপন: {ad_context[sender_id]}]\n{text}"

    try:
        reply = get_ai_reply(sender_id, ai_text)
    except Exception as e:
        print(f"AI error: {e}")
        return

    order_data = is_order_complete(reply)
    if order_data and sender_id not in order_done_users:
        name    = order_data.get("name", "")
        phone   = order_data.get("phone", "")
        address = order_data.get("address", "")
        product = order_data.get("product", "")
        price   = order_data.get("price", 0)

        order_id = send_order_to_website(name, phone, address, product, price)

        # অর্ডার complete হলে flag set করো — আর অর্ডার নেবে না
        order_done_users.add(sender_id)
        echo_followup_sent.add(sender_id)

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
    elif order_data and sender_id in order_done_users:
        # ইতিমধ্যে অর্ডার হয়েছে — JSON না দেখিয়ে normal reply দাও
        send_message(sender_id, "আপনার অর্ডার আগেই রিসিভ করা হয়েছে। আমাদের প্রতিনিধি শীঘ্রই যোগাযোগ করবে। 😊")

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
        # JSON reply কাস্টমারকে না দেখাই
        if reply.strip().startswith("{") and "order_complete" in reply:
            send_message(sender_id, "আপনার অর্ডার রিসিভ করা হয়েছে। আমাদের প্রতিনিধি শীঘ্রই যোগাযোগ করবে। 😊")
        else:
            text_part, img_keys = split_image_tags(reply)
            if text_part:
                send_message(sender_id, text_part)
            if img_keys:
                send_product_images(sender_id, img_keys)
        print(f"Reply sent: {reply[:80]}...")


def delayed_handle(sender_id: str, msg: dict, t0: float):
    """কিছুক্ষণ অপেক্ষা করি — এর মধ্যে পেজের অটো রিপ্লাই এলে বট চুপ থাকবে"""
    time.sleep(AUTO_REPLY_WAIT)
    seen = auto_reply_seen.get(sender_id, 0)
    if seen >= t0:
        print(f"Page auto-reply already answered {sender_id} — bot silent for this message")
        text = msg.get("text", "").strip()
        if text:  # কথোপকথনের ইতিহাসে রাখি, যাতে পরের উত্তরে context থাকে
            h = conversation_history.setdefault(sender_id, [])
            h.append({"role": "user", "content": text})
            h.append({"role": "assistant", "content": "(পেজের অটো রিপ্লাই উত্তর দিয়েছে)"})
            conversation_history[sender_id] = h[-20:]
        return
    try:
        handle_customer_message(sender_id, msg)
    except Exception as e:
        print(f"handle_customer_message error: {e}")

def schedule_customer_message(sender_id: str, msg: dict):
    t0 = time.time()
    last_customer_msg_time[sender_id] = t0
    threading.Thread(target=delayed_handle, args=(sender_id, msg, t0), daemon=True).start()

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

            # ── এডমিনের নিজের Facebook ID হলে — বট চুপ থাকবে ──
            if sender_id in ADMIN_FB_IDS:
                print(f"Message from ADMIN ({sender_id}) — bot silent")
                continue

            msg = event.get("message", {})

            # ── বিজ্ঞাপন থেকে এসেছে কিনা (Click-to-Messenger) ──
            ref = event.get("referral") or msg.get("referral") or (event.get("postback", {}) or {}).get("referral")
            title = extract_ad_title(ref) if ref else ""
            if title and sender_id != FB_PAGE_ID:
                ad_context[sender_id] = title
                print(f"Ad referral for {sender_id}: {title}")

            if msg.get("is_echo"):
                print(f"RAW ECHO EVENT: {json.dumps(event)}")

            # ── Echo event: বটের নিজের message ID দিয়ে আলাদা করো ──
            if msg.get("is_echo"):
                echo_mid = msg.get("mid", "")
                echo_app = str(msg.get("app_id", "") or "")
                if echo_mid and echo_mid in bot_sent_message_ids:
                    print(f"Bot own echo — ignored ({echo_mid[:25]}...)")
                elif BOT_APP_ID and echo_app == BOT_APP_ID:
                    print(f"Bot own echo (app_id) — ignored ({echo_mid[:25]}...)")
                elif echo_mid:
                    customer_id = recipient_id
                    if customer_id and customer_id != FB_PAGE_ID:
                        since_customer = time.time() - last_customer_msg_time.get(customer_id, 0)
                        if since_customer <= AUTO_REPLY_WINDOW:
                            # কাস্টমারের মেসেজের কয়েক সেকেন্ডের মধ্যে পেজ থেকে উত্তর → পেজের অটো রিপ্লাই
                            auto_reply_seen[customer_id] = time.time()
                            print(f"Page auto-reply to {customer_id} ({since_customer:.1f}s, app {echo_app}) — bot will stay silent")
                        else:
                            admin_last_reply[customer_id] = time.time()
                            print(f"*** Human admin replied to {customer_id} — bot PAUSED {ADMIN_PAUSE_TIMEOUT//60} min ***")
                else:
                    print("Echo with no mid — ignored")
                continue

            # ── Page নিজে sender হলে — skip ──
            if sender_id == FB_PAGE_ID:
                continue

            mid = msg.get("mid", "")
            if mid and mid in processed_message_ids:
                continue
            if mid:
                processed_message_ids.add(mid)
                if len(processed_message_ids) > 1000:
                    processed_message_ids.clear()

            if not msg or (not msg.get("text") and not msg.get("attachments")):
                continue  # শুধু referral বা অন্য ইভেন্ট — উত্তর দেওয়ার কিছু নেই

            # ── পেজের FAQ / Ice breaker / বাটনে চাপ → ফেসবুক নিজেই উত্তর দেয়, বট চুপ ──
            if event.get("postback") or msg.get("quick_reply"):
                print(f"Button/FAQ tap from {sender_id} — left to page auto-reply")
                last_customer_msg_time[sender_id] = time.time()
                continue

            schedule_customer_message(sender_id, msg)

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
    order_done_users.discard(sender_id)
    ad_context.pop(sender_id, None)
    return {"status": "resumed", "sender_id": sender_id}

@app.get("/pause/{sender_id}/{minutes}")
async def pause_bot(sender_id: str, minutes: int = 10):
    seconds = minutes * 60
    admin_last_reply[sender_id] = time.time() + seconds - ADMIN_PAUSE_TIMEOUT
    return {"status": "paused", "sender_id": sender_id, "minutes": minutes}

@app.get("/pause/{sender_id}")
async def pause_bot_default(sender_id: str):
    admin_last_reply[sender_id] = time.time()
    return {"status": "paused", "sender_id": sender_id, "minutes": 10}

@app.get("/resubscribe")
async def resubscribe():
    url = "https://graph.facebook.com/v19.0/me/subscribed_apps"
    params = {
        "subscribed_fields": "messages,messaging_postbacks,message_echoes",
        "access_token": PAGE_ACCESS_TOKEN
    }
    resp = requests.post(url, params=params)
    return {"status_code": resp.status_code, "response": resp.json()}

@app.get("/check_subscription")
async def check_subscription():
    url = "https://graph.facebook.com/v19.0/me/subscribed_apps"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    resp = requests.get(url, params=params)
    return resp.json()

@app.get("/my-ip")
async def my_ip():
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/")
async def root():
    return {"status": "running", "bot": "Kuri Food Customer Care"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
