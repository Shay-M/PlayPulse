from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.adb_service import ADBService
from app.services.app_state import AppState
from app.services.fastlane_service import FastlaneService
from app.services.gemini_service import GeminiService
from app.services.internal_adb_flow_service import InternalADBFlowService
from app.services.log_service import LogService
from app.services.project_scanner import ProjectScanner
from app.services.screenshot_service import ScreenshotService
from app.services.settings_service import SettingsService
from app.ui.pages.deployment_page import DeploymentPage
from app.ui.pages.logs_page import LogsPage
from app.ui.pages.metadata_page import MetadataPage
from app.ui.pages.project_setup_page import ProjectSetupPage
from app.ui.pages.screenshots_page import ScreenshotsPage
from app.ui.pages.about_page import AboutPage
from app.ui.styles import load_stylesheet
from app.ui.workers import WorkerPool


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PlayPulse - Android Store Localization & Deployment Tool")
        self.setMinimumSize(1240, 780)
        self.app_state = AppState()
        self.settings_service = SettingsService()
        self.settings_service.load_into_state(self.app_state)
        self.log_service = LogService()
        self.project_scanner = ProjectScanner()
        self.gemini_service = GeminiService()
        self.adb_service = ADBService(self.settings_service)
        self.internal_flow_service = InternalADBFlowService(self.adb_service)
        self.screenshot_service = ScreenshotService(self.adb_service, self.internal_flow_service)
        self.fastlane_service = FastlaneService()
        self.worker_pool = WorkerPool()
        self.buttons: list[QPushButton] = []
        self.pages: list[QWidget] = []
        self._init_ui()
        self.log_service.info("PlayPulse frontend ready.")

    def _init_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.project_page = ProjectSetupPage(
            self.app_state,
            self.log_service,
            self.project_scanner,
            self.settings_service,
            self.worker_pool,
        )
        self.metadata_page = MetadataPage(
            self.app_state,
            self.log_service,
            self.gemini_service,
            self.worker_pool,
        )
        self.screenshots_page = ScreenshotsPage(
            self.app_state,
            self.log_service,
            self.adb_service,
            self.screenshot_service,
            self.internal_flow_service,
            self.settings_service,
            self.worker_pool,
        )
        self.deployment_page = DeploymentPage(
            self.app_state,
            self.log_service,
            self.fastlane_service,
            self.worker_pool,
        )
        self.logs_page = LogsPage(self.app_state, self.log_service)
        self.about_page = AboutPage()

        self.pages = [
            self.project_page,
            self.metadata_page,
            self.screenshots_page,
            self.deployment_page,
            self.logs_page,
            self.about_page,
        ]
        for page in self.pages:
            self.stack.addWidget(self._wrap_page(page))

        for index, button in enumerate(self.buttons):
            button.clicked.connect(lambda checked=False, page_index=index: self.set_active_page(page_index))

        self.setStyleSheet(load_stylesheet())
        self.set_active_page(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 24, 22, 24)
        sidebar_layout.setSpacing(10)

        title = QLabel("PlayPulse")
        title.setObjectName("sidebarTitle")
        subtitle = QLabel("Store localization workflow")
        subtitle.setObjectName("sidebarSubtitle")
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(12)

        for label in ["Project Setup", "Store Metadata", "Screenshots", "Deployment", "Logs", "About"]:
            sidebar_layout.addWidget(self._create_nav_button(label))

        sidebar_layout.addStretch()
        return sidebar

    def _wrap_page(self, page: QWidget) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("pageScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(page)
        return scroll_area

    def _create_nav_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("navigationButton")
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(True)
        self.buttons.append(button)
        return button

    def set_active_page(self, index: int) -> None:
        page = self.pages[index]
        refresh_method = getattr(page, "refresh_from_state", None)
        if callable(refresh_method):
            refresh_method()

        self.stack.setCurrentIndex(index)
        for idx, button in enumerate(self.buttons):
            active = idx == index
            button.setChecked(active)
            button.setProperty("active", "true" if active else "false")
            button.style().unpolish(button)
            button.style().polish(button)
