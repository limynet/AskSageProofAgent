"""
AskSage API Test Script
Test connection to AskSage API with your API key
"""
import requests
import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

def test_asksage_api():
    """Test AskSage API connection"""
    
    print("=" * 60)
    print("🧪 AskSage API Connection Test")
    print("=" * 60)
    
    # Load environment variables
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / 'configs' / '.env'
    load_dotenv(env_path)
    
    api_key = os.getenv("ASKSAGE_API_KEY")
    api_base = os.getenv("ASKSAGE_API_BASE", "https://api.asksage.ai/v1")
    model = os.getenv("ASKSAGE_MODEL", "gpt-5.1-gov")
    
    print(f"\n📋 Configuration:")
    print(f"   API Base: {api_base}")
    print(f"   Model: {model}")
    
    if not api_key or api_key == "your_asksage_api_key_here":
        print("\n❌ Error: ASKSAGE_API_KEY not configured")
        print("\nPlease set your API key:")
        print("1. Open configs/.env file")
        print("2. Set ASKSAGE_API_KEY=your_actual_api_key")
        print("3. Save the file")
        return False
    
    print(f"   API Key: {'*' * 20}{api_key[-4:]} (hidden)")
    
    print("\n📝 Sending test request...")
    
    # Test API call
    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant."
            },
            {
                "role": "user",
                "content": "Say 'AskSage API connection successful' and nothing else."
            }
        ],
        "temperature": 0.1,
        "max_tokens": 50
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"\n📊 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                result = data['choices'][0]['message']['content']
                print(f"\n✅ API Test PASSED")
                print(f"📝 Response: {result}")
                print("\n" + "=" * 60)
                print("✅ AskSage API is working correctly!")
                print("=" * 60)
                return True
            else:
                print(f"\n❌ Unexpected response format")
                print(f"Response: {data}")
                return False
        else:
            print(f"\n❌ API request failed")
            print(f"Status: {response.status_code}")
            print(f"Error: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"\n❌ Request timed out (30s)")
        return False
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection error")
        print(f"Check your internet connection and API base URL")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_asksage_api()
    sys.exit(0 if success else 1)