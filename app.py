# ============================================================
# Kr Firebase Extractor - Backend v4.3
# Base64 support + Firebase status
# ============================================================

import re
import os
import time
import base64
import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder=".")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# HOME
# ============================================================
@app.route("/")
def home():
    for name in ("index.html", "extractor.html", "Extractor.htm"):
        try:
            return send_from_directory(".", name)
        except Exception:
            continue
    return "index.html file dorakaledu."


# ============================================================
# BASE64 DECODE
# ============================================================
def try_base64_decode(text):
    """Base64 strings ni decode chesi, vatilo Firebase URLs vethuku."""
    found = set()
    # Base64 pattern: alphanumeric + / + = , length > 20
    b64_candidates = re.findall(r'[A-Za-z0-9+/=]{20,}', text)

    for b64 in b64_candidates:
        try:
            # Padding add cheyyi
            padded = b64 + "=" * (-len(b64) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")

            # Decoded text lo Firebase URLs vethuku
            for m in re.findall(
                r'https?://[a-zA-Z0-9\-_]+\.firebaseio\.com', decoded
            ):
                found.add(m)
            for m in re.findall(
                r'https?://[a-zA-Z0-9\-_]+\.firebasedatabase\.app', decoded
            ):
                found.add(m)
            for m in re.findall(
                r'https?://[a-zA-Z0-9\-_]+\.firebaseapp\.com', decoded
            ):
                found.add(m)
        except Exception:
            continue

    return found


# ============================================================
# FIREBASE EXTRACTOR
# ============================================================
def extract_firebase(html):
    firebase_urls = set()
    config = {}

    # 1) Direct patterns (plain text)
    patterns_url = [
        r'https?://[a-zA-Z0-9\-_]+\.firebaseio\.com',
        r'https?://[a-zA-Z0-9\-_]+\.firebaseapp\.com',
        r'https?://[a-zA-Z0-9\-_]+\.firebasedatabase\.app',
        r'https?://[a-zA-Z0-9\-_]+\.web\.app',
        r'https?://firestore\.googleapis\.com/v1/projects/[a-zA-Z0-9\-_]+',
    ]
    for pat in patterns_url:
        for m in re.findall(pat, html):
            firebase_urls.add(m)

    # 2) firebaseConfig keys
    config_keys = [
        "apiKey", "authDomain", "databaseURL", "projectId",
        "storageBucket", "messagingSenderId", "appId", "measurementId",
    ]
    for key in config_keys:
        pattern = r'"' + key + r'"\s*:\s*"([^"]+)"'
        m = re.search(pattern, html)
        if m:
            config[key] = m.group(1)
            if key == "databaseURL":
                firebase_urls.add(m.group(1))
            if key == "authDomain":
                firebase_urls.add("https://" + m.group(1))

    for key in config_keys:
        if key not in config:
            pattern = r"'" + key + r"'\s*:\s*'([^']+)'"
            m = re.search(pattern, html)
            if m:
                config[key] = m.group(1)

    # 3) Base64 decoded URLs (NEW)
    b64_urls = try_base64_decode(html)
    firebase_urls.update(b64_urls)

    # 4) URL query parameter lo base64 (NEW)
    # example: ?m=W3sidXJs...
    query_match = re.search(r'[?&]m=([A-Za-z0-9+/=]+)', html)
    if query_match:
        try:
            padded = query_match.group(1) + "=" * (-len(query_match.group(1)) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            for m in re.findall(
                r'https?://[a-zA-Z0-9\-_]+\.firebaseio\.com', decoded
            ):
                firebase_urls.add(m)
            for m in re.findall(
                r'https?://[a-zA-Z0-9\-_]+\.firebasedatabase\.app', decoded
            ):
                firebase_urls.add(m)
        except Exception:
            pass

    return sorted(firebase_urls), config


# ============================================================
# CHECK FIREBASE STATUS
# ============================================================
def check_firebase_status(url):
    result = {
        "status": "unknown",
        "response_time": 0,
        "data_size": 0,
        "keys": 0,
        "error": ""
    }

    if not (".firebaseio.com" in url or ".firebasedatabase.app" in url):
        result["status"] = "n/a"
        result["error"] = "Not a realtime DB"
        return result

    test_url = url.rstrip("/") + "/.json"

    try:
        start = time.time()
        r = requests.get(test_url, headers=HEADERS, timeout=8)
        elapsed = (time.time() - start) * 1000

        result["response_time"] = int(elapsed)
        result["data_size"] = len(r.content)

        if r.status_code == 200:
            text = r.text.strip()
            if text == "null" or text == "":
                result["status"] = "active"
                result["keys"] = 0
            else:
                result["status"] = "active"
                try:
                    data = r.json()
                    if isinstance(data, dict):
                        result["keys"] = len(data)
                    elif isinstance(data, list):
                        result["keys"] = len(data)
                    else:
                        result["keys"] = 1
                except Exception:
                    result["keys"] = 0
        elif r.status_code in (401, 403):
            result["status"] = "active"
            result["error"] = "Auth required"
        elif r.status_code == 404:
            result["status"] = "inactive"
            result["error"] = "Not found"
        else:
            result["status"] = "active"
            result["error"] = "HTTP " + str(r.status_code)

    except requests.exceptions.Timeout:
        result["status"] = "inactive"
        result["error"] = "Timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "inactive"
        result["error"] = "Connection failed"
    except Exception as e:
        result["status"] = "inactive"
        result["error"] = str(e)[:60]

    return result


# ============================================================
# API
# ============================================================
@app.route("/extract")
def extract():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({
            "error": "No URL provided",
            "firebase_urls": [],
            "config": {},
            "statuses": {}
        }), 400

    if not url.startswith("http"):
        url = "https://" + url

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
    except Exception as e:
        return jsonify({
            "error": f"Fetch failed: {str(e)[:80]}",
            "firebase_urls": [],
            "config": {},
            "statuses": {}
        }), 200

    # Full URL text + fetched HTML rendu pass cheyyi
    firebase_urls, config = extract_firebase(res.text + " " + url)

    statuses = {}
    for fb_url in firebase_urls:
        statuses[fb_url] = check_firebase_status(fb_url)

    return jsonify({
        "url": url,
        "firebase_urls": firebase_urls,
        "config": config,
        "statuses": statuses
    })


# ============================================================
# HEALTH
# ============================================================
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print(f"🚀 Kr Firebase Extractor running on port {port}")
    print(f"🌐 Open: http://127.0.0.1:{port}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
