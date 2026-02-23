/**
 * 编辑器插件：图片压缩（Canvas）、供 Quill 插入图片时使用
 */
(function () {
    'use strict';

    /**
     * 压缩图片为 JPEG Blob
     * @param {File} file
     * @param {number} maxWidth
     * @param {number} quality 0-1
     * @returns {Promise<Blob>}
     */
    function compressImage(file, maxWidth, quality) {
        return new Promise(function (resolve, reject) {
            var img = new Image();
            var url = URL.createObjectURL(file);
            img.onload = function () {
                URL.revokeObjectURL(url);
                var w = img.width, h = img.height;
                if (w > maxWidth) {
                    h = (h * maxWidth) / w;
                    w = maxWidth;
                }
                var canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, w, h);
                canvas.toBlob(function (blob) {
                    if (blob && blob.size > 0) resolve(blob);
                    else resolve(file);
                }, 'image/jpeg', quality);
            };
            img.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('图片加载失败'));
            };
            img.src = url;
        });
    }

    window.EditorHandler = {
        compressImage: compressImage
    };
})();
