import pytest


class TestRegister:

    def test_register_success(self, client):
        resp = client.post('/api/auth/web2/register', json={
            'username': 'newuser',
            'password': 'securepass',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert 'token' in data
        assert data['user']['username'] == 'newuser'

    def test_register_duplicate_username(self, client, seed_user):
        resp = client.post('/api/auth/web2/register', json={
            'username': 'testuser',
            'password': 'password123',
        })
        assert resp.status_code == 400
        assert '已被注册' in resp.get_json()['error']

    def test_register_missing_fields(self, client):
        resp = client.post('/api/auth/web2/register', json={
            'username': '',
            'password': '',
        })
        assert resp.status_code == 400

    def test_register_short_password(self, client):
        resp = client.post('/api/auth/web2/register', json={
            'username': 'shortpw',
            'password': '12345',
        })
        assert resp.status_code == 400
        assert '6' in resp.get_json()['error']


class TestLogin:

    def test_login_success(self, client, seed_user):
        resp = client.post('/api/auth/web2/login', json={
            'username': 'testuser',
            'password': 'password123',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'token' in data
        assert data['user']['username'] == 'testuser'

    def test_login_wrong_password(self, client, seed_user):
        resp = client.post('/api/auth/web2/login', json={
            'username': 'testuser',
            'password': 'wrongpass',
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post('/api/auth/web2/login', json={
            'username': 'ghost',
            'password': 'whatever',
        })
        assert resp.status_code == 401


class TestLogout:

    def test_logout(self, client):
        resp = client.post('/api/auth/logout')
        assert resp.status_code == 200
        assert '退出' in resp.get_json()['message']


class TestChangePassword:

    def test_change_password_no_login_success(self, client, seed_user):
        resp = client.post('/api/auth/web2/change-password', json={
            'username': 'testuser',
            'old_password': 'password123',
            'new_password': 'newpass789',
        })
        assert resp.status_code == 200
        assert '已修改' in resp.get_json()['message']

        login_resp = client.post('/api/auth/web2/login', json={
            'username': 'testuser',
            'password': 'newpass789',
        })
        assert login_resp.status_code == 200

    def test_change_password_no_login_wrong_old(self, client, seed_user):
        resp = client.post('/api/auth/web2/change-password', json={
            'username': 'testuser',
            'old_password': 'wrong_old',
            'new_password': 'newpass789',
        })
        assert resp.status_code == 401
        assert '原密码' in resp.get_json()['error']

    def test_change_password_no_login_short_new(self, client, seed_user):
        resp = client.post('/api/auth/web2/change-password', json={
            'username': 'testuser',
            'old_password': 'password123',
            'new_password': '123',
        })
        assert resp.status_code == 400
        assert '6' in resp.get_json()['error']

    def test_change_password_requires_fields(self, client):
        resp = client.post('/api/auth/web2/change-password', json={
            'username': 'testuser',
        })
        assert resp.status_code == 400
