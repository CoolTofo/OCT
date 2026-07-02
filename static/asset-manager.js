(function(){
    const api = window.CanvasAssetLibrary;
    const LAST_CANVAS_ID_KEY = 'oct_last_canvas_id';
    const state = {
        library:{categories:[]},
        activeCategoryId:'',
        selected:new Set(),
        previewId:'',
        query:'',
        busy:false,
    };
    const dom = {};

    function $(id){ return document.getElementById(id); }
    function escapeHtml(value){
        return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
    }
    function setNotice(message='', kind=''){
        dom.notice.textContent = message || '';
        dom.notice.className = `asset-notice${kind ? ` ${kind}` : ''}`;
    }
    function categories(){ return api.imageCategories(state.library); }
    function activeCategory(){ return api.activeImageCategory(state.library, state.activeCategoryId); }
    function allItems(){ return categories().flatMap(cat => (cat.items || []).map(item => ({...item, categoryId:cat.id, categoryName:cat.name}))); }
    function currentItems(){
        const cat = activeCategory();
        const q = state.query.trim().toLowerCase();
        const items = cat ? (cat.items || []) : [];
        if(!q) return items;
        return items.filter(item => `${item.name || ''} ${item.url || ''}`.toLowerCase().includes(q));
    }
    function selectedIds(){ return Array.from(state.selected); }
    function itemById(id){ return allItems().find(item => item.id === id) || null; }
    function fileLabel(item){ return api.fileNameFromUrl(item?.url || '', item?.name || 'asset'); }
    function runIcons(){ if(window.lucide?.createIcons) window.lucide.createIcons(); }

    function canvasReturnUrl(){
        const params = new URLSearchParams(window.location.search || '');
        let id = params.get('canvas_id') || params.get('id') || '';
        if(!id) {
            try { id = localStorage.getItem(LAST_CANVAS_ID_KEY) || ''; } catch(_) {}
        }
        return id ? `/static/canvas.html?id=${encodeURIComponent(id)}` : '/static/canvas.html';
    }
    async function loadLibrary(preferredCategoryId=''){
        try {
            state.library = await api.fetchLibrary();
            const preferred = preferredCategoryId || state.activeCategoryId;
            const cat = api.activeImageCategory(state.library, preferred);
            state.activeCategoryId = cat?.id || '';
            state.selected = new Set(selectedIds().filter(id => itemById(id)));
            render();
            setNotice('资产库已同步。', 'ok');
        } catch(err) {
            setNotice(err.message || '资产库加载失败。', 'error');
        }
    }

    function render(){
        renderCategories();
        renderBulkOptions();
        renderGrid();
        renderPreview();
        runIcons();
    }

    function renderCategories(){
        const cats = categories();
        dom.categoryCount.textContent = `${cats.length} 个分类`;
        dom.categoryList.innerHTML = cats.map(cat => {
            const count = (cat.items || []).length;
            return `<button class="category-row${cat.id === state.activeCategoryId ? ' active' : ''}" type="button" data-category-id="${escapeHtml(cat.id)}" title="${escapeHtml(cat.name)}">
                <strong>${escapeHtml(cat.name)}</strong><span>${count}</span>
            </button>`;
        }).join('') || '<div class="preview-empty">还没有图片分类</div>';
    }

    function renderBulkOptions(){
        const cats = categories();
        dom.bulkMoveSelect.innerHTML = cats.map(cat => `<option value="${escapeHtml(cat.id)}">移动到：${escapeHtml(cat.name)}</option>`).join('');
        dom.bulkMoveSelect.value = state.activeCategoryId || cats[0]?.id || '';
        const count = state.selected.size;
        dom.selectionCount.textContent = count ? `已选择 ${count}` : '未选择';
    }

    function renderGrid(){
        const items = currentItems();
        const cat = activeCategory();
        dom.assetCount.textContent = `${items.length} 个资产${cat ? ` · ${cat.name}` : ''}`;
        dom.emptyState.classList.toggle('show', items.length === 0);
        dom.assetGrid.innerHTML = items.map(item => {
            const selected = state.selected.has(item.id);
            const title = item.name || fileLabel(item);
            const download = api.downloadHref(item.url, fileLabel(item));
            return `<article class="asset-card${selected ? ' selected' : ''}" data-preview-id="${escapeHtml(item.id)}">
                <input class="asset-card-select" type="checkbox" data-select-id="${escapeHtml(item.id)}" ${selected ? 'checked' : ''} aria-label="选择 ${escapeHtml(title)}">
                <div class="asset-thumb"><img src="${escapeHtml(item.url)}" alt="${escapeHtml(title)}" loading="lazy"></div>
                <div class="asset-card-body">
                    <p class="asset-card-title" title="${escapeHtml(title)}">${escapeHtml(title)}</p>
                    <div class="asset-card-meta" title="${escapeHtml(fileLabel(item))}">${escapeHtml(fileLabel(item))}</div>
                    <div class="asset-card-actions">
                        <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer" title="打开"><i data-lucide="external-link"></i></a>
                        <a href="${escapeHtml(download)}" title="下载"><i data-lucide="download"></i></a>
                        <button type="button" data-copy-id="${escapeHtml(item.id)}" title="复制路径"><i data-lucide="copy"></i></button>
                        <button type="button" data-rename-id="${escapeHtml(item.id)}" title="重命名"><i data-lucide="pencil"></i></button>
                    </div>
                </div>
            </article>`;
        }).join('');
        if(!items.find(item => item.id === state.previewId)) state.previewId = items[0]?.id || '';
    }

    function renderPreview(){
        const item = itemById(state.previewId) || currentItems()[0] || null;
        if(!item){
            dom.previewPane.innerHTML = '<div class="preview-empty">选择一个资产查看详情</div>';
            return;
        }
        state.previewId = item.id;
        const title = item.name || fileLabel(item);
        dom.previewPane.innerHTML = `<div class="preview-image"><img src="${escapeHtml(item.url)}" alt="${escapeHtml(title)}"></div>
            <div class="preview-name">${escapeHtml(title)}</div>
            <div class="preview-url">${escapeHtml(item.url)}</div>
            <div class="preview-actions">
                <a class="asset-btn small" href="${escapeHtml(api.downloadHref(item.url, fileLabel(item)))}"><i data-lucide="download"></i><span>下载</span></a>
                <button class="asset-btn small" type="button" data-preview-copy="${escapeHtml(item.id)}"><i data-lucide="copy"></i><span>复制路径</span></button>
                <button class="asset-btn small" type="button" data-preview-rename="${escapeHtml(item.id)}"><i data-lucide="pencil"></i><span>重命名</span></button>
                <button class="asset-btn small danger" type="button" data-preview-delete="${escapeHtml(item.id)}"><i data-lucide="trash-2"></i><span>删除</span></button>
            </div>`;
    }

    async function withBusy(label, fn){
        if(state.busy) return;
        state.busy = true;
        setNotice(label || '处理中...');
        try { await fn(); }
        catch(err){ setNotice(err.message || '操作失败。', 'error'); }
        finally { state.busy = false; render(); }
    }

    async function createCategory(){
        const name = prompt('新分类名称');
        if(!name) return;
        await withBusy('正在新建分类...', async () => {
            const data = await api.createCategory(name.trim());
            state.library = data.library;
            state.activeCategoryId = data.category?.id || state.activeCategoryId;
            setNotice('分类已创建。', 'ok');
        });
    }

    async function renameCategory(){
        const cat = activeCategory();
        if(!cat) return;
        const name = prompt('重命名分类', cat.name || '');
        if(!name || name === cat.name) return;
        await withBusy('正在重命名分类...', async () => {
            const data = await api.renameCategory(cat.id, name.trim());
            state.library = data.library;
            setNotice('分类已重命名。', 'ok');
        });
    }

    async function deleteCategory(){
        const cat = activeCategory();
        if(!cat) return;
        const count = (cat.items || []).length;
        if(!confirm(`删除分类「${cat.name}」？${count ? `\n分类中的 ${count} 个资产记录也会从库中移除。` : ''}`)) return;
        await withBusy('正在删除分类...', async () => {
            const data = await api.deleteCategory(cat.id);
            state.library = data.library;
            state.activeCategoryId = api.activeImageCategory(state.library)?.id || '';
            state.selected.clear();
            setNotice('分类已删除。', 'ok');
        });
    }

    async function uploadToCurrent(files){
        const cat = activeCategory();
        if(!cat){ setNotice('请先创建一个图片分类。', 'error'); return; }
        const fileList = Array.from(files || []);
        if(!fileList.length) return;
        await withBusy(`正在上传 ${fileList.length} 个文件...`, async () => {
            const data = await api.uploadFiles(fileList);
            const images = (data.files || []).filter(file => file.media_kind === 'image' || api.isImageMediaUrl(file.url || file.preview_url || ''));
            if(!images.length) throw new Error('没有可保存的图片文件。');
            let saved = 0;
            for(const file of images){
                const url = file.url || file.preview_url || file.source_url;
                if(!url) continue;
                const result = await api.addItem(cat.id, url, file.name || api.fileNameFromUrl(url));
                state.library = result.library;
                saved += 1;
            }
            await loadLibrary(cat.id);
            setNotice(`已保存 ${saved} 个图片资产。`, 'ok');
        });
    }

    async function renameItem(id){
        const item = itemById(id);
        if(!item) return;
        const name = prompt('重命名资产', item.name || fileLabel(item));
        if(!name || name === item.name) return;
        await withBusy('正在重命名资产...', async () => {
            const data = await api.renameItem(id, name.trim());
            state.library = data.library;
            setNotice('资产已重命名。', 'ok');
        });
    }

    async function deleteItems(ids){
        if(!ids.length) return;
        if(!confirm(`从资产库移除 ${ids.length} 个资产记录？`)) return;
        await withBusy('正在删除资产...', async () => {
            const data = ids.length === 1 ? await api.deleteItem(ids[0]) : await api.deleteItems(ids);
            state.library = data.library;
            ids.forEach(id => state.selected.delete(id));
            if(ids.includes(state.previewId)) state.previewId = '';
            setNotice(`已移除 ${ids.length} 个资产记录。`, 'ok');
        });
    }

    async function moveSelected(){
        const ids = selectedIds();
        const targetId = dom.bulkMoveSelect.value;
        if(!ids.length || !targetId) return;
        await withBusy('正在移动资产...', async () => {
            const data = await api.moveItems(ids, targetId);
            state.library = data.library;
            state.activeCategoryId = targetId;
            state.selected.clear();
            setNotice(`已移动 ${ids.length} 个资产。`, 'ok');
        });
    }

    async function copyItemUrl(id){
        const item = itemById(id);
        if(!item) return;
        try {
            await navigator.clipboard.writeText(item.url || '');
            setNotice('路径已复制。', 'ok');
        } catch(_) {
            setNotice(item.url || '', 'ok');
        }
    }

    function bindEvents(){
        dom.refreshBtn.addEventListener('click', () => loadLibrary());
        dom.uploadBtn.addEventListener('click', () => dom.fileInput.click());
        dom.fileInput.addEventListener('change', event => {
            uploadToCurrent(event.target.files).finally(() => { event.target.value = ''; });
        });
        dom.newCategoryBtn.addEventListener('click', createCategory);
        dom.renameCategoryBtn.addEventListener('click', renameCategory);
        dom.deleteCategoryBtn.addEventListener('click', deleteCategory);
        dom.searchInput.addEventListener('input', event => { state.query = event.target.value || ''; render(); });
        dom.selectAllBtn.addEventListener('click', () => { currentItems().forEach(item => state.selected.add(item.id)); render(); });
        dom.clearSelectionBtn.addEventListener('click', () => { state.selected.clear(); render(); });
        dom.bulkMoveBtn.addEventListener('click', moveSelected);
        dom.bulkDownloadBtn.addEventListener('click', () => {
            const ids = selectedIds();
            if(!ids.length) return setNotice('请先选择要下载的资产。', 'error');
            api.downloadItems(ids, `oct-assets-${new Date().toISOString().slice(0,10)}.zip`).catch(err => setNotice(err.message || '下载失败。', 'error'));
        });
        dom.bulkDeleteBtn.addEventListener('click', () => deleteItems(selectedIds()));
        dom.categoryList.addEventListener('click', event => {
            const btn = event.target.closest('[data-category-id]');
            if(!btn) return;
            state.activeCategoryId = btn.dataset.categoryId || '';
            state.selected.clear();
            state.previewId = '';
            render();
        });
        dom.assetGrid.addEventListener('click', event => {
            const select = event.target.closest('[data-select-id]');
            if(select){
                const id = select.dataset.selectId;
                select.checked ? state.selected.add(id) : state.selected.delete(id);
                state.previewId = id;
                render();
                return;
            }
            const copy = event.target.closest('[data-copy-id]');
            if(copy) return copyItemUrl(copy.dataset.copyId);
            const rename = event.target.closest('[data-rename-id]');
            if(rename) return renameItem(rename.dataset.renameId);
            const card = event.target.closest('[data-preview-id]');
            if(card){ state.previewId = card.dataset.previewId || ''; render(); }
        });
        dom.previewPane.addEventListener('click', event => {
            const copy = event.target.closest('[data-preview-copy]');
            if(copy) return copyItemUrl(copy.dataset.previewCopy);
            const rename = event.target.closest('[data-preview-rename]');
            if(rename) return renameItem(rename.dataset.previewRename);
            const del = event.target.closest('[data-preview-delete]');
            if(del) return deleteItems([del.dataset.previewDelete]);
        });
        ['dragenter','dragover'].forEach(type => dom.dropzone.addEventListener(type, event => {
            event.preventDefault();
            dom.dropzone.classList.add('dragging');
        }));
        ['dragleave','drop'].forEach(type => dom.dropzone.addEventListener(type, event => {
            event.preventDefault();
            dom.dropzone.classList.remove('dragging');
        }));
        dom.dropzone.addEventListener('drop', event => uploadToCurrent(event.dataTransfer?.files));
    }

    function init(){
        ['backToCanvasLink','categoryCount','categoryList','renameCategoryBtn','deleteCategoryBtn','refreshBtn','uploadBtn','fileInput','searchInput','assetCount','selectionCount','dropzone','selectAllBtn','clearSelectionBtn','bulkMoveSelect','bulkMoveBtn','bulkDownloadBtn','bulkDeleteBtn','notice','assetGrid','emptyState','previewPane','newCategoryBtn'].forEach(id => dom[id] = $(id));
        if(dom.backToCanvasLink) dom.backToCanvasLink.href = canvasReturnUrl();
        bindEvents();
        loadLibrary();
    }

    document.addEventListener('DOMContentLoaded', init);
})();