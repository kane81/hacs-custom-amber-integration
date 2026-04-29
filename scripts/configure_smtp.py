#!/usr/bin/env python3
"""Configure SMTP notifications in amber.yaml"""
import sys
import re

pkg_path = sys.argv[1]
smtp_user = sys.argv[2]

with open(pkg_path, 'r') as f:
    content = f.read()

# Already configured
if '  - name: amber_smtp' in content:
    print("already configured")
    sys.exit(0)

# Replace the entire optional email section including surrounding comment lines
commented_pattern = re.compile(
    r'  # ─── OPTIONAL: uncomment and fill in to add email.*?(?=\n  # ─── OPTIONAL: add mobile)',
    re.DOTALL
)

uncommented = (
    '  - name: amber_smtp\n'
    '    platform: smtp\n'
    '    server: !secret smtp_server\n'
    '    port: 587\n'
    '    timeout: 15\n'
    '    sender: !secret smtp_username\n'
    '    encryption: starttls\n'
    '    username: !secret smtp_username\n'
    '    password: !secret smtp_password\n'
    '    recipient:\n'
    '      - "' + smtp_user + '"\n'
    '    sender_name: "Home Assistant - Amber"\n'
)

if commented_pattern.search(content):
    content = commented_pattern.sub(uncommented, content)
    content = content.replace(
        '      - service: persistent_notification',
        '      - service: persistent_notification\n      - service: amber_smtp'
    )
    with open(pkg_path, 'w') as f:
        f.write(content)
    print("done")
else:
    print("smtp block not found in package")
    sys.exit(1)
