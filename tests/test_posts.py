import pytest


class TestGetPosts:

    def test_get_posts_empty(self, client):
        resp = client.get('/api/posts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'posts' in data
        assert isinstance(data['posts'], list)

    def test_get_posts_returns_list(self, client, seed_admin):
        admin, headers = seed_admin
        client.post('/api/posts', json={
            'title': 'Test Post',
            'content': '<p>Hello world</p>',
        }, headers=headers)

        resp = client.get('/api/posts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['posts']) >= 1


class TestSearchPosts:

    def test_search_posts_empty_query(self, client):
        resp = client.get('/api/search?q=')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['posts'] == []

    def test_search_posts_with_query_no_match(self, client):
        resp = client.get('/api/search?q=nonexistent_xyz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data['posts'], list)
        assert data['total'] == 0


class TestPostAuth:

    def test_create_post_requires_auth(self, client):
        resp = client.post('/api/posts', json={
            'title': 'No auth',
            'content': 'content',
        })
        assert resp.status_code == 401

    def test_like_post_requires_auth(self, client):
        resp = client.post('/api/posts/1/like')
        assert resp.status_code == 401

    def test_bookmark_post_requires_auth(self, client):
        resp = client.post('/api/posts/1/bookmark')
        assert resp.status_code == 401

    def test_delete_post_requires_auth(self, client):
        resp = client.delete('/api/posts/1')
        assert resp.status_code == 401

    def test_add_comment_requires_auth(self, client):
        resp = client.post('/api/posts/1/comments', json={
            'content': 'test comment',
        })
        assert resp.status_code == 401


class TestPostDetail:

    def test_get_post_detail_not_found(self, client):
        resp = client.get('/api/posts/99999')
        assert resp.status_code in (404, 500)


class TestPinnedPost:

    def test_get_pinned_post_empty(self, client):
        resp = client.get('/api/posts/pinned')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['post'] is None


class TestCheckTx:

    def test_check_tx_missing_hash(self, client):
        resp = client.get('/api/posts/check_tx')
        assert resp.status_code == 400
        assert '缺少' in resp.get_json()['error']
