hello python

$env:PYTHONPATH="src" 

uvicorn fast_app.main:app --reload

python scripts/test_rag_chat_api.py