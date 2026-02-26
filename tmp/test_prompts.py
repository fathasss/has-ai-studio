import os
import sys

# Add core to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.prompts import load_prompt

def test_prompts():
    print("Testing prompt loading logic...")
    
    # Test TeamLead Chat
    p1 = load_prompt("teamlead.json", "TM_teamlead_chat", "FALLBACK")
    if "PRINCIPAL SOFTWARE ARCHITECT" in p1:
        print("✅ TeamLead Chat loaded from MD")
    else:
        print(f"❌ TeamLead Chat failed. Content: {p1[:50]}")

    # Test DevOps Worker
    p2 = load_prompt("devops.json", "DV_devops_worker", "FALLBACK")
    if "SENIOR DEVOPS ENGINEER" in p2:
        print("✅ DevOps Worker loaded from MD")
    else:
        print(f"❌ DevOps Worker failed. Content: {p2[:50]}")
        
    # Test Fallback
    p3 = load_prompt("nonexistent.json", "key", "MY_FALLBACK")
    if p3 == "MY_FALLBACK":
        print("✅ Fallback works")
    else:
        print(f"❌ Fallback failed. Content: {p3}")

if __name__ == "__main__":
    test_prompts()
