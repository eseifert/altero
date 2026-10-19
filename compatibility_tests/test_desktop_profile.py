"""A disposable profile must not inherit anything from the machine it runs on."""

import re

from tools.compatibility.desktop import prepare_profile


def test_the_interface_is_english_whatever_the_system_language(tmp_path, monkeypatch):
    """Dialog rules match English button labels, so the profile asks for English.

    Without the preference Zotero follows the system's locale: on a German
    machine the permission-loss prompt offered "Gruppe überspringen" and the
    groups scenario failed looking for "Skip Group".
    """
    monkeypatch.setenv("LANG", "de_DE.UTF-8")

    profile = prepare_profile(tmp_path / "A", "http://127.0.0.1:1/")

    preferences = (profile / "user.js").read_text()
    assert re.search(r'^user_pref\("intl\.locale\.requested", "en-US"\);$', preferences, re.M)
