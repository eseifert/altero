"""Differential check of Zotero's original common-word selection and digest."""

import json
import subprocess

from altero.services.pdfmerge import hash_text
from tools.compatibility.client import ZoteroClient


def test_common_word_hash_matches_the_original(zotero_client: ZoteroClient) -> None:
    selected = zotero_client.extract("merge_words")
    words = [f"word{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(65)]
    base = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    cases = [
        "",
        "alpha " * 100,
        base,
        base.replace("alpha", "AL-pha123"),
        base.replace(" ", "\ufeff"),
        base.replace("alpha bravo", "alpha\u0085bravo"),
        " ".join(words),
        " ".join(words[::-1]),
        " ".join(words + ["écho", "echo", "åland", "äland", "öland", "zland"] * 2),
        base + " İSTANBUL straße début 中文测试 ελληνικά العربية",
        " ".join(chr(0x10400 + i) * 2 for i in range(15)),
    ]
    requests = [
        {"locale": locale, "text": text}
        for locale in ["en-US", "de", "sv", "tr", "zh-CN", "ar", "he"]
        for text in cases
    ]
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const {source, cases} = JSON.parse(readFileSync(0, 'utf8'));
let collator;
const Zotero = {localeCompare: (a, b) => collator.compare(a, b)};
const words = eval('(' + source + ')');
const results = cases.map(({locale, text}) => {
  collator = new Intl.Collator(locale, {sensitivity: 'base', numeric: true});
  const chosen = words(text, 50);
  return chosen.length < 10 ? null
    : createHash('md5').update(chosen.sort().join(' ')).digest('hex');
});
process.stdout.write(JSON.stringify(results));
""",
        ],
        input=json.dumps({"source": selected["source"], "cases": requests}),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    expected = json.loads(result.stdout)
    for case, digest in zip(requests, expected, strict=True):
        assert hash_text(case["text"], case["locale"]) == digest, case
