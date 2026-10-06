import os
os.environ['TURSO_DATABASE_URL'] = 'https://example.com'
os.environ['TURSO_AUTH_TOKEN'] = 'x'
from app import app

with app.test_client() as c:
    with c.session_transaction() as s:
        s['user_id'] = 1
        s['full_name'] = 'Test User'
    resp = c.post('/lesson-plan/generate', json={
        'curriculum': 'cbc',
        'subject': 'ICT',
        'class_name': 'Form 1',
        'duration': 40,
        'topic': 'Computer Basics',
        'subtopic': 'Input and output devices'
    })
    print(resp.status_code)
    print(resp.get_data(as_text=True)[:500])
