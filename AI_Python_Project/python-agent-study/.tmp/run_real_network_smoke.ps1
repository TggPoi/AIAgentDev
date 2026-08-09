Set-Location "d:\AI_Agent_Project\AI_Python_Project\python-agent-study"
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" ".tmp\real_network_enhanced_web_smoke.py"
exit $LASTEXITCODE
