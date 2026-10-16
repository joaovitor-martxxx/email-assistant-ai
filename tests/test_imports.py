"""Pega erros de composição (import quebrado, nome errado) que py_compile não vê."""
import importlib
import pkgutil

import eaa


def test_every_module_in_the_package_imports():
    names = [m.name for m in pkgutil.iter_modules(eaa.__path__)]
    assert {"main", "pipeline", "retry", "rate_limiter", "notion_writer"} <= set(names)
    for name in names:
        importlib.import_module(f"eaa.{name}")

