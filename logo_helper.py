# Logo as base64 encoded string
# This avoids binary file issues with Hugging Face Spaces

def get_logo_base64():
    """Returns the Sentinel logo as a base64 encoded string"""
    # If logo file exists, read it
    try:
        import base64
        with open("assets/logo.png", "rb") as f:
            return base64.b64encode(f.read()).decode()
    except:
        # Fallback: return empty string if file not found
        return ""
