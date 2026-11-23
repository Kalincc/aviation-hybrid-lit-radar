from datetime import date

import pytest

from src import db, extractor, pipeline, sources


def paper():
    return sources.PaperIn(source='arxiv', external_id='test-1',
                          title='Hybrid Aircraft Control', published=date.today().isoformat(),
                          url='https://arxiv.org/abs/test-1',
                          abstract='We study hybrid aircraft energy management in simulation.')


def test_refresh_recovers_missing_extraction(monkeypatch, settings):
    monkeypatch.setattr(sources, 'fetch_all', lambda **kw: ([paper()], []))
    pipeline.run_refresh(settings=settings, extract=False)
    result = pipeline.run_refresh(settings=settings)
    assert result['inserted'] == 0
    assert result['extracted'] == 1
    assert pipeline.run_refresh(settings=settings)['extracted'] == 0


def test_refresh_deduplicates_against_previous_sources(monkeypatch, settings):
    original = paper()
    original.doi = '10.1234/aircraft'
    monkeypatch.setattr(sources, 'fetch_all', lambda **kw: ([original], []))
    pipeline.run_refresh(settings=settings, extract=False)
    duplicate = paper()
    duplicate.source = 'openalex'
    duplicate.external_id = 'W123'
    duplicate.doi = 'https://doi.org/10.1234/AIRCRAFT'
    duplicate.title = 'A differently indexed title'
    monkeypatch.setattr(sources, 'fetch_all', lambda **kw: ([duplicate], []))
    result = pipeline.run_refresh(settings=settings, extract=False)
    assert result['fetched'] == 1 and result['inserted'] == 0 and result['skipped'] == 1


def test_failed_extraction_finishes_run_and_can_retry(monkeypatch, settings):
    monkeypatch.setattr(sources, 'fetch_all', lambda **kw: ([paper()], []))
    def fail(*args):
        raise RuntimeError('extraction unavailable')
    monkeypatch.setattr(extractor, 'extract_many', fail)
    result = pipeline.run_refresh(settings=settings)
    assert result['status'] == 'partial' and result['errors']
    with db.open_db(settings.db_path) as conn:
        run = db.get_run(conn, result['run_id'])
        assert run['finished_at'] and run['status'] == 'partial'


@pytest.mark.parametrize('abstract', [
    'The dataset is publicly available for aircraft research.',
    'We use proprietary flight data to validate the controller.',
    'An open-source dataset is evaluated in our experiments.',
    'Our code is not publicly available.',
])
def test_data_availability_is_not_code_open_source(abstract):
    result = extractor.heuristic_extract({'abstract': abstract})
    assert result['code_open_source'] != 'yes'
    if 'code' not in abstract:
        assert result['code_open_source'] == 'unknown'


def test_search_treats_sql_wildcards_literally(conn):
    db.upsert_paper(conn, paper())
    assert db.list_papers(conn, q='%')[0] == 0
    assert db.list_papers(conn, q='_')[0] == 0


def test_relevance_requires_aviation_and_power_context():
    assert not sources.is_relevant('Civil aviation pilot training and operational safety')
    assert not sources.is_relevant('Civil aviation pilot training', 'Aircraft energy management and operational safety.')
    assert not sources.is_relevant('Hybrid vehicle propulsion energy management')
    assert not sources.is_relevant('Anaerobic fuel cell processing')
    assert sources.is_relevant('Liquid-cooled thermal management for fuel-cell-powered aircraft')
    assert sources.is_relevant('Mode transition control of hybrid-electric UAVs')


def test_ris_export_matches_filters_and_sanitizes_lines(client, db_file):
    with db.open_db(db_file) as conn:
        entry = paper().to_dict()
        entry['title'] = 'Hybrid Aircraft\nER  - malicious'
        entry['authors'] = ['Alice', 'Bob']
        db.upsert_paper(conn, entry)
    response = client.get('/api/export.ris?days=0&q=Hybrid')
    assert response.status_code == 200
    assert 'attachment;' in response.headers['content-disposition']
    assert 'TI  - Hybrid Aircraft ER - malicious' in response.text
    assert 'AU  - Alice\nAU  - Bob' in response.text
    assert response.text.count('\nER  -') == 1
    assert client.get('/api/export.ris?days=0&source=openalex').text == ''


def test_export_includes_all_pages(client, db_file):
    with db.open_db(db_file) as conn:
        for index in range(55):
            entry = paper().to_dict()
            entry['external_id'] = str(index)
            db.upsert_paper(conn, entry)
    assert client.get('/api/export.ris?days=0').text.count('TY  - GEN') == 55


def test_refresh_rejects_overlapping_request(client, monkeypatch):
    active = False
    def nested_refresh(**kwargs):
        nonlocal active
        if active:
            raise RuntimeError('overlap was allowed')
        active = True
        try:
            response = client.post('/api/refresh', json={})
            assert response.status_code == 409
        finally:
            active = False
        raise RuntimeError('simulated failure')
    monkeypatch.setattr(pipeline, 'run_refresh', nested_refresh)
    for _ in range(2):
        with pytest.raises(RuntimeError, match='simulated failure'):
            client.post('/api/refresh', json={})
