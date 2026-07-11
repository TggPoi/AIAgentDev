hello python

$env:PYTHONPATH="src" 

.\.venv\Scripts\Activate.ps1 激活虚拟环境

uvicorn fast_app.main:app --reload

测试web页面：
cd scripts\phase_15
python -m http.server 5173

http://127.0.0.1:5173/rag_agent_manual_acceptance.html