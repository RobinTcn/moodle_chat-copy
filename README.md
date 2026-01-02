# Setup Guide

## 1 Environment Variables (.env files)

### Backend (.env in `\backend\`)
Create a `.env` file in the `\backend\` directory with the following content:

```env
# OpenAI API Key for ChatGPT functionality
OPENAI_API_KEY=your_openai_api_key_here

# Google OAuth Configuration for Calendar Integration
# Get these from: https://console.cloud.google.com/apis/credentials
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret

# Frontend URL for CORS and redirects
FRONTEND_URL=http://localhost:5173
```

### Frontend (.env in `\frontend\`)
Create a `.env` file in the `\frontend\` directory:

```env
# Google OAuth Client ID (same as backend)
VITE_GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com

# Backend API URL
VITE_BACKEND_URL=http://localhost:8000
```

## 2 Install Dependencies
Navigate to this project in a PowerShell terminal and run:

```powershell
pip install -r backend/requirements.txt
```

## 3 Start the App
Open two separate PowerShell terminals. In one, go to `\backend\`, in the other go to `\frontend\`.

### Start Backend:
In your `\backend\` terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend:app --reload --port 8000
```

(for macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate && uvicorn backend:app --reload --port 8000`)

### Start Frontend:
Before starting, ensure **Node.js** is installed.

In your `\frontend\` terminal, run:

```powershell
npm install
npm run dev
```

This will produce a localhost link (typically `http://localhost:5173`) which you can click on.