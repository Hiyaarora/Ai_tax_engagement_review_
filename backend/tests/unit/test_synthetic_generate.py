import re
from pathlib import Path

from scripts.synthetic.generate import OUTPUT_FILES, generate_all


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_generate_all_writes_the_four_demo_files(tmp_path: Path):
    written = generate_all(tmp_path)
    assert sorted(p.name for p in written) == sorted(OUTPUT_FILES)
    for path in written:
        assert path.exists() and path.stat().st_size > 0


def test_pdfs_fit_the_document_intelligence_free_tier_two_page_limit(tmp_path: Path):
    for path in generate_all(tmp_path):
        if path.suffix == ".pdf":
            assert 1 <= _pdf_page_count(path.read_bytes()) <= 2, path.name


def test_every_document_carries_the_synthetic_disclaimer(tmp_path: Path):
    for path in generate_all(tmp_path):
        if path.suffix == ".csv":
            assert path.read_text().startswith("# SYNTHETIC DATA")
