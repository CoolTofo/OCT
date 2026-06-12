/*
 * Seedance Director Agent manually maintained rules.
 *
 * Keep these rules editable and versioned. The canvas agent reads this file
 * instead of fetching live docs at runtime, so behavior is reproducible.
 */
(function initCanvasSeedanceAgentRules(global){
    'use strict';

    const VERSION = '2026-06-11-manual-v1';

    const LIMITS = Object.freeze({
        segmentMinSeconds:4,
        segmentDefaultMinSeconds:10,
        segmentMaxSeconds:15,
        imageMaxCount:9,
        videoMaxCount:3,
        videoTotalMaxSeconds:15,
        audioMaxCount:3,
        audioTotalMaxSeconds:15,
        audioMaxMb:15,
        requestMaxMb:64
    });

    const DEFAULTS = Object.freeze({
        aspectRatio:'16:9',
        fps:24,
        cinemaProfile:'deakins',
        promptLanguage:'zh',
        stageMode:'staged',
        styleText:[
            '罗杰·迪金斯 / Roger Deakins 风格。',
            '自然主义电影摄影，动机光源，低调光，克制运镜，清晰空间层次。',
            '强调真实空气感、胶片质感、剪影、柔和高光控制和人物与环境的空间关系。'
        ].join(' '),
        negativeText:[
            '无水印，无 logo，无字幕，无屏幕文字。',
            '无低清晰度，无塑料皮肤，无蜡像感，无脸部变形，无肢体畸形。',
            '无闪烁，无过曝或欠曝，无跳轴，无空间关系混乱。'
        ].join(' ')
    });

    const TASK_TYPES = Object.freeze([
        'text-to-video',
        'image-to-video',
        'multi-image-reference',
        'video-reference',
        'audio-reference',
        'long-script',
        'shot-rewrite',
        'extension'
    ]);

    const AUDIT_CHECKLIST = Object.freeze([
        '剧情因果：前后镜头的动作起点、承接和结果不能跳跃。',
        '人物连续：身份、服装、道具、姿态、表情、视线和动作方向保持一致。',
        '走位空间：左右关系、前后关系、距离变化、入画/出画方向和镜头轴线清楚。',
        '镜头逻辑：景别变化有动机，每个镜头只保留一种主运镜，不机械平均时间码。',
        '素材映射：每张图片、视频、音频必须稳定使用 @imageN / @videoN / @audioN。',
        '台词音效：保留中文原文、标点和顺序，并放入合理时间码。',
        'Seedance 可生成性：主体定义清楚，动作可视化，约束明确，避免抽象空话。'
    ]);

    const STAGE_LABELS = Object.freeze({
        idle:'待开始',
        analyzing:'分析剧本中',
        analyzed:'分析完成',
        planning:'生成分段分镜中',
        planned:'分段分镜完成',
        prompting:'生成并审核提示词中',
        complete:'完成',
        failed:'失败'
    });

    function rulesSummary(){
        return [
            `规则版本：${VERSION}`,
            `单段视频：${LIMITS.segmentMinSeconds}-${LIMITS.segmentMaxSeconds} 秒，长剧本默认拆成 ${LIMITS.segmentDefaultMinSeconds}-${LIMITS.segmentMaxSeconds} 秒小段。`,
            `参考图最多 ${LIMITS.imageMaxCount} 张；参考视频最多 ${LIMITS.videoMaxCount} 个且总时长不超过 ${LIMITS.videoTotalMaxSeconds} 秒；参考音频最多 ${LIMITS.audioMaxCount} 个且总时长不超过 ${LIMITS.audioTotalMaxSeconds} 秒。`,
            '多图必须逐张映射，禁止只写“参考图”。',
            '长剧本必须按剧情自然节奏拆分，不使用固定平均时间模板。',
            '最终提示词需要包含模式、素材映射、镜头策略、正式提示词、摄影风格、负面约束、生成设置。'
        ].join('\n');
    }

    global.CanvasSeedanceAgentRules = Object.freeze({
        VERSION,
        LIMITS,
        DEFAULTS,
        TASK_TYPES,
        AUDIT_CHECKLIST,
        STAGE_LABELS,
        rulesSummary
    });
})(window);
