from __future__ import annotations

import sys
from types import ModuleType
from typing import Any


class _AutoStubModule(ModuleType):
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - dynamic access
        if name.startswith('__'):
            raise AttributeError(name)
        stub_class = type(name, (), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, stub_class)
        return stub_class


def install_qt_stubs() -> None:
    if 'PyQt5' in sys.modules:
        return

    pyqt_root = ModuleType('PyQt5')
    qt_core = _AutoStubModule('PyQt5.QtCore')
    qt_widgets = _AutoStubModule('PyQt5.QtWidgets')
    qt_gui = _AutoStubModule('PyQt5.QtGui')

    class _QtNamespace:
        UserRole = 0x0100

        def __getattr__(self, attr: str) -> int:
            return 0

    qt_core.Qt = _QtNamespace()

    sys.modules['PyQt5'] = pyqt_root
    sys.modules['PyQt5.QtCore'] = qt_core
    sys.modules['PyQt5.QtWidgets'] = qt_widgets
    sys.modules['PyQt5.QtGui'] = qt_gui

    pyqt_root.QtCore = qt_core
    pyqt_root.QtWidgets = qt_widgets
    pyqt_root.QtGui = qt_gui


def install_yaml_stub() -> None:
    if 'yaml' in sys.modules:
        return

    yaml_stub = ModuleType('yaml')

    def _default_load(*_args: Any, **_kwargs: Any) -> Any:
        return {}

    def _default_dump(*_args: Any, **_kwargs: Any) -> str:
        return ''

    yaml_stub.safe_load = _default_load  # type: ignore[attr-defined]
    yaml_stub.load = _default_load  # type: ignore[attr-defined]
    yaml_stub.safe_dump = _default_dump  # type: ignore[attr-defined]
    yaml_stub.dump = _default_dump  # type: ignore[attr-defined]
    yaml_stub.SafeDumper = type('SafeDumper', (), {})  # type: ignore[attr-defined]
    yaml_stub.SafeLoader = type('SafeLoader', (), {})  # type: ignore[attr-defined]

    sys.modules['yaml'] = yaml_stub


def install_numpy_stub() -> None:
    if 'numpy' in sys.modules:
        return

    numpy_stub = ModuleType('numpy')

    class _Integer(int):
        pass

    class _Floating(float):
        pass

    numpy_stub.integer = _Integer  # type: ignore[attr-defined]
    numpy_stub.floating = _Floating  # type: ignore[attr-defined]
    numpy_stub.bool_ = bool  # type: ignore[attr-defined]
    numpy_stub.isscalar = staticmethod(lambda value: isinstance(value, (int, float)))  # type: ignore[attr-defined]

    sys.modules['numpy'] = numpy_stub
