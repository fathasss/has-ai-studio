import requests, json, sys

sys.stdout.reconfigure(encoding='utf-8')

# Test 1: Initial message
r = requests.post('http://localhost:8000/chat/teamlead', json={
    "history": [
        {"role": "user", "content": "Merhaba, basit bir TODO uygulamasi yapmak istiyorum. REST API olsun."}
    ]
}, timeout=120)

print(f"=== TEST 1: Initial Message ===")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    resp = r.json().get("response", "")
    print(f"Response length: {len(resp)} chars")
    print(f"Response preview:\n{resp[:1500]}")
else:
    print(f"Error: {r.text[:500]}")

print("\n\n")

# Test 2: Follow-up message (memory test)
print("=== TEST 2: Follow-up (Memory Test) ===")
r2 = requests.post('http://localhost:8000/chat/teamlead', json={
    "history": [
        {"role": "user", "content": "Merhaba, basit bir TODO uygulamasi yapmak istiyorum. REST API olsun."},
        {"role": "assistant", "content": resp},
        {"role": "user", "content": "JWT authentication da ekle ve PostgreSQL kullanalim."}
    ]
}, timeout=120)

print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    resp2 = r2.json().get("response", "")
    print(f"Response length: {len(resp2)} chars")
    print(f"Response preview:\n{resp2[:1500]}")
    
    # Check if it remembers TODO app context
    if "todo" in resp2.lower() or "yapılacak" in resp2.lower():
        print("\n✅ MEMORY TEST PASSED: LLM remembered the TODO app context!")
    else:
        print("\n⚠️ MEMORY TEST: LLM may not have retained full context")
else:
    print(f"Error: {r2.text[:500]}")
