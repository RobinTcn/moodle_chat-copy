"""Secure credential storage using device-based encryption."""
import os
import sys
import json
import logging
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from typing import Optional


def get_credentials_dir() -> Path:
    """Get the directory where encrypted credentials are stored."""
    # Use AppData on Windows, ~/.config on Linux/Mac
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", os.path.expanduser("~")))
        cred_dir = base / "StudiBot"
    else:
        cred_dir = Path.home() / ".config" / "studibot"
    
    cred_dir.mkdir(parents=True, exist_ok=True)
    return cred_dir


def get_device_key() -> bytes:
    """Generate a device-specific encryption key.
    
    This creates a consistent key based on machine-specific data.
    The key is derived from hardware/system identifiers.
    """
    # Combine multiple system identifiers for uniqueness
    identifiers = [
        os.getenv("COMPUTERNAME", ""),  # Windows
        os.getenv("HOSTNAME", ""),       # Linux/Mac
        os.getenv("USERNAME", ""),
        str(Path.home()),
    ]
    
    # Create a stable hash from identifiers
    combined = "|".join(identifiers).encode("utf-8")
    key_material = hashlib.sha256(combined).digest()
    
    # Fernet requires a base64-encoded 32-byte key
    import base64
    return base64.urlsafe_b64encode(key_material)


def encrypt_data(data: dict) -> bytes:
    """Encrypt a dictionary to bytes using device-specific key."""
    key = get_device_key()
    cipher = Fernet(key)
    json_data = json.dumps(data)
    return cipher.encrypt(json_data.encode("utf-8"))


def decrypt_data(encrypted_bytes: bytes) -> Optional[dict]:
    """Decrypt bytes back to dictionary using device-specific key."""
    try:
        key = get_device_key()
        cipher = Fernet(key)
        json_data = cipher.decrypt(encrypted_bytes).decode("utf-8")
        return json.loads(json_data)
    except Exception as e:
        logging.error(f"Error decrypting credentials: {e}")
        return None


def save_credentials(username: str, password: str, api_key: str) -> bool:
    """Save credentials encrypted to local storage."""
    try:
        credentials = {
            "username": username,
            "password": password,
            "api_key": api_key,
        }
        encrypted = encrypt_data(credentials)
        
        cred_dir = get_credentials_dir()
        cred_file = cred_dir / "credentials.enc"
        
        with open(cred_file, "wb") as f:
            f.write(encrypted)
        
        logging.info("Credentials saved successfully.")
        return True
    except Exception as e:
        logging.error(f"Error saving credentials: {e}")
        return False


def load_credentials() -> Optional[dict]:
    """Load and decrypt credentials from local storage."""
    try:
        cred_dir = get_credentials_dir()
        cred_file = cred_dir / "credentials.enc"
        
        if not cred_file.exists():
            logging.info("No stored credentials found.")
            return None
        
        with open(cred_file, "rb") as f:
            encrypted = f.read()
        
        return decrypt_data(encrypted)
    except Exception as e:
        logging.error(f"Error loading credentials: {e}")
        return None


def delete_credentials() -> bool:
    """Delete stored credentials."""
    try:
        cred_dir = get_credentials_dir()
        cred_file = cred_dir / "credentials.enc"
        
        if cred_file.exists():
            cred_file.unlink()
            logging.info("Credentials deleted successfully.")
            return True
        
        logging.info("No credentials file to delete.")
        return True
    except Exception as e:
        logging.error(f"Error deleting credentials: {e}")
        return False
