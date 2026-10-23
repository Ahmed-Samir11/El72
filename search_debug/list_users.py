import sqlite3
c = sqlite3.connect('elhaq.db')
rows = c.execute('SELECT id, phone, tier, created_at FROM users').fetchall()
print('users in DB:', len(rows))
for r in rows:
    print(' ', r)
