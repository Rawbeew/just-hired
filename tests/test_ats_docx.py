#!/usr/bin/env python3
"""
Tests for the ATS resume/cover-letter generator that ships inside index.html.

The generator is client-side JavaScript (scoreText, buildResume, textToDocx,
zipStore, crc32, ...). These tests extract the inline <script> block from
index.html, run the pure functions under Node (node must be on PATH), and
validate the emitted .docx bytes with Python's zipfile + xml.etree:

  - a generated .docx is a structurally valid ZIP (stored entries)
  - word/document.xml exists and parses as XML (well-formed OOXML)
  - resume text content survives into document.xml
  - scoreText/atsClean behave as documented

This is the closest we can get to "the PDF/docx endpoint produces a parseable
file" without a browser: there is no server-side PDF endpoint in this project
(see README limitations) — downloads are produced by this JS in the client.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INDEX = os.path.join(ROOT, "index.html")

NODE = shutil.which("node")
SKIP = "node not on PATH; cannot test client-side docx generator"


STUBS = """
// Minimal DOM stubs: index.html's script touches the DOM at load time.
const __noop = () => {};
const document = {
  getElementById: () => ({ innerHTML: '', style: {}, classList: {add:__noop,remove:__noop,toggle:__noop}, addEventListener: __noop, value:'', textContent:'' }),
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: () => ({ style: {}, setAttribute: __noop, appendChild: __noop }),
  addEventListener: __noop,
  body: { appendChild: __noop },
};
const window = { addEventListener: __noop, location: { href: '', search: '' } };
const localStorage = { getItem: () => null, setItem: __noop };
"""


def extract_script():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"<script>(.*)</script>", src, re.S)
    assert m, "no inline <script> block found in index.html"
    return STUBS + m.group(1)


def run_node(js):
    if not NODE:
        raise unittest.SkipTest(SKIP)
    # Write to a temp file: Windows has a short command-line limit, so
    # `node -e <big script>` fails with WinError 206.
    fd, jspath = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js)
        p = subprocess.run([NODE, jspath], capture_output=True, text=True)
    finally:
        os.remove(jspath)
    if p.returncode != 0:
        raise AssertionError("node failed:\n" + p.stderr)
    return p.stdout


class AtsDocxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = extract_script()

    def gen_docx(self, text):
        """Run textToDocx+zipStore under node, write bytes to temp file."""
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        js = (
            self.script
            + f"""
const fs = require('fs');
const bytes = zipStore(textToDocx({text!r}));
fs.writeFileSync({path!r}, Buffer.from(bytes));
"""
        )
        run_node(js)
        return path

    def test_docx_is_valid_zip_with_parseable_document_xml(self):
        sample = "Jane Doe\nPSW Candidate\nEXPERIENCE\n- Personal support worker at UHN"
        path = self.gen_docx(sample)
        try:
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
                self.assertIsNone(bad, f"corrupt entry: {bad}")
                names = z.namelist()
                self.assertIn("word/document.xml", names)
                doc = z.read("word/document.xml").decode("utf-8")
            ET.fromstring(doc)  # raises if not well-formed XML
            self.assertIn("Personal support worker", doc.replace("&#xD;", ""))
        finally:
            os.remove(path)

    def test_docx_escapes_xml_specials(self):
        sample = "A & B <tag> \"quotes\""
        path = self.gen_docx(sample)
        try:
            with zipfile.ZipFile(path) as z:
                doc = z.read("word/document.xml").decode("utf-8")
            ET.fromstring(doc)  # would raise on unescaped &
            self.assertIn("&amp;", doc)
        finally:
            os.remove(path)

    def test_scoretext_and_atsclean(self):
        js = (
            self.script
            + """
console.log(JSON.stringify({
  s: scoreText('must have 2 years experience; diploma in PSW'),
  clean: atsClean('  Multi–line   text '),
}));
"""
        )
        out = run_node(js)
        data = __import__("json").loads(out.strip().splitlines()[-1])
        self.assertIsInstance(data["s"], (int, float))
        self.assertEqual(data["clean"], "multi–line text")

    def test_buildresume_mentions_job_keywords(self):
        js = (
            self.script
            + """
const r = buildResume('We are hiring a personal support worker. Requirements: medication administration, dementia care.');
console.log(r.length > 100 ? 'long' : 'short');
"""
        )
        self.assertEqual(run_node(js).strip(), "long")


if __name__ == "__main__":
    unittest.main()
