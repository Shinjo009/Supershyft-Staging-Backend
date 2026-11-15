from pathlib import Path

root = Path(__file__).resolve().parents[1] / "tests/modules/notifications"
replacements = [
    (
        "VALUES (:sk, :dn, 'whatsapp', 'test-webhook', true, false, false, false)",
        "VALUES (:sk, :dn, 'whatsapp', 'test_tpl', NULL, NULL, true, false, false, false)",
    ),
    (
        "VALUES (:sk, :dn, 'email', 'test-webhook', true, false, false, false)",
        "VALUES (:sk, :dn, 'email', NULL, 'Test', 'Test', true, false, false, false)",
    ),
    (
        "VALUES (:sk, :dn, :ch, 'test-webhook', true, false, false, false)",
        "VALUES (:sk, :dn, :ch, 'test_tpl', 'Test', 'Test', true, false, false, false)",
    ),
    (
        "VALUES (:sk, :dn, 'whatsapp', 'test-webhook', :active, false, false, :rpd)",
        "VALUES (:sk, :dn, 'whatsapp', 'test_tpl', NULL, NULL, :active, false, false, :rpd)",
    ),
]
for p in root.glob("*.py"):
    t = p.read_text(encoding="utf-8")
    n = t
    for old, new in replacements:
        n = n.replace(old, new)
    if ":ch, 'test-webhook', true, false, false," in n:
        n = n.replace(
            ":ch, 'test-webhook', true, false, false,",
            ":ch, 'test_tpl', 'Test', 'Test', true, false, false,",
        )
    if n != t:
        p.write_text(n, encoding="utf-8")
        print(p.name)