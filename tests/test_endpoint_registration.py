from app import NAV_LINKS


def test_nav_links_endpoints_registered(app):
    endpoint_names = {rule.endpoint for rule in app.url_map.iter_rules()}

    assert "menu.view_menus" in endpoint_names
    assert "event.view_events" in endpoint_names

    missing = sorted(set(NAV_LINKS) - endpoint_names)
    assert missing == []
