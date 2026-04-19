import requests

def check_ollama():
    try:
        response = requests.get("http://localhost:11434/")
        if response.status_code == 200:
            print("✅ Ollama is running.")
        else:
            print(f"⚠️ Ollama returned status code: {response.status_code}")
            
        # Check for models
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            print(f"Available models: {models}")
            if "llama3:latest" in models or "llama3" in models:
                print("✅ llama3 model found.")
            else:
                print("❌ llama3 model NOT found. Please run 'ollama pull llama3'")
        else:
             print("❌ Could not list models.")
             
    except Exception as e:
        print(f"❌ Error connecting to Ollama: {e}")

if __name__ == "__main__":
    check_ollama()
