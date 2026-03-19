import pytest


class TestNotifications:

    def test_get_notifications_requires_auth(self, client):
        resp = client.get('/api/notifications')
        assert resp.status_code == 401

    def test_get_notifications_empty(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/notifications', headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['notifications'] == []
        assert data['total'] == 0

    def test_read_notification_requires_auth(self, client):
        resp = client.put('/api/notifications/1/read')
        assert resp.status_code == 401

    def test_read_all_notifications_requires_auth(self, client):
        resp = client.put('/api/notifications/read_all')
        assert resp.status_code == 401

    def test_read_all_notifications_success(self, client, seed_user):
        _, headers = seed_user
        resp = client.put('/api/notifications/read_all', headers=headers)
        assert resp.status_code == 200
        assert '已读' in resp.get_json()['message']
