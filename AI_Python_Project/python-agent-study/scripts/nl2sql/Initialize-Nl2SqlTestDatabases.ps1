param(
    [string]$RealEstateOwnerPassword = "nl2sql_real_estate_owner_test_2026",
    [string]$RealEstateReaderPassword = "nl2sql_real_estate_reader_test_2026",
    [string]$GameOwnerPassword = "nl2sql_game_owner_test_2026",
    [string]$GameReaderPassword = "nl2sql_game_reader_test_2026"
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:NL2SQL_REAL_ESTATE_OWNER_PASSWORD = $RealEstateOwnerPassword
$env:NL2SQL_REAL_ESTATE_READER_PASSWORD = $RealEstateReaderPassword
$env:NL2SQL_GAME_OWNER_PASSWORD = $GameOwnerPassword
$env:NL2SQL_GAME_READER_PASSWORD = $GameReaderPassword

& $python (Join-Path $PSScriptRoot "bootstrap_test_databases.py")
if ($LASTEXITCODE -ne 0) {
    throw "NL2SQL 测试数据库初始化失败，exit_code=$LASTEXITCODE"
}
