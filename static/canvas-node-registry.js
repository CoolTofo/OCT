/*
 * Canvas node registry
 *
 * Code rule: keep canvas node labels, icons, and addability in this small
 * registry instead of duplicating raw type arrays or menu option literals in
 * canvas.html. Future AI/code updates should add new node metadata here first,
 * then consume it from the canvas UI to preserve a professional structure.
 */
(function initCanvasNodeRegistry(global){
    'use strict';

    const NODE_META = Object.freeze({
        generator: {labelKey:'canvas.apiGenerate', fallback:'API生成', icon:'wand-sparkles', title:'API Generate'},
        storyboard: {fallback:'分镜图工坊', icon:'layout-template', title:'分镜图工坊'},
        storyboardGrid: {fallback:'多宫格分镜', icon:'panel-top', title:'多宫格分镜'},
        msgen: {labelKey:'canvas.modelscopeGenerate', fallback:'Modelscope生成', icon:'cloud-lightning', titleKey:'canvas.modelscopeGenerate'},
        comfy: {labelKey:'canvas.comfyGenerate', fallback:'ComfyUI 生成', icon:'workflow', title:'ComfyUI'},
        rh: {fallback:'RunningHub', icon:'workflow', title:'RunningHub'},
        video: {labelKey:'canvas.videoGenerateNode', fallback:'视频生成', icon:'clapperboard', titleKey:'canvas.videoGenerateNode'},
        sd2Video: {labelKey:'canvas.sd2VideoGenerate', fallback:'SD2.0 视频', icon:'film', titleKey:'canvas.sd2VideoGenerate'},
        dreaminaImage: {fallback:'Dreamina 图', icon:'image-plus', title:'Dreamina Image'},
        dreaminaVideo: {fallback:'Dreamina 视频', icon:'terminal', title:'Dreamina Video'},
        imageExtend: {fallback:'扩展图片', icon:'expand', title:'扩展图片'},
        panorama: {fallback:'360 全景', icon:'orbit', title:'360 全景'},
        png: {labelKey:'canvas.pngComposeNode', fallback:'PNG 合成节点', icon:'file-image', titleKey:'canvas.pngComposeNode'},
        output: {fallback:'Output', icon:'circle-dot', title:'Output'},
        image: {labelKey:'canvas.imageCard', fallback:'图片卡片', icon:'image-plus', title:'Image'},
        prompt: {labelKey:'canvas.prompt', fallback:'提示词', icon:'text-cursor-input', title:'Prompt'},
        poseEditor: {fallback:'\u59ff\u52bf\u7f16\u8f91', icon:'person-standing', title:'\u59ff\u52bf\u7f16\u8f91'},
        flowFrame: {fallback:'流帧心法', icon:'film', title:'流帧心法'},
        scriptPlanner: {fallback:'长剧本拆分', icon:'scroll-text', title:'长剧本拆分'},
        scriptSection: {fallback:'剧情段落', icon:'file-text', title:'剧情段落'},
        scriptSegment: {fallback:'10-15s小段', icon:'list-video', title:'10-15s小段'},
        seedanceDirector: {fallback:'Seedance导演Agent', icon:'clapperboard', title:'Seedance导演Agent'},
        loop: {labelKey:'canvas.loopNode', fallback:'循环节点', icon:'repeat-2', titleKey:'canvas.loopNode'},
        group: {labelKey:'canvas.group', fallback:'分组', icon:'group', title:'Group'},
        llm: {fallback:'LLM', icon:'message-square-text', title:'LLM'}
    });

    const GENERATOR_TYPES = Object.freeze(['generator','storyboardGrid','msgen','comfy','rh','video','png','dreamina','imageExtend','panorama']);
    const IMAGE_OUTPUT_TYPES = Object.freeze(['generator','storyboardGrid','msgen','comfy','rh','png','dreamina','imageExtend','panorama']);
    const ADDABLE_GENERATOR_TYPES = Object.freeze(['generator','storyboard','storyboardGrid','msgen','comfy','rh','video','sd2Video','dreaminaImage','dreaminaVideo','png','imageExtend','panorama']);
    const ADDABLE_SOURCE_TYPES = Object.freeze(['image','prompt','poseEditor','flowFrame','loop','group','llm']);
    const NODE_PALETTE_SECTIONS = Object.freeze([
        {id:'source', fallback:'素材', types:['image','prompt','poseEditor','flowFrame','scriptPlanner','seedanceDirector','loop','group','output']},
        {id:'imageGen', fallback:'图片 / 合成', types:['generator','storyboard','storyboardGrid','msgen','png','imageExtend','panorama']},
        {id:'videoGen', fallback:'视频', types:['video','sd2Video','dreaminaImage','dreaminaVideo']},
        {id:'workflow', fallback:'工作流 / AI', types:['llm','comfy','rh']}
    ]);

    function resolveText(meta, tr, primaryKey){
        const key = primaryKey || meta.labelKey;
        if(key && typeof tr === 'function') return tr(key);
        return meta.fallback || meta.title || '';
    }

    function option(type, tr){
        const meta = NODE_META[type] || {fallback:type, icon:'circle'};
        return {type, label:resolveText(meta, tr), icon:meta.icon || 'circle'};
    }

    function addableGeneratorOptions(tr){
        return ADDABLE_GENERATOR_TYPES.map(type => option(type, tr));
    }

    function addableSourceOptions(tr){
        return ADDABLE_SOURCE_TYPES.map(type => option(type, tr));
    }

    function nodePaletteSections(tr){
        return NODE_PALETTE_SECTIONS.map(section => ({
            id:section.id,
            title:section.fallback,
            items:section.types.map(type => option(type, tr))
        }));
    }

    function titleFor(type, tr){
        const meta = NODE_META[type];
        if(!meta) return '';
        if(meta.titleKey && typeof tr === 'function') return tr(meta.titleKey);
        return meta.title || resolveText(meta, tr);
    }

    global.CanvasNodeRegistry = Object.freeze({
        NODE_META,
        GENERATOR_TYPES,
        IMAGE_OUTPUT_TYPES,
        addableGeneratorOptions,
        addableSourceOptions,
        nodePaletteSections,
        titleFor
    });
})(window);
