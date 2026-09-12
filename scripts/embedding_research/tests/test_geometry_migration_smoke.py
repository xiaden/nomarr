from scripts.embedding_research.common.geometry_analysis import GeometryCorpusRequest
from scripts.embedding_research.common.head_analysis import GeometryHeadOutput
from scripts.embedding_research.db.flat import load_analyze_metrics, write_analyze_metrics


def test_geometry_public_types_import():
    assert GeometryCorpusRequest
    assert GeometryHeadOutput


def test_geometry_metric_round_trip(con):
    write_analyze_metrics(con, "geometry:test", "geometry", "geometry", 0, {"score": 1.0}, run_id="run")
    frame = load_analyze_metrics(con, run_id="run")
    assert frame.loc[0, "score"] == 1.0
