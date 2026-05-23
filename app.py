import cv2
import time
import os
import threading
from datetime import datetime

import google.generativeai as genai
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

GEMINI_API_KEY = "AIzaSyCaQqMIe-UIlsXiPmphrpoLlzT2X4I66Do"
CAMERA_URL = "http://192.0.0.4:8080/video"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

os.makedirs("detections", exist_ok=True)

app = FastAPI()
app.mount("/detections", StaticFiles(directory="detections"), name="detections")

status = {
    "camera": "Starting",
    "latest_image": "",
    "ai_summary": "Waiting for AI analysis...",
    "last_updated": "Not yet",
    "frame_count": 0
}


def ask_gemini():
    prompt = """
You are an AI surveillance assistant.

Analyze this surveillance situation based on continuous camera monitoring.
Explain:
1. What may be happening
2. Whether anything suspicious exists
3. Important observation

Keep it short and professional.
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Error: {e}"


def camera_worker():
    print("Starting camera worker...", flush=True)

    while True:
        cap = cv2.VideoCapture(CAMERA_URL)

        if not cap.isOpened():
            print("Camera connection failed. Retrying...", flush=True)
            status["camera"] = "Connection Failed"
            time.sleep(5)
            continue

        print("Camera connected successfully", flush=True)
        status["camera"] = "Connected"

        while True:
            ret, frame = cap.read()

            if not ret:
                print("Frame failed. Reconnecting...", flush=True)
                status["camera"] = "Reconnecting"
                cap.release()
                break

            status["frame_count"] += 1
            frame_count = status["frame_count"]

            if frame_count % 30 == 0:
                filename = "latest_frame.jpg"
                filepath = f"detections/{filename}"

                cv2.imwrite(filepath, frame)

                status["latest_image"] = f"/detections/{filename}"
                status["last_updated"] = datetime.now().strftime("%H:%M:%S")

                print(f"Saved {filepath}", flush=True)

                summary = ask_gemini()
                status["ai_summary"] = summary

                print("Gemini Summary:", summary, flush=True)

            time.sleep(0.03)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    image_html = ""

    if status["latest_image"]:
        image_html = f'<img src="{status["latest_image"]}?t={time.time()}" />'

    return f"""
    <html>
    <head>
        <title>AI Surveillance Dashboard</title>
        <meta http-equiv="refresh" content="3">
        <style>
            body {{
                background: #111827;
                color: white;
                font-family: Arial;
                padding: 30px;
            }}
            h1 {{
                color: #38bdf8;
            }}
            .card {{
                background: #1f2937;
                padding: 20px;
                border-radius: 12px;
                max-width: 900px;
            }}
            img {{
                width: 100%;
                border-radius: 10px;
                border: 2px solid #38bdf8;
                margin-top: 15px;
            }}
            .summary {{
                background: #374151;
                padding: 15px;
                border-radius: 8px;
                margin-top: 15px;
            }}
            .status {{
                color: #22c55e;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <h1>AI Surveillance Dashboard</h1>

        <div class="card">
            <p>Status: <span class="status">{status["camera"]}</span></p>
            <p>Frames Processed: {status["frame_count"]}</p>
            <p>Last Updated: {status["last_updated"]}</p>

            <div class="summary">
                <b>Gemini 2.5 Flash Summary:</b><br>
                {status["ai_summary"]}
            </div>

            {image_html}
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    thread = threading.Thread(target=camera_worker, daemon=True)
    thread.start()

    uvicorn.run(app, host="0.0.0.0", port=8000)