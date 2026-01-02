"""
Google Calendar API integration module
Handles OAuth flow and fetching calendar events
"""
import os
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta

# Try to load from environment, fallback to .env file
try:
    from dotenv import load_dotenv
    # Load from the backend directory
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(backend_dir, '.env')
    print(f"[OAuth] Loading .env from: {env_path}")
    load_dotenv(env_path)
except ImportError:
    print("[OAuth] python-dotenv not installed, relying on system environment variables")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

print(f"[OAuth] Configuration loaded:")
print(f"[OAuth]   CLIENT_ID: {GOOGLE_CLIENT_ID[:30] if GOOGLE_CLIENT_ID else 'NOT SET'}...")
print(f"[OAuth]   CLIENT_SECRET: {GOOGLE_CLIENT_SECRET[:10] if GOOGLE_CLIENT_SECRET else 'NOT SET'}...")
print(f"[OAuth]   FRONTEND_URL: {FRONTEND_URL}")

# OAuth endpoints
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def exchange_code_for_token(code: str, redirect_uri: str) -> Optional[Dict]:
    """
    Exchange authorization code for access token and refresh token
    
    Args:
        code: Authorization code from Google
        redirect_uri: Redirect URI (should be "postmessage" for implicit flow)
    """
    try:
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        
        print(f"\n[OAuth] ===== Starting OAuth Token Exchange =====")
        print(f"[OAuth] Redirect URI: {redirect_uri}")
        print(f"[OAuth] Client ID: {GOOGLE_CLIENT_ID[:30]}...")
        print(f"[OAuth] Client Secret: {GOOGLE_CLIENT_SECRET[:10]}..." if GOOGLE_CLIENT_SECRET else "[OAuth] Client Secret: NOT SET")
        print(f"[OAuth] Authorization Code: {code[:20]}...")
        
        response = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
        
        print(f"[OAuth] Google Response Status: {response.status_code}")
        
        if not response.ok:
            error_body = response.text
            print(f"[OAuth] ERROR - Google returned {response.status_code}")
            print(f"[OAuth] Response body: {error_body}")
            
            # Try to parse error details
            try:
                error_json = response.json()
                print(f"[OAuth] Error details: {error_json}")
            except:
                pass
        
        response.raise_for_status()
        
        result = response.json()
        print(f"[OAuth] ✓ Successfully received access token!")
        print(f"[OAuth] Token expires in: {result.get('expires_in')} seconds")
        print(f"[OAuth] Has refresh token: {bool(result.get('refresh_token'))}")
        print(f"[OAuth] ===== OAuth Token Exchange Complete =====\n")
        return result
        
    except requests.exceptions.Timeout:
        print(f"[OAuth] ✗ Request timeout while exchanging code")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[OAuth] ✗ HTTP error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[OAuth] Response status: {e.response.status_code}")
            print(f"[OAuth] Response body: {e.response.text}")
        return None
    except Exception as e:
        print(f"[OAuth] ✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None


def refresh_access_token(refresh_token: str) -> Optional[Dict]:
    """
    Use refresh token to get a new access token
    """
    try:
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        
        response = requests.post(GOOGLE_TOKEN_URL, data=data)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        print(f"Error refreshing token: {e}")
        return None


def fetch_calendar_events(
    access_token: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None
) -> List[Dict]:
    """
    Fetch calendar events from Google Calendar API
    
    Args:
        access_token: Google OAuth access token
        time_min: ISO format datetime string for start of range
        time_max: ISO format datetime string for end of range
    
    Returns:
        List of calendar events
    """
    try:
        # Default to current month if no time range provided
        if not time_min:
            now = datetime.now()
            time_min = datetime(now.year, now.month, 1).isoformat() + 'Z'
        
        if not time_max:
            now = datetime.now()
            # Get last day of current month
            next_month = now.replace(day=28) + timedelta(days=4)
            time_max = (next_month - timedelta(days=next_month.day)).replace(hour=23, minute=59, second=59).isoformat() + 'Z'
        
        print(f"\n[Calendar] Fetching events from {time_min} to {time_max}")
        
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        
        headers = {
            "Authorization": f"Bearer {access_token[:20]}...",
        }
        
        print(f"[Calendar] Calling Google Calendar API...")
        print(f"[Calendar] API URL: {GOOGLE_CALENDAR_API}")
        print(f"[Calendar] Parameters: {params}")
        
        response = requests.get(GOOGLE_CALENDAR_API, headers={"Authorization": f"Bearer {access_token}"}, params=params)
        
        print(f"[Calendar] Response status: {response.status_code}")
        
        if not response.ok:
            print(f"[Calendar] Error response: {response.text}")
        
        response.raise_for_status()
        
        data = response.json()
        print(f"[Calendar] Full API response: {data}")
        
        items = data.get("items", [])
        
        print(f"[Calendar] ✓ Retrieved {len(items)} events from Google Calendar")
        
        # Transform to our calendar event format
        events = []
        for item in items:
            start = item.get("start", {})
            start_date = start.get("dateTime") or start.get("date")
            
            # Extract just the date part (YYYY-MM-DD)
            if start_date:
                date_str = start_date.split('T')[0]
                events.append({
                    "id": f"google-{item.get('id')}",
                    "date": date_str,
                    "text": item.get("summary", "Ohne Titel"),
                    "source": "google"
                })
        
        print(f"[Calendar] ✓ Processed {len(events)} events\n")
        return events
    
    except Exception as e:
        print(f"[Calendar] ✗ Error fetching calendar events: {e}")
        import traceback
        traceback.print_exc()
        return []


def create_calendar_event(access_token: str, event_title: str, event_date: str) -> Optional[Dict]:
    """
    Create an event in Google Calendar
    
    Args:
        access_token: Google OAuth access token
        event_title: Title/description of the event
        event_date: ISO date string (YYYY-MM-DD)
    
    Returns:
        Created event data or None if failed
    """
    try:
        print(f"\n[Calendar] Creating event in Google Calendar...")
        print(f"[Calendar] Title: {event_title}")
        print(f"[Calendar] Date: {event_date}")
        event_data = {
            "summary": event_title,
            "start": {
                "date": event_date,
            },
            "end": {
                "date": event_date,
            },
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        response = requests.post(
            GOOGLE_CALENDAR_API,
            headers=headers,
            json=event_data
        )
        
        print(f"[Calendar] Response status: {response.status_code}")
        
        if not response.ok:
            print(f"[Calendar] Error creating event. Status: {response.status_code}")
            print(f"[Calendar] Error details: {response.text}")
            response.raise_for_status()
        
        created_event = response.json()
        print(f"[Calendar] ✓ Event created successfully!")
        print(f"[Calendar] Event ID: {created_event.get('id')}")
        print(f"[Calendar] Event URL: {created_event.get('htmlLink')}\n")
        
        return created_event
    
    except Exception as e:
        print(f"[Calendar] ✗ Error creating calendar event: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_user_info(access_token: str) -> Optional[Dict]:
    """
    Fetch user profile information from Google
    """
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        
        response = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers=headers
        )
        response.raise_for_status()
        
        return response.json()
    
    except Exception as e:
        print(f"Error fetching user info: {e}")
        return None


def delete_calendar_event(access_token: str, event_id: str) -> bool:
    """
    Delete an event from Google Calendar
    
    Args:
        access_token: Google OAuth access token
        event_id: The Google Calendar event ID (without 'google-' prefix)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"\n[Calendar] Deleting event from Google Calendar...")
        print(f"[Calendar] Event ID: {event_id}")
        
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        
        response = requests.delete(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers=headers
        )
        
        print(f"[Calendar] Response status: {response.status_code}")
        
        if not response.ok:
            print(f"[Calendar] Error deleting event: {response.text}")
            response.raise_for_status()
        
        print(f"[Calendar] ✓ Event deleted successfully!\n")
        return True
    
    except Exception as e:
        print(f"[Calendar] ✗ Error deleting calendar event: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_calendar_event(access_token: str, event_id: str, event_title: str, event_date: str) -> Optional[Dict]:
    """
    Update an event in Google Calendar
    
    Args:
        access_token: Google OAuth access token
        event_id: The Google Calendar event ID (without 'google-' prefix)
        event_title: New title/description of the event
        event_date: New ISO date string (YYYY-MM-DD)
    
    Returns:
        Updated event data or None if failed
    """
    try:
        print(f"\n[Calendar] Updating event in Google Calendar...")
        print(f"[Calendar] Event ID: {event_id}")
        print(f"[Calendar] Title: {event_title}")
        print(f"[Calendar] Date: {event_date}")
        
        event_data = {
            "summary": event_title,
            "start": {
                "date": event_date,
            },
            "end": {
                "date": event_date,
            },
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        response = requests.patch(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers=headers,
            json=event_data
        )
        
        print(f"[Calendar] Response status: {response.status_code}")
        
        if not response.ok:
            print(f"[Calendar] Error updating event: {response.text}")
            response.raise_for_status()
        
        updated_event = response.json()
        print(f"[Calendar] ✓ Event updated successfully!")
        print(f"[Calendar] Event ID: {updated_event.get('id')}\n")
        
        return updated_event
    
    except Exception as e:
        print(f"[Calendar] ✗ Error updating calendar event: {e}")
        import traceback
        traceback.print_exc()
        return None
