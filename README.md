# Setup Guide

## 1 API Key
Create a `.env` file in `\backend\` containing `GEMINI_API_KEY=` followed by your own API Key.


## 2 Start the App
Firstly, navigate to this project in a powershell terminal and run `pip install -r backend/requirements.txt`. 
This will install all needed packages. 

Secondly, open up two powershell terminals. In one, open `\backend\`, in the other open `\frontend\`.
### Start backend:
In your `\backend\`command line, run this command:

`.\.venv\Scripts\python.exe -m uvicorn backend:app --reload --port 8000`

(for macOS/Linux it is: `python3 -m venv .venv && source .venv/bin/activate && uvicorn backend:app --reload --port 8000`)

### Start frontend:
Before starting your frontend, ensure that you have Node.js installed on your device.

In your `\frontend\`command line, run these two commands:

`npm install`

`npm run dev`

This should produce a link to a localhost page which you can click on.
