# vanta/create_files.ps1
$files = @(
    "main.py",
    "README.md",
    "compiler/__init__.py",
    "compiler/tokens.py",
    "compiler/lexer.py",
    "compiler/ast_nodes.py",
    "compiler/parser.py",
    "compiler/typesys.py",
    "compiler/type_checker.py",
    "compiler/codegen_cpp.py",
    "compiler/driver.py",
    "runtime/vanta_runtime.hpp",
    "examples/vector_math.vnt",
    "examples/physics.vnt",
    "tests/__init__.py",
    "tests/test_lexer.py",
    "tests/test_parser.py",
    "tests/test_type_checker.py",
    "tests/test_codegen.py",
    "tests/test_integration.py",
    "docs/LANGUAGE_REFERENCE.md",
    "docs/ARCHITECTURE.md"
)
foreach ($f in $files) {
    $dir = Split-Path $f -Parent
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    New-Item -ItemType File -Path $f -Force | Out-Null
}
Write-Host "Created $($files.Count) files."