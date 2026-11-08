import main


def reset_state():
    main.watchlist.clear()
    main.monitored_groups.clear()
    main.recent_processed.clear()
    main.analyzed_messages = 0
    main.worker_status["analyzed_messages"] = 0


def test_apply_monitoring_config_replaces_snapshot():
    reset_state()

    changed = main.apply_monitoring_config(
        {
            "watchlist": [
                {"value": "Test@Example.com", "target_type": "email"},
                {"value": "empresa.com", "target_type": "domain"},
            ],
            "groups": [{"name": "@TestGroup"}, {"name": "1234567"}],
        }
    )

    assert changed is True
    assert main.watchlist["test@example.com"] == ("Test@Example.com", "email")
    assert "empresa.com" in main.watchlist
    assert main.monitored_groups == {"testgroup", "1234567"}

    unchanged = main.apply_monitoring_config(
        {
            "watchlist": [
                {"value": "Test@Example.com", "target_type": "email"},
                {"value": "empresa.com", "target_type": "domain"},
            ],
            "groups": [{"name": "@TestGroup"}, {"name": "1234567"}],
        }
    )
    assert unchanged is False

    replaced = main.apply_monitoring_config(
        {
            "watchlist": [{"value": "novo.com", "target_type": "domain"}],
            "groups": [{"name": "@Outro"}],
        }
    )
    assert replaced is True
    assert main.watchlist == {"novo.com": ("novo.com", "domain")}
    assert main.monitored_groups == {"outro"}


def test_apply_monitoring_config_ignores_empty_items():
    reset_state()

    main.apply_monitoring_config(
        {
            "watchlist": [{"value": "", "target_type": "email"}],
            "groups": [{"name": ""}],
        }
    )

    assert main.watchlist == {}
    assert main.monitored_groups == set()


def test_mark_message_analyzed_deduplicates_recent_events():
    reset_state()

    main.mark_message_analyzed(123, 1)
    main.mark_message_analyzed(123, 1)
    main.mark_message_analyzed(123, 2)

    assert main.analyzed_messages == 2
    assert main.worker_status["analyzed_messages"] == 2
