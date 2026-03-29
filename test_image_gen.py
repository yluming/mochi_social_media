import requests
import json
import os

# Read API key
api_key = "sk-Qs8w7URjkJbTSNZRwuAIT7gCFiteCJPI"

# Test image generation with doubao-seedream-5-lite
url = "https://imodel.xfinfr.com/api/v1/images/generate"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

payload = {
    "model": "doubao-seedream-5-lite",
    "extParams": {
        "prompt": "一只可爱的柴犬，水彩画风格，温暖的色调",
        "width": 1024,
        "height": 1024
    }
}

print("Sending request to image generation API...")
print(f"Model: {payload['model']}")
print(f"Prompt: {payload['extParams']['prompt']}")
print()

try:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    print(f"HTTP Status: {response.status_code}")
    result = response.json()
    print(f"Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # If successful, try to download the image
    if result.get("data") and len(result["data"]) > 0:
        img_url = result["data"][0].get("url")
        if img_url:
            print(f"\nImage URL: {img_url}")
            img_response = requests.get(img_url, timeout=30)
            with open("/d/Test/Mochi_test/test_output.png", "wb") as f:
                f.write(img_response.content)
            print("Image saved to D:\Test\Mochi_test\test_output.png")
        
except Exception as e:
    print(f"Error: {e}")
