"""Application bootstrap and command-line entry point."""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .controller import GuiController
from .main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jikong BMS CAN desktop monitor")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="start the local BMS demo")
    source.add_argument("--replay", type=Path, help="start replaying a CAN frame CSV")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    parser.add_argument("--loop", action="store_true", help="loop replay input")
    return parser


def configure_application(app: QApplication) -> None:
    app.setApplicationName("BMS CAN Monitor")
    app.setOrganizationName("Jikong BMS CAN")
    app.setStyle("Fusion")

    preferred = (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "SimHei",
    )
    families = set(QFontDatabase.families())
    if platform.system() == "Windows" and not families.intersection(preferred):
        for font_path in (
            Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path(r"C:\Windows\Fonts\msyhl.ttc"),
        ):
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
        families = set(QFontDatabase.families())
    family = next((name for name in preferred if name in families), app.font().family())
    font = QFont(family)
    font.setPointSize(9)
    app.setFont(font)


def create_application(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    configure_application(app)
    pg.setConfigOptions(antialias=False, background="#ffffff", foreground="#344054")

    controller = GuiController()
    window = MainWindow(controller)
    if args.demo:
        controller.start_demo()
    elif args.replay is not None:
        controller.start_replay(args.replay, speed=args.speed, loop=args.loop)
    return app, window


def main() -> int:
    app, window = create_application(sys.argv[1:])
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
