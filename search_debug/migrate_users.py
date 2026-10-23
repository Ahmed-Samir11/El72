import sqlite3
c = sqlite3.connect('elhaq.db')
cols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
print('before:', cols)
if 'name' not in cols:
    c.execute('ALTER TABLE users ADD COLUMN name VARCHAR(100) NOT NULL DEFAULT \'Customer\'')
if 'preferred_language' not in cols:
    c.execute('ALTER TABLE users ADD COLUMN preferred_language VARCHAR(10) NOT NULL DEFAULT \'en\'')
c.commit()
cols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
print('after :', cols)
