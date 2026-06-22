import sqlite3

def init_db():
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, status TEXT, data TEXT)''')
    conn.commit()
    conn.close()

def save_task(task_id, status, data_str):
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)", (task_id, status, data_str))
    conn.commit()
    conn.close()

def get_task(task_id):
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
    row = c.fetchone()
    conn.close()
    return row