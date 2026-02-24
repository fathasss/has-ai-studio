import re

with open('core/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix QA Trigger logic
old_logic = '''                # Deterministic QA Trigger
                if tot > 0 and done == tot:'''

new_logic = '''                # Deterministic QA Trigger (Adding 1 because the current agent's job isn't marked COMPLETED yet)
                if tot > 0 and (done + 1) >= tot:'''

content = content.replace(old_logic, new_logic)

with open('core/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("QA Trigger Patched.")
