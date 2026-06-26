"""Fix raw newlines inside JS string literals that crash the parser"""
import os, re
HTML = os.path.join(os.path.dirname(__file__), '..', 'telegram-bot', 'miniapp', 'index.html')
c = open(HTML, encoding='utf-8').read()

# The broken strings have real newlines inside single-quoted JS strings
# Pattern: a line that ends mid-string and continues on next line

# Fix 1: crossCheckNav warning message with raw newlines
OLD1 = ("      statusEl.textContent = 'CANH BAO chenh lech:\n"
        "' + issues.join('\n"
        "');")
NEW1 = "      statusEl.textContent = 'CANH BAO chenh lech:\\n' + issues.join('\\n');"
if OLD1 in c:
    c = c.replace(OLD1, NEW1)
    print('OK fix1')
else:
    print('fix1 not found, trying alt')

# Fix 2: cross-check OK message
OLD2 = ("      statusEl.textContent += '\n"
        "Cross-check OK - du lieu khop.';")
NEW2 = "      statusEl.textContent += '\\nCross-check OK - du lieu khop.';"
if OLD2 in c:
    c = c.replace(OLD2, NEW2)
    print('OK fix2')
else:
    print('fix2 not found')

# Fix 3: cross-check error message
OLD3 = ("    statusEl.textContent += '\n"
        "(Cross-check loi: ' + e.message + ')';")
NEW3 = "    statusEl.textContent += '\\n(Cross-check loi: ' + e.message + ')';"
if OLD3 in c:
    c = c.replace(OLD3, NEW3)
    print('OK fix3')
else:
    print('fix3 not found')

# Also fix the .replace(/\./g,'') which strips all dots (wrong for decimal NAV like 15613.5)
# Should only strip commas as thousands separator
OLD4 = "    const nav = parseFloat((navInp?.value||'').replace(/,/g,'').replace(/\\./g,'').replace(/\\s/g,''));"
NEW4 = "    const nav = parseFloat((navInp?.value||'').replace(/,/g,'').replace(/\\s/g,''));"
if OLD4 in c:
    c = c.replace(OLD4, NEW4)
    print('OK fix4: removed bad dot-strip')
else:
    # Try without the escaped backslashes (they may not be doubled in the actual file)
    OLD4b = "    const nav = parseFloat((navInp?.value||'').replace(/,/g,'').replace(/./g,'').replace(/ /g,''));"
    if OLD4b in c:
        c = c.replace(OLD4b, NEW4.replace('/\\s/', '/ /'))
        print('OK fix4b')
    else:
        print('fix4 not found (check manually)')

open(HTML, 'w', encoding='utf-8').write(c)
print('Done')
