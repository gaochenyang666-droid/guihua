class TestHealth:

    def test_health_ok(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'

    def test_health_returns_json(self, client):
        resp = client.get('/health')
        assert resp.content_type.startswith('application/json')

    def test_index_page(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
