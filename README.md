# Setup Guide

## 1 API Key
Create a `.env` file in `\backend\` containing `GEMINI_API_KEY=` followed by your own API Key.


## 2 Start the App
Firstly, navigate to this project in a powershell terminal and run `pip install -r backend/requirements.txt`. 
This will install all needed packages. 

Secondly, open up two powershell terminals. In one, open `\backend\`, in the other open `\frontend\`.
### Start backend:
In your `\backend\`command line, run these two commands:

`.\.venv\Scripts\Activate.ps1` 

`uvicorn backend:app --reload --port 8000`

### Start frontend:
In your `\frontend\`command line, run these two commands:

`npm install`

`npm run dev`
