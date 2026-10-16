"""Roda cada arquivo de tests/ isoladamente (via pytest) e mostra um resumo PASS/FAIL."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    files = sorted((ROOT / "tests").glob("test_*.py"))
    if not files:
        print("Nenhum arquivo de teste encontrado em tests/")
        return 1
    results = []
    for f in files:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(f)],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        ok = proc.returncode == 0
        results.append((f.name, ok))
        if not ok:
            print(proc.stdout + proc.stderr)
    print("\nResumo:")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    failed = sum(1 for _, ok in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} arquivos passaram")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
