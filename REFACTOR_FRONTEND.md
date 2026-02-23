# 前端拆分说明

## 已新增的静态资源

- **`static/js/api-client.js`**：统一 API 客户端。`ApiClient.get(path)` / `ApiClient.post(path, body)` 自动带 `Authorization: Bearer <token>`，可被各页共用。
- **`static/js/auth.js`**：身份核心。`AuthCore.fetchMe()` / `AuthCore.logout()` / `AuthCore.getCurrentUser()`，各页可先加载此文件再在页面内定义自己的 `Auth.init`、登录表单等。
- **`static/js/web3-utils.js`**：Web3 工具。`Web3Utils.getFeesConfig()`、`Web3Utils.sendUsdtTransfer(from, to, amountUsdt)`、`Web3Utils.checkChainId(provider)`，打赏/发帖费逻辑可逐步迁到此处。
- **`static/js/editor-handler.js`**：编辑器工具。`EditorHandler.compressImage(file, maxWidth, quality)`，供 Quill 图片上传前压缩。
- **`static/css/theme.css`**：主题变量与动画（`:root`、`@keyframes`），可在 `style.css` 前引入以分离主题与布局。
- **`templates/components/_navbar.html`**：导航栏 Jinja2 片段，可在各模板中 `{% include 'components/_navbar.html' %}` 并配合 `{% block nav_extra %}` 扩展。

## 接入方式（可选、渐进）

1. **仅用 api-client**：在 `index.html` 等中增加 `<script src="/static/js/api-client.js"></script>`，将 `API_BASE` 设为 `ApiClient.getBase()`，部分 `fetch` 改为 `ApiClient.get('/user/me')` 等。
2. **仅用 editor-handler**：在 `studio.html` 中引入 `editor-handler.js`，将内联的 `compressImage` 改为调用 `EditorHandler.compressImage`。
3. **仅用 theme.css**：在 `<head>` 中在 `style.css` 前增加 `<link rel="stylesheet" href="/static/css/theme.css">`，再在 `style.css` 中删除重复的 `:root` 与 `@keyframes`，避免重复定义。
4. **组件**：将各页面的 `<nav class="navbar glass">...</nav>` 替换为 `{% include 'components/_navbar.html' %}`，并在需要处用 `{% block nav_extra %}` 插入搜索框、用户菜单等。

当前页面仍保留原有内联逻辑，上述文件为可选增强；按需引入并逐步替换即可。
