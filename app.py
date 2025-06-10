from flask import Flask, request, jsonify
import requests
import openai
import os
import tempfile
import threading
from urllib.parse import urlparse
import re

app = Flask(__name__)

def extract_google_drive_file_id(url):
    """Extract file ID from Google Drive URL"""
    patterns = [
        r'/file/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)',
        r'/open\?id=([a-zA-Z0-9-_]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_download_url(file_id):
    """Convert Google Drive file ID to direct download URL"""
    return f"https://drive.google.com/uc?export=download&id={file_id}"

def download_file(url, file_path):
    """Download file from URL to local path"""
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    with open(file_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return file_path

def transcribe_with_whisper(file_path, api_key):
    """Transcribe audio file using OpenAI Whisper"""
    openai.api_key = api_key
    
    with open(file_path, 'rb') as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
            response_format="json"
        )
    
    return transcript['text']

def send_webhook(callback_url, data):
    """Send results back to n8n webhook"""
    try:
        response = requests.post(callback_url, json=data)
        response.raise_for_status()
        print(f"Webhook sent successfully: {response.status_code}")
    except Exception as e:
        print(f"Webhook error: {str(e)}")

def process_video_async(google_drive_url, callback_url, row_id, openai_api_key):
    """Process video in background thread"""
    try:
        # Extract file ID from Google Drive URL
        file_id = extract_google_drive_file_id(google_drive_url)
        if not file_id:
            raise ValueError("Could not extract file ID from Google Drive URL")
        
        # Get direct download URL
        download_url = get_download_url(file_id)
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            temp_path = temp_file.name
        
        # Download file
        print(f"Downloading file: {file_id}")
        download_file(download_url, temp_path)
        
        # Transcribe with Whisper
        print(f"Transcribing file: {file_id}")
        transcript = transcribe_with_whisper(temp_path, openai_api_key)
        
        # Clean up temp file
        os.unlink(temp_path)
        
        # Send success webhook
        webhook_data = {
            "status": "success",
            "row_id": row_id,
            "transcript": transcript,
            "file_id": file_id
        }
        
        send_webhook(callback_url, webhook_data)
        
    except Exception as e:
        print(f"Error processing video: {str(e)}")
        
        # Send error webhook
        webhook_data = {
            "status": "error",
            "row_id": row_id,
            "error": str(e)
        }
        
        send_webhook(callback_url, webhook_data)

@app.route('/', methods=['GET'])
def health_check():
    return {"status": "healthy", "service": "video-transcription"}

@app.route('/process-video', methods=['POST'])
def process_video():
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['google_drive_url', 'callback_url', 'row_id', 'openai_api_key']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        google_drive_url = data['google_drive_url']
        callback_url = data['callback_url']
        row_id = data['row_id']
        openai_api_key = data['openai_api_key']
        
        # Start processing in background thread
        thread = threading.Thread(
            target=process_video_async,
            args=(google_drive_url, callback_url, row_id, openai_api_key)
        )
        thread.start()
        
        return jsonify({
            "status": "processing",
            "message": "Video processing started",
            "row_id": row_id
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
