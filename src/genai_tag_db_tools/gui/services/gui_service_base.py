"""GUI service base class."""

import logging

from PySide6.QtCore import QObject, Signal


class GuiServiceBase(QObject):
    """GUI向けの共通基底クラス、シグナル/ロガー"""

    progress_updated = Signal(int, str)  # (progress, message)
    process_finished = Signal(str)  # (message)
    error_occurred = Signal(str)  # (error message)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

    def close(self) -> None:
        """リソース解放(サブクラスでオーバーライド可能)"""
        self.logger.info("Closing %s", self.__class__.__name__)
        # Signal
        try:
            self.disconnect()  # type: ignore[call-overload]
        except TypeError:
            # No connections to disconnect
            pass
