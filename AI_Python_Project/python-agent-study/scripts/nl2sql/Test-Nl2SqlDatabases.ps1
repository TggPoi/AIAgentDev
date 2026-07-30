$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $projectRoot "src"

if (-not $env:NL2SQL_DATABASE_URLS_JSON) {
    $env:NL2SQL_DATABASE_URLS_JSON = '{"real_estate_test":"postgresql://nl2sql_real_estate_reader:nl2sql_real_estate_reader_test_2026@127.0.0.1:5432/nl2sql_real_estate_test","game_test":"postgresql://nl2sql_game_reader:nl2sql_game_reader_test_2026@127.0.0.1:5432/nl2sql_game_test"}'
}

& $python (Join-Path $PSScriptRoot "test_real_databases.py")
if ($LASTEXITCODE -ne 0) {
    throw "NL2SQL 真实数据库测试失败，exit_code=$LASTEXITCODE"
}
