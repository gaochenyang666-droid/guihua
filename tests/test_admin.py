import pytest


class TestAdminStats:

    def test_admin_stats_requires_auth(self, client):
        resp = client.get('/api/admin/stats')
        assert resp.status_code == 401

    def test_admin_stats_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/admin/stats', headers=headers)
        assert resp.status_code == 403

    def test_admin_stats_success(self, client, seed_admin):
        _, headers = seed_admin
        resp = client.get('/api/admin/stats', headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'users' in data
        assert 'posts' in data
        assert 'revenue' in data


class TestAdminUsers:

    def test_admin_users_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/admin/users', headers=headers)
        assert resp.status_code == 403

    def test_admin_users_success(self, client, seed_admin):
        _, headers = seed_admin
        resp = client.get('/api/admin/users', headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1


class TestBanUser:

    def test_ban_user_requires_admin(self, client, seed_user):
        user, headers = seed_user
        resp = client.post(f'/api/admin/users/{user.id}/ban', headers=headers)
        assert resp.status_code == 403


class TestAnnouncements:

    def test_list_announcements_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/admin/announcements', headers=headers)
        assert resp.status_code == 403

    def test_create_announcement_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.post('/api/admin/announcements', json={
            'title': 'Test',
            'content': 'Test content',
        }, headers=headers)
        assert resp.status_code == 403

    def test_create_announcement_success(self, client, seed_admin):
        _, headers = seed_admin
        resp = client.post('/api/admin/announcements', json={
            'title': 'Test Announcement',
            'content': 'Important news',
            'level': 'info',
        }, headers=headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['announcement']['title'] == 'Test Announcement'


class TestAuditLogs:

    def test_admin_audit_logs_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/admin/audit-logs', headers=headers)
        assert resp.status_code == 403


class TestReports:

    def test_admin_reports_requires_admin(self, client, seed_user):
        _, headers = seed_user
        resp = client.get('/api/admin/reports', headers=headers)
        assert resp.status_code == 403
