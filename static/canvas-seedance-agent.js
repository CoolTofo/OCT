/*
 * Seedance Director Agent helper.
 *
 * Pure prompt builders and normalizers for the canvas-level director node.
 */
(function initCanvasSeedanceAgent(global){
    'use strict';

    function cleanText(value){
        return String(value ?? '').trim();
    }

    function cleanList(value){
        if(Array.isArray(value)) return value.map(cleanText).filter(Boolean);
        const text = cleanText(value);
        if(!text) return [];
        return text.split(/\n+/).map(item => item.replace(/^\s*[-*0-9.、，:：]+\s*/, '').trim()).filter(Boolean);
    }

    function normalizeMap(value){
        if(value && typeof value === 'object' && !Array.isArray(value)) return value;
        return {};
    }

    function stripJsonFence(text){
        return cleanText(text).replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
    }

    function parseJsonBlock(raw){
        const text = stripJsonFence(raw);
        if(!text) throw new Error('empty json');
        try { return JSON.parse(text); } catch(_err) {}
        const start = text.indexOf('{');
        const end = text.lastIndexOf('}');
        if(start >= 0 && end > start) return JSON.parse(text.slice(start, end + 1));
        throw new Error('invalid json');
    }

    function rules(){
        return global.CanvasSeedanceAgentRules || {};
    }

    function defaults(){
        return rules().DEFAULTS || {};
    }

    function assetLines(assets){
        const list = assets || [];
        if(!list.length) return '- 无参考素材';
        return list.map(asset => {
            const limit = asset.included === false ? '（超出上限，正式生成时不纳入）' : '';
            return `- ${asset.tag || asset.id}：${asset.role || asset.name || ''}${limit}；文件：${asset.name || asset.sourceLabel || ''}`;
        }).join('\n');
    }

    function normalizeReferenceContract(value, assets=[]){
        const raw = normalizeMap(value);
        const contract = {};
        assets.forEach(asset => {
            const key = asset.tag || asset.id;
            contract[key] = cleanText(raw[key] || raw[asset.id] || raw[asset.sourceId] || asset.role || '');
        });
        Object.keys(raw).forEach(key => {
            if(!contract[key]) contract[key] = cleanText(raw[key]);
        });
        return contract;
    }

    function fallbackAnalysis(options={}){
        const assets = options.assets || [];
        const contract = normalizeReferenceContract({}, assets);
        const scriptText = cleanText(options.scriptText);
        return {
            taskType:assets.length ? 'multi-image-reference' : (scriptText.length > 900 ? 'long-script' : 'text-to-video'),
            projectSummary:scriptText ? scriptText.slice(0, 220) : '未填写剧本，等待输入。',
            storyAnalysis:'按原文剧情目标、情绪推进和动作因果建立镜头节奏。',
            styleBible:defaults().styleText || '',
            characterPerformance:'逐段明确人物表情、眼神、身体重心、姿态变化和台词节奏。',
            blockingPlan:'逐段明确左右关系、前后关系、入画/出画方向、视线方向和道具承接。',
            shotIntent:'根据剧情自然断点决定镜头数量和时长，禁止机械平均。',
            referenceContract:contract,
            continuityRules:[
                '保留原文台词、标点和顺序。',
                '每段入场状态必须承接上一段出场状态。',
                '人物姿态、走位、空间轴线、道具和光线必须连续。'
            ],
            warnings:['AI 分析不可用时使用了本地兜底分析。'],
            raw:'',
            parseError:true
        };
    }

    function normalizeAnalysis(raw, options={}){
        try {
            const parsed = parseJsonBlock(raw);
            const assets = options.assets || [];
            return {
                taskType:cleanText(parsed.taskType || parsed.task || parsed.type) || fallbackAnalysis(options).taskType,
                projectSummary:cleanText(parsed.projectSummary || parsed.summary || parsed.overview),
                storyAnalysis:cleanText(parsed.storyAnalysis || parsed.scriptAnalysis || parsed.story),
                styleBible:cleanText(parsed.styleBible || parsed.style || parsed.visualStyle) || defaults().styleText || '',
                characterPerformance:cleanText(parsed.characterPerformance || parsed.performance || parsed.characters),
                blockingPlan:cleanText(parsed.blockingPlan || parsed.blocking || parsed.spatialPlan),
                shotIntent:cleanText(parsed.shotIntent || parsed.shotStrategy || parsed.pacing),
                referenceContract:normalizeReferenceContract(parsed.referenceContract || parsed.assetUsage || parsed.references, assets),
                continuityRules:cleanList(parsed.continuityRules || parsed.continuity || parsed.rules),
                warnings:cleanList(parsed.warnings),
                raw:cleanText(raw),
                parseError:false
            };
        } catch(err) {
            const fallback = fallbackAnalysis(options);
            fallback.raw = cleanText(raw);
            fallback.warnings = [`分析 JSON 解析失败，已使用本地兜底：${err.message}`];
            return fallback;
        }
    }

    function analysisText(analysis){
        const a = analysis || {};
        const refLines = Object.entries(a.referenceContract || {})
            .map(([key, value]) => `- ${key}：${value}`)
            .join('\n');
        const continuity = cleanList(a.continuityRules).map(item => `- ${item}`).join('\n');
        return [
            `任务类型：${a.taskType || 'auto'}`,
            '',
            '项目理解：',
            a.projectSummary || '',
            '',
            '剧本分析：',
            a.storyAnalysis || '',
            '',
            '摄影风格：',
            a.styleBible || defaults().styleText || '',
            '',
            '人物表演：',
            a.characterPerformance || '',
            '',
            '人物走位 / 空间调度：',
            a.blockingPlan || '',
            '',
            '镜头节奏意图：',
            a.shotIntent || '',
            '',
            '参考素材协议：',
            refLines || '- 无',
            '',
            '连续性规则：',
            continuity || '- 保持上下文衔接。'
        ].join('\n').trim();
    }

    function buildAnalysisPrompt(options={}){
        const rulesText = rules().rulesSummary ? rules().rulesSummary() : '';
        const checklist = (rules().AUDIT_CHECKLIST || []).map(item => `- ${item}`).join('\n');
        const scriptText = cleanText(options.scriptText);
        const assets = options.assets || [];
        return [
            '任务：你是 Seedance 2.0 AI 导演 Agent 的总控分析师。',
            '你必须先理解剧本、风格、人物表演、人物走位、参考素材用途和上下文连续性，再给后续分段和流帧心法使用。',
            '不要生成最终视频提示词；这里只做结构化分析和参考素材协议。',
            '',
            '手动维护的 Seedance 规则：',
            rulesText,
            '',
            '审核清单：',
            checklist,
            '',
            '参考素材候选：',
            assetLines(assets),
            '',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"taskType":"","projectSummary":"","storyAnalysis":"","styleBible":"","characterPerformance":"","blockingPlan":"","shotIntent":"","referenceContract":{"@image1":""},"continuityRules":[""],"warnings":[""]}',
            '',
            '分析要求：',
            '- taskType 从 text-to-video、image-to-video、multi-image-reference、video-reference、audio-reference、long-script、shot-rewrite、extension 中选择最贴近的一项。',
            '- referenceContract 必须逐项列出每个 @imageN / @videoN / @audioN 的用途，不能合并成“参考图”。',
            '- characterPerformance 要写表情、眼神、身体重心、动作承接和台词表演。',
            '- blockingPlan 要写左右关系、前后关系、视线方向、入画/出画方向、镜头轴线和道具位置。',
            '- shotIntent 只描述当前剧本的节奏判断，禁止输出通用模板菜单，禁止机械平均镜头时长。',
            '',
            '完整剧本 / 用户需求：',
            scriptText || '未填写'
        ].join('\n');
    }

    function buildPlannerScriptInput(options={}){
        const scriptText = cleanText(options.scriptText);
        const analysis = options.analysis || {};
        return [
            '【完整原文】',
            scriptText || '未填写',
            '',
            '【Seedance导演Agent分析】',
            analysisText(analysis),
            '',
            '【执行要求】',
            '请按完整原文自然节奏拆分，不改写台词，不删除标点，不机械平均时长。',
            '每段必须承接上一段出场状态，并把参考素材协议传递给流帧心法。'
        ].join('\n');
    }

    function buildPromptReviewPrompt(options={}){
        const analysis = options.analysis || {};
        const prompts = cleanText(options.prompts);
        return [
            '任务：你是 Seedance 2.0 导演 Agent 的总审核员。',
            '请审核所有分段提示词是否符合剧本、参考素材、人物走位、上下文衔接和 Seedance 约束。',
            '只输出严格 JSON，不要 Markdown。字段固定为：',
            '{"pass":boolean,"blockingIssues":[""],"warnings":[""],"fixInstructions":[""],"summary":""}',
            '',
            '总控分析：',
            analysisText(analysis),
            '',
            '审核重点：',
            (rules().AUDIT_CHECKLIST || []).map(item => `- ${item}`).join('\n'),
            '',
            '待审核提示词：',
            prompts || '无'
        ].join('\n');
    }

    function normalizeDirectorReview(raw){
        try {
            const parsed = parseJsonBlock(raw);
            const blockingIssues = cleanList(parsed.blockingIssues);
            return {
                pass:Boolean(parsed.pass) && !blockingIssues.length,
                blockingIssues,
                warnings:cleanList(parsed.warnings),
                fixInstructions:cleanList(parsed.fixInstructions),
                summary:cleanText(parsed.summary),
                raw:cleanText(raw),
                parseError:false
            };
        } catch(err) {
            return {
                pass:false,
                blockingIssues:['审核 JSON 解析失败，无法确认通过。'],
                warnings:[cleanText(raw) || err.message],
                fixInstructions:['请重新审核提示词的连续性、素材映射和时间码。'],
                summary:'',
                raw:cleanText(raw),
                parseError:true
            };
        }
    }

    global.CanvasSeedanceAgent = Object.freeze({
        normalizeAnalysis,
        buildAnalysisPrompt,
        buildPlannerScriptInput,
        buildPromptReviewPrompt,
        normalizeDirectorReview,
        analysisText,
        assetLines
    });
})(window);
