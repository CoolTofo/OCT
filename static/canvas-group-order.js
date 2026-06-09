/*
 * Group visual ordering helpers.
 *
 * Group image references should be stable from the layout itself: top row
 * first, left to right within each row. This avoids depending on the order in
 * which images were selected, dragged into the group, or restored from saved
 * data.
 */
(function initCanvasGroupOrder(global){
    'use strict';

    function fallbackRect(node){
        const x = Number(node?.x || 0);
        const y = Number(node?.y || 0);
        const w = Number(node?.w || 260);
        const h = Number(node?.h || 200);
        return {x, y, w, h, cx:x + w / 2, cy:y + h / 2};
    }

    function rectFor(node, measureNode){
        const rect = typeof measureNode === 'function' ? measureNode(node) : null;
        if(rect && Number.isFinite(rect.cx) && Number.isFinite(rect.cy)) return rect;
        return fallbackRect(node);
    }

    function orderedByVisualPosition(items, measureNode){
        const entries = (items || [])
            .filter(Boolean)
            .map((node, index) => ({node, index, rect:rectFor(node, measureNode)}))
            .sort((a, b) => a.rect.cy - b.rect.cy || a.rect.cx - b.rect.cx || a.index - b.index);
        const rows = [];
        entries.forEach(entry => {
            const h = Math.max(1, Number(entry.rect.h || 0));
            let row = rows.find(candidate => Math.abs(entry.rect.cy - candidate.cy) <= Math.max(24, Math.min(candidate.avgH, h) * 0.35));
            if(!row){
                row = {cy:entry.rect.cy, avgH:h, items:[]};
                rows.push(row);
            }
            row.items.push(entry);
            row.cy = row.items.reduce((sum, item) => sum + item.rect.cy, 0) / row.items.length;
            row.avgH = row.items.reduce((sum, item) => sum + Math.max(1, Number(item.rect.h || 0)), 0) / row.items.length;
        });
        return rows
            .sort((a, b) => a.cy - b.cy)
            .flatMap(row => row.items.sort((a, b) => a.rect.cx - b.rect.cx || a.rect.cy - b.rect.cy || a.index - b.index))
            .map(entry => entry.node);
    }

    function orderedGroupItems(group, allNodes, measureNode, filter=null){
        const nodeById = new Map((allNodes || []).filter(Boolean).map(node => [node.id, node]));
        const items = (group?.items || [])
            .map(id => nodeById.get(id))
            .filter(node => node && (!filter || filter(node)));
        return orderedByVisualPosition(items, measureNode);
    }

    global.CanvasGroupOrder = Object.freeze({
        orderedByVisualPosition,
        orderedGroupItems
    });
})(window);
