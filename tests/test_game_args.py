def test_unwritable_log_file_falls_back_to_console(tmp_path):
    from theroadragetrip.game_args import configure_logging
    configure_logging(log_file=str(tmp_path / "missing-dir" / "server.log"))  # must not raise
