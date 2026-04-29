#!/usr/bin/env python3
"""Configure SMTP notifications in amber.yaml"""
import sys

pkg_path = sys.argv[1]
smtp_user = sys.argv[2]

with open(pkg_path, 'r') as f:
    content = f.read()

# Already configured
if '- name: amber_smtp' in content and '#' not in content.split('- name: amber_smtp')[0].split('\n')[-1]:
    print("already configured")
    sys.exit(0)

# Find and replace the commented smtp block
commented = (
    '  # Then add "- service: amber_smtp" to the group services above.\n'
    '  #\n'
    '  # - name: amber_smtp\n'
    '  #   platform: smtp\n'
    '  #   server: !secret smtp_server\n'
    '  #   port: 587\n'
    '  #   timeout: 15\n'
    '  #   sender: !secret smtp_username\n'
    '  #   encryption: starttls\n'
    '  #   username: !secret smtp_username\n'
    '  #   password: !secret smtp_password\n'
    '  #   recipient:\n'
    '  #     - "your@email.com"    # <- your email address\n'
    '  #   sender_name: "Home Assistant - Amber"'
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
    f'      - "{smtp_user}"\n'
    '    sender_name: "Home Assistant - Amber"'
)

content = content.replace(commented, uncommented)
content = content.replace(
    '      - service: persistent_notification',
    '      - service: persistent_notification\n      - service: amber_smtp'
)

with open(pkg_path, 'w') as f:
    f.write(content)
print("done")
