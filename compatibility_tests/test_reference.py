"""Reference evidence fails closed when the reviewed source changes."""

import hashlib
import subprocess

import pytest

from tools.compatibility.client import CompatibilityError
from tools.compatibility.reference import reference_evidence


def test_reference_requires_reviewed_source_and_ranges(tmp_path):
    source = tmp_path / "reference"
    source.mkdir()
    file = source / "reference.php"
    file.write_text("<?php\n// reviewed behavior\n")
    for args in (
        ["init", "-q"],
        ["add", "reference.php"],
        [
            "-c",
            "user.name=Compatibility",
            "-c",
            "user.email=test@invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(["git", "-C", str(source), *args], check=True)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    manifest = tmp_path / "reference.toml"
    manifest.write_text(f'''[dataserver]
revision = "{revision}"
[files]
"reference.php" = "{hashlib.sha256(file.read_bytes()).hexdigest()}"
[[checks]]
name = "fixture"
status = "consistent"
claim = "Reviewed behavior"
file = "reference.php"
line = 1
end_line = 2
''')
    report = reference_evidence(source, manifest)
    assert report["checks"][0]["code"] == file.read_text()
    assert report["executed"] is False
    file.write_text("<?php\n// changed\n")
    with pytest.raises(CompatibilityError, match=r"changed|fingerprint"):
        reference_evidence(source, manifest)
    file.write_text("<?php\n// reviewed behavior\n")
    manifest.write_text(manifest.read_text().replace("end_line = 2", "end_line = 3"))
    with pytest.raises(CompatibilityError, match="range"):
        reference_evidence(source, manifest)
