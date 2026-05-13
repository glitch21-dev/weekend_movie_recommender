import sys
from datetime import datetime

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

import config
from calendar_exporter.google_calendar import GoogleCalendarError, GoogleCalendarExporter
from calendar_exporter.sync_service import sync_watchlist_item, bulk_sync_unsynced
from database.db_manager import DBManager
from recommender.recommender import Recommender
from scheduler.scheduler import Scheduler
from utils.helpers import ensure_timezone


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    done = pyqtSignal()


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            out = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(out)
        except Exception as exc:  # pragma: no cover - UI behavior
            self.signals.error.emit(str(exc))
        finally:
            self.signals.done.emit()


class MovieApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Weekend Movie Recommender")
        self.resize(1100, 700)
        self.thread_pool = QThreadPool.globalInstance()
        self.db = DBManager()
        self.recommender = Recommender(self.db)
        self.scheduler = Scheduler(self.db)
        self.google_exporter = GoogleCalendarExporter()
        self.current_movies = []
        self.selected_movie = None

        self._build_ui()
        self.refresh_auth_state()
        self.load_recommendations()
        self.load_sync_table()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)

        left = QVBoxLayout()
        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search title...")
        self.genre_filter = QLineEdit()
        self.genre_filter.setPlaceholderText("Filter genre...")
        self.sort_box = QComboBox()
        self.sort_box.addItems(["Score (desc)", "IMDb (desc)", "Year (desc)", "Title (asc)"])
        self.top_n_box = QSpinBox()
        self.top_n_box.setRange(1, 100)
        self.top_n_box.setValue(config.TOP_N_RECOMMENDATIONS)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_recommendations)
        self.search_input.textChanged.connect(self.apply_filters)
        self.genre_filter.textChanged.connect(self.apply_filters)
        self.sort_box.currentIndexChanged.connect(self.apply_filters)
        controls.addWidget(self.search_input)
        controls.addWidget(self.genre_filter)
        controls.addWidget(self.sort_box)
        controls.addWidget(self.top_n_box)
        controls.addWidget(refresh_btn)

        self.movies_list = QListWidget()
        self.movies_list.currentItemChanged.connect(self.on_select_movie)
        left.addLayout(controls)
        left.addWidget(self.movies_list)

        right = QVBoxLayout()
        self.auth_label = QLabel()
        auth_btn = QPushButton("Authenticate Google")
        auth_btn.clicked.connect(self.authenticate_google)
        right.addWidget(self.auth_label)
        right.addWidget(auth_btn)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        right.addWidget(self.details)

        form = QFormLayout()
        self.schedule_input = QDateTimeEdit(datetime.now())
        self.schedule_input.setCalendarPopup(True)
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("Streaming platform or cinema")
        form.addRow("Watch time", self.schedule_input)
        form.addRow("Location", self.location_input)
        right.addLayout(form)

        actions = QHBoxLayout()
        save_btn = QPushButton("Save to Watchlist")
        export_btn = QPushButton("Export to Google Calendar")
        save_btn.clicked.connect(self.save_watchlist)
        export_btn.clicked.connect(self.export_selected)
        actions.addWidget(save_btn)
        actions.addWidget(export_btn)
        right.addLayout(actions)

        sync_header = QLabel("Google Calendar Sync Dashboard")
        right.addWidget(sync_header)

        self.sync_table = QTableWidget()
        self.sync_table.setColumnCount(6)
        self.sync_table.setHorizontalHeaderLabels(
            ["Movie", "Scheduled", "Status", "Last Sync", "Google Event ID", "Last Error"]
        )
        self.sync_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sync_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sync_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.sync_table.horizontalHeader().setStretchLastSection(True)
        self.sync_table.setMinimumHeight(220)
        right.addWidget(self.sync_table)

        sync_actions = QHBoxLayout()
        self.sync_refresh_btn = QPushButton("Refresh")
        self.sync_retry_btn = QPushButton("Retry Failed")
        self.sync_bulk_btn = QPushButton("Export Unsynced")
        self.sync_delete_btn = QPushButton("Delete Events")
        self.sync_reauth_btn = QPushButton("Reauthenticate")
        self.sync_refresh_btn.clicked.connect(self.refresh_sync_table)
        self.sync_retry_btn.clicked.connect(self.retry_failed_syncs)
        self.sync_bulk_btn.clicked.connect(self.export_unsynced_bulk)
        self.sync_delete_btn.clicked.connect(self.delete_selected_events)
        self.sync_reauth_btn.clicked.connect(self.reauthenticate_google)
        for b in [self.sync_refresh_btn, self.sync_retry_btn, self.sync_bulk_btn, self.sync_delete_btn, self.sync_reauth_btn]:
            sync_actions.addWidget(b)
        right.addLayout(sync_actions)

        self.loading_label = QLabel("")
        right.addWidget(self.loading_label)

        main_layout.addLayout(left, 3)
        main_layout.addLayout(right, 2)

    def set_loading(self, message):
        self.loading_label.setText(message)

    def run_worker(self, fn, on_result, loading_text="Loading..."):
        self.set_loading(loading_text)
        worker = Worker(fn)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.show_error)
        worker.signals.done.connect(lambda: self.set_loading(""))
        self.thread_pool.start(worker)

    def refresh_auth_state(self):
        configured = self.google_exporter.is_configured()
        token_exists = "Yes" if self.google_exporter.is_configured() and self._token_exists() else "No"
        self.auth_label.setText(
            f"Google OAuth configured: {'Yes' if configured else 'No'} | Token available: {token_exists}"
        )

    @staticmethod
    def _token_exists():
        import os
        return os.path.exists(config.GOOGLE_TOKEN_FILE)

    def load_recommendations(self):
        top_n = self.top_n_box.value()
        self.run_worker(
            lambda: self.recommender.generate_recommendations(top_n=top_n),
            self._on_recommendations_loaded,
            "Loading recommendations...",
        )

    def _on_recommendations_loaded(self, movies):
        self.current_movies = movies or []
        self.apply_filters()

    def load_sync_table(self):
        self.sync_table.setRowCount(0)
        watchlist = self.db.get_watchlist(watched_only=False) or []
        for it in watchlist:
            wid = it.get("id")
            title = it.get("title") or ""
            scheduled = it.get("scheduled_date")
            if isinstance(scheduled, datetime):
                scheduled_str = scheduled.strftime("%Y-%m-%d %H:%M")
            else:
                scheduled_str = str(scheduled or "")

            status = it.get("google_sync_status") or "pending"
            status_display = "pending" if status == "syncing" else status
            last_sync = it.get("google_last_sync_at") or ""
            event_id = it.get("google_event_id") or ""
            last_error = it.get("google_last_error") or ""
            last_error_short = (last_error[:75] + "…") if len(last_error) > 75 else last_error

            row = self.sync_table.rowCount()
            self.sync_table.insertRow(row)

            movie_item = QTableWidgetItem(title)
            movie_item.setData(Qt.ItemDataRole.UserRole, wid)

            status_item = QTableWidgetItem(status)
            scheduled_item = QTableWidgetItem(scheduled_str)
            last_sync_item = QTableWidgetItem(str(last_sync))
            event_id_item = QTableWidgetItem(str(event_id))
            error_item = QTableWidgetItem(last_error_short)

            if status_display == "failed":
                status_item.setForeground(Qt.GlobalColor.red)
            elif status_display == "revoked":
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            elif status_display == "duplicate_skipped":
                status_item.setForeground(Qt.GlobalColor.gray)
            elif status_display == "synced":
                status_item.setForeground(Qt.GlobalColor.darkGreen)

            self.sync_table.setItem(row, 0, movie_item)
            self.sync_table.setItem(row, 1, scheduled_item)
            status_item.setText(status_display)
            self.sync_table.setItem(row, 2, status_item)
            self.sync_table.setItem(row, 3, last_sync_item)
            self.sync_table.setItem(row, 4, event_id_item)
            self.sync_table.setItem(row, 5, error_item)

    def refresh_sync_table(self):
        self.load_sync_table()

    def retry_failed_syncs(self):
        items = self.db.get_watchlist(watched_only=False) or []
        candidate_ids = [
            it["id"]
            for it in items
            if (not it.get("watched")) and (it.get("google_sync_status") == "failed")
        ]
        if not candidate_ids:
            self.show_info("No failed sync items found.")
            return

        location_override = self.location_input.text().strip()

        def _retry():
            db = DBManager()
            exporter = GoogleCalendarExporter()
            try:
                results = []
                for wid in candidate_ids:
                    results.append(
                        sync_watchlist_item(
                            db,
                            exporter,
                            wid,
                            location_override=location_override,
                            reminder_minutes=30,
                            interactive_auth=True,
                        )
                    )
                return results
            finally:
                db.close()

        self.run_worker(_retry, lambda _: self._after_sync_operation("Retry complete."), "Retrying sync...")

    def export_unsynced_bulk(self):
        location_override = self.location_input.text().strip()

        def _bulk():
            db = DBManager()
            exporter = GoogleCalendarExporter()
            try:
                return bulk_sync_unsynced(
                    db,
                    exporter,
                    location_override=location_override,
                    reminder_minutes=30,
                    interactive_auth=True,
                )
            finally:
                db.close()

        self.run_worker(_bulk, lambda _: self._after_sync_operation("Bulk export complete."), "Exporting unsynced...")

    def delete_selected_events(self):
        selected_rows = self.sync_table.selectionModel().selectedRows()
        if not selected_rows:
            self.show_error("Select one or more rows to delete.")
            return

        wid_list = []
        for idx in selected_rows:
            wid = self.sync_table.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
            wid_list.append(int(wid))

        def _delete():
            db = DBManager()
            exporter = GoogleCalendarExporter()
            try:
                deleted = 0
                for wid in wid_list:
                    item = db.get_watchlist_item(wid)
                    event_id = (item or {}).get("google_event_id")
                    if event_id:
                        exporter.delete_event(event_id)
                        db.clear_calendar_event_link(wid)
                        deleted += 1
                return deleted
            finally:
                db.close()

        self.run_worker(_delete, lambda _: self._after_sync_operation("Deletion complete."), "Deleting events...")

    def reauthenticate_google(self):
        def _reauth():
            exporter = GoogleCalendarExporter()
            return exporter.reauthenticate()

        self.run_worker(_reauth, self._on_google_reauthed, "Reauthenticating...")

    def apply_filters(self):
        search_text = self.search_input.text().strip().lower()
        genre_text = self.genre_filter.text().strip().lower()
        data = []
        for movie in self.current_movies:
            title = (movie.get("title") or "").lower()
            genres = str(movie.get("genres", "")).lower()
            if search_text and search_text not in title:
                continue
            if genre_text and genre_text not in genres:
                continue
            data.append(movie)

        sort_choice = self.sort_box.currentText()
        if sort_choice == "IMDb (desc)":
            data.sort(key=lambda m: m.get("imdb_rating") or 0, reverse=True)
        elif sort_choice == "Year (desc)":
            data.sort(key=lambda m: m.get("year") or 0, reverse=True)
        elif sort_choice == "Title (asc)":
            data.sort(key=lambda m: m.get("title") or "")
        else:
            data.sort(key=lambda m: m.get("computed_score") or 0, reverse=True)

        self.movies_list.clear()
        for movie in data:
            item = QListWidgetItem(
                f"{movie.get('title')} ({movie.get('year')}) | IMDb {movie.get('imdb_rating')} | Score {movie.get('computed_score')}"
            )
            item.setData(256, movie)
            self.movies_list.addItem(item)

    def on_select_movie(self, current, previous):  # pylint: disable=unused-argument
        if not current:
            self.selected_movie = None
            self.details.clear()
            return
        movie = current.data(256)
        self.selected_movie = movie
        self.details.setPlainText(
            f"Title: {movie.get('title')}\n"
            f"Year: {movie.get('year')}\n"
            f"IMDb: {movie.get('imdb_rating')}\n"
            f"Computed score: {movie.get('computed_score')}\n"
            f"Genres: {movie.get('genres')}\n"
            f"Votes: {movie.get('vote_count')}\n"
        )

    def save_watchlist(self):
        if not self.selected_movie:
            self.show_error("Select a movie first.")
            return
        when = self.schedule_input.dateTime().toPyDateTime()
        when = ensure_timezone(when)
        movie_id = self.selected_movie["id"]

        self.run_worker(
            lambda: self._save_watchlist_item(movie_id, when),
            lambda _: self._after_sync_operation("Movie saved to watchlist."),
            "Saving watchlist item...",
        )

    def _save_watchlist_item(self, movie_id: int, when: datetime) -> None:
        db = DBManager()
        try:
            db.add_to_watchlist(movie_id, when)
        finally:
            db.close()

    def authenticate_google(self):
        def _auth():
            self.google_exporter.authenticate(interactive=True)
            return True
        self.run_worker(_auth, lambda _: self._on_authenticated(), "Authenticating Google...")

    def _on_authenticated(self):
        self.refresh_auth_state()
        self.show_info("Google authentication complete.")

    def export_selected(self):
        if not self.selected_movie:
            self.show_error("Select a movie first.")
            return
        when = ensure_timezone(self.schedule_input.dateTime().toPyDateTime())
        movie_id = self.selected_movie["id"]
        location = self.location_input.text().strip()

        def _export():
            db = DBManager()
            exporter = GoogleCalendarExporter()
            try:
                db.add_to_watchlist(movie_id, when)
                watchlist_id = db.get_watchlist_id_by_movie_and_time(movie_id, when)
                if not watchlist_id:
                    raise RuntimeError("Failed to create watchlist entry for export.")
                return sync_watchlist_item(
                    db,
                    exporter,
                    watchlist_id,
                    location_override=location,
                    reminder_minutes=30,
                    interactive_auth=True,
                )
            finally:
                db.close()

        self.run_worker(_export, self._on_export_sync_complete, "Exporting to Google Calendar...")

    def _on_export_sync_complete(self, result):
        status = result.get("status")
        event_id = result.get("event_id")
        if status == "synced":
            self._after_sync_operation("Exported to Google Calendar.")
        elif status == "duplicate_skipped":
            self.load_sync_table()
            self.show_info(f"Duplicate detected; skipped creating a new event. Event ID: {event_id}")
        elif status == "revoked":
            self.load_sync_table()
            self.show_info("Google token appears revoked. Click 'Reauthenticate' to continue.")
        else:
            self.load_sync_table()
            self.show_info(f"Calendar export did not complete (status={status}). Error: {result.get('last_error')}")

    def _on_google_reauthed(self, _):
        self.refresh_auth_state()
        self.load_sync_table()
        self.show_info("Google reauthentication complete.")

    def _after_sync_operation(self, success_message: str):
        self.load_sync_table()
        self.show_info(success_message)

    def show_error(self, message):
        if isinstance(message, GoogleCalendarError):
            text = str(message)
        else:
            text = str(message)
        QMessageBox.critical(self, "Error", text)

    def show_info(self, message):
        QMessageBox.information(self, "Info", str(message))

    def closeEvent(self, event):  # pragma: no cover - Qt lifecycle
        self.db.close()
        super().closeEvent(event)


def run_gui():
    app = QApplication(sys.argv)
    win = MovieApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
