from pathlib import Path

from scripts.ingest_documents import doc_type_for, engagement_jobs, shared_jobs
from scripts.synthetic.generate import generate_all


def test_demo_jobs_index_documents_only_with_inferred_doc_types(tmp_path: Path):
    from app.services.engagement_data import EngagementDataRepository

    generate_all(tmp_path)
    repo = EngagementDataRepository(tmp_path)

    jobs = shared_jobs(tmp_path) + engagement_jobs(repo, "acme-2025")

    assert [(p.name, eng, dt) for p, eng, dt in jobs] == [
        ("salt_reference_guide.pdf", "shared", "reference"),
        ("locations.docx", "acme-2025", "locations"),
        ("questionnaire.pdf", "acme-2025", "questionnaire"),
    ]
    assert doc_type_for(Path("random.pdf")) == "other"
