/*
 * Organize frame membership helpers.
 *
 * A node belongs to an organize frame when the node center is inside the
 * frame bounds. Organize frames are visual containers only, so they never
 * become children of other organize frames.
 */
(function initCanvasOrganizeFrames(global){
    'use strict';

    const RESIZE_DIRECTIONS = Object.freeze(['n', 'e', 's', 'w', 'ne', 'nw', 'se', 'sw']);
    const RESIZE_CURSORS = Object.freeze({
        n:'n-resize',
        e:'e-resize',
        s:'s-resize',
        w:'w-resize',
        ne:'nesw-resize',
        nw:'nwse-resize',
        se:'nwse-resize',
        sw:'nesw-resize'
    });

    function normalizeResizeDirection(direction){
        return RESIZE_DIRECTIONS.includes(direction) ? direction : 'se';
    }

    function resizeCursor(direction){
        return RESIZE_CURSORS[normalizeResizeDirection(direction)] || RESIZE_CURSORS.se;
    }

    function rectFor(node, measureNode){
        if(typeof measureNode === 'function') return measureNode(node);
        const w = Number(node?.w || 260);
        const h = Number(node?.h || 200);
        const x = Number(node?.x || 0);
        const y = Number(node?.y || 0);
        return {x, y, w, h, cx:x + w / 2, cy:y + h / 2};
    }

    function isOrganizeFrame(node){
        return node?.type === 'organizeFrame';
    }

    function nodeCenterInsideFrame(node, frame, measureNode){
        if(!node || !frame || node.id === frame.id || isOrganizeFrame(node)) return false;
        const nr = rectFor(node, measureNode);
        const fr = rectFor(frame, measureNode);
        return nr.cx >= fr.x && nr.cx <= fr.x + fr.w && nr.cy >= fr.y && nr.cy <= fr.y + fr.h;
    }

    function frameMembershipIds(nodes, frame, measureNode){
        return (nodes || [])
            .filter(node => nodeCenterInsideFrame(node, frame, measureNode))
            .map(node => node.id);
    }

    function sameIdList(a, b){
        if(!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
        return a.every((id, index) => id === b[index]);
    }

    global.CanvasOrganizeFrames = Object.freeze({
        RESIZE_DIRECTIONS,
        frameMembershipIds,
        isOrganizeFrame,
        nodeCenterInsideFrame,
        normalizeResizeDirection,
        resizeCursor,
        sameIdList
    });
})(window);
