from flask import Flask, request, jsonify
import requests
import openai
import os
import tempfile
import threading
from urllib.parse import urlparse
import re
import subprocess

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
    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    
    with open(file_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return file_path

def convert_to_audio(input_path, output_path):
    """Convert video to audio format supported by Whisper"""
    try:
        # Try to convert to MP3 using ffmpeg
        subprocess.run([
            'ffmpeg', '-i', input_path, 
            '-vn',  # No video
            '-acodec', 'mp3', 
            '-ab', '192k', 
            '-ar', '22050', 
            '-y',  # Overwrite output file
            output_path
        ], check=True, capture_output=True, text=True)
        
        print(f"Successfully converted to audio: {output_path}")
        return output_path
        
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg conversion failed: {e}")
        print(f"FFmpeg stderr: {e.stderr}")
        
        # Fallback: try original file if it's already audio
        if input_path.lower().endswith(('.mp3', '.wav', '.m4a', '.flac')):
            print("Using original file as it's already audio format")
            return input_path
        else:
            raise Exception(f"Could not convert video to audio format. FFmpeg error: {e.stderr}")
    
    except FileNotFoundError:
        print("FFmpeg not found, trying original file")
        return input_path

def transcribe_with_whisper(file_path, api_key):
    """Transcribe audio file using OpenAI Whisper"""
    try:
        openai.api_key = api_key
        
        # Check file size (Whisper has 25MB limit)
        file_size = os.path.getsize(file_path)
        if file_size > 25 * 1024 * 1024:  # 25MB
            raise Exception(f"File too large for Whisper API: {file_size / (1024*1024):.1f}MB (max 25MB)")
        
        with open(file_path, 'rb') as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                response_format="json"
            )
        
        return transcript['text']
        
    except Exception as e:
        raise Exception(f"Whisper transcription failed: {str(e)}")

def send_webhook(callback_url, data):
    """Send results back to n8n webhook"""
    try:
        response = requests.post(callback_url, json=data, timeout=30)
        response.raise_for_status()
        print(f"Webhook sent successfully: {response.status_code}")
    except Exception as e:
        print(f"Webhook error: {str(e)}")

def process_video_async(google_drive_url, callback_url, row_id, openai_api_key):
    """Process video in background thread"""
    try:
        print(f"Starting processing for row_id: {row_id}")
        
        # Extract file ID from Google Drive URL
        file_id = extract_google_drive_file_id(google_drive_url)
        if not file_id:
            raise ValueError("Could not extract file ID from Google Drive URL")
        
        print(f"Extracted file ID: {file_id}")
        
        # Get direct download URL
        download_url = get_download_url(file_id)
        
        # Create temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as temp_file:
            temp_path = temp_file.name
        
        audio_path = temp_path.replace('.tmp', '.mp3')
        
        try:
            # Download file
            print(f"Downloading file from Google Drive...")
            download_file(download_url, temp_path)
            print(f"Download completed: {os.path.getsize(temp_path)} bytes")
            
            # Convert to audio format
            print(f"Converting to audio format...")
            final_audio_path = convert_to_audio(temp_path, audio_path)
            
            # Transcribe with Whisper
            print(f"Starting transcription...")
            transcript = transcribe_with_whisper(final_audio_path, openai_api_key)
            print(f"Transcription completed: {len(transcript)} characters")
            
            # Send success webhook
            webhook_data = {
                "status": "success",
                "row_id": row_id,
                "transcript": transcript,
                "file_id": file_id
            }
            
            send_webhook(callback_url, webhook_data)
            print(f"Success webhook sent for row_id: {row_id}")
            
        finally:
            # Clean up temp files
            for file_path in [temp_path, audio_path]:
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                except:
                    pass
        
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
    return {"status": "healthy", "service": "video-transcription", "version": "1.1"}

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
        
        print(f"Received processing request for row_id: {row_id}")
        print(f"Google Drive URL: {google_drive_url}")
        print(f"Callback URL: {callback_url}")
        
        # Start processing in background thread
        thread = threading.Thread(
            target=process_video_async,
            args=(google_drive_url, callback_url, row_id, openai_api_key)
        )
        thread.daemon = True  # Thread will die when main program exits
        thread.start()
        
        return jsonify({
            "status": "processing",
            "message": "Video processing started",
            "row_id": row_id
        })
        
    except Exception as e:
        print(f"Error in process_video endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
