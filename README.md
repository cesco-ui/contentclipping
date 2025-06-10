# Video Transcription Service

External service for processing videos from Google Drive and transcribing with OpenAI Whisper.

## API Endpoints

### POST /process-video
Processes a video from Google Drive URL and returns transcript via webhook.

**Request Body:**
```json
{
  "google_drive_url": "https://drive.google.com/file/d/FILE_ID/view",
  "callback_url": "https://your-n8n-instance.com/webhook/callback",
  "row_id": "unique-row-identifier",
  "openai_api_key": "sk-..."
}
```

**Response:**
```json
{
  "status": "processing",
  "message": "Video processing started",
  "row_id": "unique-row-identifier"
}
```

**Webhook Response (Success):**
```json
{
  "status": "success",
  "row_id": "unique-row-identifier", 
  "transcript": "Full video transcript...",
  "file_id": "google-drive-file-id"
}
```

### GET /
Health check endpoint.

## Deployment

1. Create GitHub repository with these files
2. Connect to Render
3. Deploy as Web Service
