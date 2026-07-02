(function(){
    const LOCAL_MEDIA_RE = /^\/(?:assets|output)\//i;

    function cleanUrl(value){
        return String(value || '').trim();
    }

    function isLocalMediaUrl(url){
        return LOCAL_MEDIA_RE.test(cleanUrl(url));
    }

    function isImageMediaUrl(url){
        const clean = cleanUrl(url).split('?', 1)[0].toLowerCase();
        return /\.(png|jpe?g|webp|gif|bmp)$/i.test(clean);
    }

    function fileNameFromUrl(url, fallback='asset'){
        const clean = cleanUrl(url).split('?', 1)[0];
        const raw = clean.split('/').filter(Boolean).pop() || fallback;
        try {
            return decodeURIComponent(raw);
        } catch(_) {
            return raw;
        }
    }

    function downloadHref(url, filename=''){
        const clean = cleanUrl(url);
        if(!isLocalMediaUrl(clean)) return clean;
        const name = filename || fileNameFromUrl(clean, 'download');
        return `/api/download-output?url=${encodeURIComponent(clean)}&name=${encodeURIComponent(name)}`;
    }

    function mediaKindFromUrl(url){
        const clean = cleanUrl(url).split('?', 1)[0].toLowerCase();
        if(/\.(mp4|m4v|mov|webm|mkv|avi|wmv|flv|mpg|mpeg|ts|mts|m2ts|3gp|ogv)$/i.test(clean)) return 'video';
        if(/\.(mp3|wav|ogg|m4a|flac|aac|wma|opus|aiff?|amr)$/i.test(clean)) return 'audio';
        if(isImageMediaUrl(clean)) return 'image';
        return 'file';
    }

    function imageCategories(library){
        return (library?.categories || []).filter(cat => (cat.type || 'image') === 'image');
    }

    function activeImageCategory(library, preferredId=''){
        const cats = imageCategories(library);
        return cats.find(cat => cat.id === preferredId) || cats[0] || null;
    }

    async function fetchLibrary(){
        const res = await fetch('/api/asset-library');
        if(!res.ok) throw new Error('Asset library load failed.');
        const data = await res.json();
        return data.library || {categories:[]};
    }

    async function createCategory(name){
        const res = await fetch('/api/asset-library/categories', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name, type:'image'})
        });
        if(!res.ok) throw new Error('Asset folder create failed.');
        return res.json();
    }

    async function renameCategory(categoryId, name){
        const res = await fetch(`/api/asset-library/categories/${encodeURIComponent(categoryId)}`, {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name})
        });
        if(!res.ok) throw new Error('Asset folder rename failed.');
        return res.json();
    }

    async function deleteCategory(categoryId){
        const res = await fetch(`/api/asset-library/categories/${encodeURIComponent(categoryId)}`, {method:'DELETE'});
        if(!res.ok) throw new Error('Asset folder delete failed.');
        return res.json();
    }

    async function addItem(categoryId, url, name=''){
        const res = await fetch('/api/asset-library/items', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({category_id:categoryId, url, name})
        });
        if(!res.ok) {
            let message = 'Asset save failed.';
            try {
                const data = await res.json();
                message = data?.detail || data?.message || message;
            } catch(_) {}
            throw new Error(message);
        }
        return res.json();
    }

    async function renameItem(itemId, name){
        const res = await fetch(`/api/asset-library/items/${encodeURIComponent(itemId)}`, {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name})
        });
        if(!res.ok) throw new Error('Asset rename failed.');
        return res.json();
    }

    async function deleteItem(itemId){
        const res = await fetch(`/api/asset-library/items/${encodeURIComponent(itemId)}`, {method:'DELETE'});
        if(!res.ok) throw new Error('Asset delete failed.');
        return res.json();
    }

    async function responseErrorMessage(res, fallback){
        try {
            const data = await res.json();
            return data?.detail || data?.message || fallback;
        } catch(_) {
            return fallback;
        }
    }

    async function postJson(url, payload, fallback){
        const res = await fetch(url, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(payload || {})
        });
        if(!res.ok) throw new Error(await responseErrorMessage(res, fallback));
        return res.json();
    }

    async function deleteItems(ids){
        return postJson('/api/asset-library/items/delete', {ids}, 'Asset delete failed.');
    }

    async function moveItems(ids, categoryId){
        return postJson('/api/asset-library/items/move', {ids, category_id:categoryId}, 'Asset move failed.');
    }

    async function checkUrls(urls){
        return postJson('/api/canvas-assets/check', {urls}, 'Asset check failed.');
    }

    async function uploadFiles(files){
        const form = new FormData();
        Array.from(files || []).forEach(file => form.append('files', file));
        const res = await fetch('/api/ai/upload', {method:'POST', body:form});
        if(!res.ok) throw new Error(await responseErrorMessage(res, 'Media upload failed.'));
        return res.json();
    }

    async function downloadItems(ids, filename='asset-library-images.zip'){
        const res = await fetch('/api/asset-library/items/download', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ids, filename})
        });
        if(!res.ok) throw new Error(await responseErrorMessage(res, 'Asset download failed.'));
        const blob = await res.blob();
        const href = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = href;
        link.download = filename || 'asset-library-images.zip';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(href), 1000);
    }

    window.CanvasAssetLibrary = {
        isLocalMediaUrl,
        isImageMediaUrl,
        fileNameFromUrl,
        downloadHref,
        mediaKindFromUrl,
        imageCategories,
        activeImageCategory,
        fetchLibrary,
        createCategory,
        renameCategory,
        deleteCategory,
        addItem,
        renameItem,
        deleteItem,
        deleteItems,
        moveItems,
        checkUrls,
        uploadFiles,
        downloadItems,
    };
})();
