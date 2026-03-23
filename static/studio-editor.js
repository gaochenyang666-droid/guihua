(function () {
    'use strict';

    window.GHStudioEditorFactory = function GHStudioEditorFactory(deps) {
        const {
            apiBase,
            getQuill,
            setQuill,
            getLastEditorRange,
            setLastEditorRange,
            handle401,
            Toast
        } = deps;

        function compressImage(file, maxWidth, quality) {
            return new Promise((resolve, reject) => {
                const img = new Image();
                const url = URL.createObjectURL(file);
                img.onload = () => {
                    URL.revokeObjectURL(url);
                    let w = img.width;
                    let h = img.height;
                    if (w > maxWidth) {
                        h = (h * maxWidth) / w;
                        w = maxWidth;
                    }
                    const canvas = document.createElement('canvas');
                    canvas.width = w;
                    canvas.height = h;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, w, h);
                    canvas.toBlob((blob) => {
                        if (blob && blob.size > 0) resolve(blob);
                        else resolve(file);
                    }, 'image/jpeg', quality);
                };
                img.onerror = () => {
                    URL.revokeObjectURL(url);
                    reject(new Error('图片加载失败'));
                };
                img.src = url;
            });
        }

        function normalizeUploadName(file, forcedExt) {
            const raw = String((file && file.name) || 'image').replace(/[^\w.\-]/g, '_');
            const base = raw.replace(/\.[^.]+$/, '') || 'image';
            let ext = forcedExt || ((raw.match(/\.([^.]+)$/) || [])[1] || 'jpg');
            ext = String(ext).toLowerCase().replace(/[^a-z0-9]/g, '') || 'jpg';
            return `${base}.${ext}`;
        }

        async function prepareUploadImage(file, maxWidth, quality) {
            const mime = String((file && file.type) || '').toLowerCase();
            if (mime === 'image/gif') {
                return { uploadBlob: file, uploadName: normalizeUploadName(file, 'gif') };
            }
            if ((file && file.size ? file.size : 0) <= 260 * 1024) {
                const ext = mime.indexOf('png') >= 0 ? 'png' : (mime.indexOf('webp') >= 0 ? 'webp' : 'jpg');
                return { uploadBlob: file, uploadName: normalizeUploadName(file, ext) };
            }
            const compressed = await compressImage(file, maxWidth, quality).catch(() => file);
            if (!compressed || compressed === file) {
                const ext = mime.indexOf('png') >= 0 ? 'png' : (mime.indexOf('webp') >= 0 ? 'webp' : 'jpg');
                return { uploadBlob: file, uploadName: normalizeUploadName(file, ext) };
            }
            return { uploadBlob: compressed, uploadName: normalizeUploadName(file, 'jpg') };
        }

        async function uploadInlineImageToEditor(file) {
            const studioQuill = getQuill();
            if (!studioQuill || !file) return;
            if (file.size > 8 * 1024 * 1024) {
                Toast.error('图片需小于 8MB，请压缩或换图');
                return;
            }
            try {
                const insertRange = studioQuill.getSelection(true) || getLastEditorRange() || { index: studioQuill.getLength(), length: 0 };
                const prepared = await prepareUploadImage(file, 720, 0.62);
                const formData = new FormData();
                formData.append('file', prepared.uploadBlob, prepared.uploadName);
                const res = await fetch(apiBase + '/upload', {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin'
                });
                if (handle401(res)) return;
                const resp = await res.json().catch(() => ({}));
                if (!res.ok || !resp.url) {
                    Toast.error(resp.error || '上传失败');
                    return;
                }
                const targetRange = getLastEditorRange() || insertRange;
                studioQuill.insertEmbed(targetRange.index, 'image', resp.url, 'user');
                studioQuill.setSelection(targetRange.index + 1, 0, 'silent');
                setLastEditorRange({ index: targetRange.index + 1, length: 0 });
                Toast.success('图片已插入');
            } catch (e) {
                Toast.error('上传失败: ' + ((e && e.message) || '网络错误'));
            }
        }

        function initQuill() {
            const el = document.getElementById('studioPostContent');
            if (!el) return;
            if (typeof Quill === 'undefined') {
                const wrap = document.getElementById('quillEditorWrap');
                if (wrap) wrap.innerHTML = '<p class="studio-editor-error">富文本编辑器加载失败，请刷新页面或检查网络后重试。</p>';
                return;
            }
            if (getQuill()) return;
            const studioQuill = new Quill(el, {
                theme: 'snow',
                placeholder: '撰写你的怪谈… 可插入图片',
                modules: {
                    toolbar: [
                        ['bold', 'italic', 'underline'],
                        [{ list: 'ordered' }, { list: 'bullet' }],
                        ['link', 'image']
                    ]
                }
            });
            setQuill(studioQuill);

            studioQuill.on('selection-change', (range) => {
                if (range) setLastEditorRange(range);
            });
            studioQuill.root.addEventListener('paste', async (evt) => {
                const clipboard = evt.clipboardData;
                if (!clipboard || !clipboard.items) return;
                const imageItem = Array.from(clipboard.items).find((it) => it && it.type && it.type.indexOf('image/') === 0);
                if (!imageItem) return;
                evt.preventDefault();
                const file = imageItem.getAsFile();
                await uploadInlineImageToEditor(file);
            });
            studioQuill.root.addEventListener('drop', async (evt) => {
                const dt = evt.dataTransfer;
                if (!dt || !dt.files || !dt.files.length) return;
                const imageFile = Array.from(dt.files).find((f) => f && f.type && f.type.indexOf('image/') === 0);
                if (!imageFile) return;
                evt.preventDefault();
                const selection = document.caretRangeFromPoint ? document.caretRangeFromPoint(evt.clientX, evt.clientY) : null;
                if (selection && selection.startContainer && studioQuill) {
                    const blot = Quill.find(selection.startContainer, true);
                    if (blot) {
                        const idx = studioQuill.getIndex(blot);
                        setLastEditorRange({ index: idx, length: 0 });
                    }
                }
                await uploadInlineImageToEditor(imageFile);
            });
            const toolbar = studioQuill.getModule('toolbar');
            toolbar.addHandler('image', function () {
                const selected = studioQuill.getSelection(true);
                if (selected) setLastEditorRange(selected);
                const input = document.createElement('input');
                input.setAttribute('type', 'file');
                input.setAttribute('accept', 'image/png,image/jpeg,image/gif,image/webp');
                input.onchange = async function () {
                    const file = input.files && input.files[0];
                    if (!file) return;
                    await uploadInlineImageToEditor(file);
                    input.value = '';
                };
                input.click();
            });
        }

        return {
            initQuill,
            uploadInlineImageToEditor
        };
    };
})();
