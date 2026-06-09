(function(){
    const LOCAL_KEYS = new Set([
        'id',
        'x',
        'y',
        'w',
        'h',
        'items',
        'inputs',
        'linkedCloneId',
        'running',
        'runStatus',
        'runError',
        '_pending',
        '_cascadeFailed',
        '_cascadeIdx',
        'jpgBusy'
    ]);

    function clone(value){
        return value == null ? value : JSON.parse(JSON.stringify(value));
    }

    function syncPayload(node){
        const payload = {};
        Object.keys(node || {}).sort().forEach(key => {
            if(LOCAL_KEYS.has(key)) return;
            payload[key] = clone(node[key]);
        });
        return payload;
    }

    function payloadJson(node){
        return JSON.stringify(syncPayload(node));
    }

    function applyPayload(target, payload){
        if(!target || !payload) return false;
        let changed = false;
        Object.keys(target).forEach(key => {
            if(LOCAL_KEYS.has(key)) return;
            if(Object.prototype.hasOwnProperty.call(payload, key)) return;
            delete target[key];
            changed = true;
        });
        Object.entries(payload).forEach(([key, value]) => {
            const next = clone(value);
            if(JSON.stringify(target[key]) === JSON.stringify(next)) return;
            target[key] = next;
            changed = true;
        });
        return changed;
    }

    function ensureGroupId(node, uid){
        if(!node) return '';
        if(!node.linkedCloneId) node.linkedCloneId = uid('lnk');
        return node.linkedCloneId;
    }

    window.CanvasLinkedClones = {
        applyPayload,
        ensureGroupId,
        payloadJson,
        syncPayload
    };
})();
