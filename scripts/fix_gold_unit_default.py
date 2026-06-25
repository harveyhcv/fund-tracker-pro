import os
HTML = os.path.join(os.path.dirname(__file__), '..', 'telegram-bot', 'miniapp', 'index.html')
c = open(HTML, encoding='utf-8').read()
old = "_goldUnit='luong'"
new = "_goldUnit='chi'"
if old in c:
    c = c.replace(old, new, 1)
    open(HTML, 'w', encoding='utf-8').write(c)
    print('OK: default goldUnit = chi')
else:
    print('not found: ' + old)
