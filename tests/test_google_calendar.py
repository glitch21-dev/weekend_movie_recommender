from calendar_exporter.google_calendar import GoogleCalendarError, GoogleCalendarExporter


def test_google_auth_fails_gracefully_without_credentials():
    exporter = GoogleCalendarExporter()
    if exporter.is_configured():
        # Environment may provide real credentials; skip strict assertion in that case.
        return
    try:
        exporter.authenticate(interactive=False)
        raise AssertionError("Expected authentication failure when credentials are missing.")
    except GoogleCalendarError:
        assert True
