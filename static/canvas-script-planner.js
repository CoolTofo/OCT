/*
 * Long script planner helper.
 *
 * Pure helpers for splitting a long script into continuity-aware 10-15 second
 * segments before each segment is handed to the Flow Frame agent.
 */
(function initCanvasScriptPlanner(global){
    'use strict';

    const DEFAULTS = Object.freeze({
        segmentMinSeconds:10,
        segmentMaxSeconds:15,
        language:'zh',
        maxSegmentSeconds:15,
        minSegmentSeconds:10
    });

    function cleanText(value){
        return String(value ?? '').trim();
    }

    function numberValue(value, fallback, min, max){
        const num = Number(value);
        if(!Number.isFinite(num)) return fallback;
        return Math.max(min, Math.min(max, num));
    }

    function normalizeBounds(node={}){
        const min = numberValue(node.segmentMinSeconds, DEFAULTS.segmentMinSeconds, 4, 15);
        const max = numberValue(node.segmentMaxSeconds, DEFAULTS.segmentMaxSeconds, min, 20);
        return {min, max};
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

    function cleanList(value){
        if(Array.isArray(value)) return value.map(cleanText).filter(Boolean);
        const text = cleanText(value);
        if(!text) return [];
        return text.split(/\n+/).map(item => item.replace(/^\s*[-*•\d.、)）]+\s*/, '').trim()).filter(Boolean);
    }

    function normalizeMap(value){
        if(value && typeof value === 'object' && !Array.isArray(value)) return value;
        return {};
    }

    function segmentId(index){
        return `S${String(index + 1).padStart(2, '0')}`;
    }

    function paragraphUnits(scriptText){
        const text = cleanText(scriptText);
        if(!text) return [];
        const paragraphs = text.split(/\n{2,}/).map(cleanText).filter(Boolean);
        if(paragraphs.length > 1) return paragraphs;
        const lines = text.split(/\n+/).map(cleanText).filter(Boolean);
        if(lines.length > 1) return lines;
        const sentences = text.match(/[^。！？!?；;]+[。！？!?；;]?/g) || [text];
        return sentences.map(cleanText).filter(Boolean);
    }

    function fallbackSegments(scriptText, bounds=DEFAULTS){
        const units = paragraphUnits(scriptText);
        if(!units.length) return [];
        const targetChars = 260;
        const chunks = [];
        let current = '';
        units.forEach(unit => {
            const next = current ? `${current}\n${unit}` : unit;
            if(current && next.length > targetChars){
                chunks.push(current);
                current = unit;
            } else {
                current = next;
            }
        });
        if(current) chunks.push(current);
        return chunks.map((text, index) => ({
            id:segmentId(index),
            title:`第 ${index + 1} 段`,
            originalText:text,
            targetDuration:Math.min(bounds.max || DEFAULTS.segmentMaxSeconds, Math.max(bounds.min || DEFAULTS.segmentMinSeconds, Math.round(text.length / 24) || bounds.min || DEFAULTS.segmentMinSeconds)),
            entryState:index === 0 ? '承接长剧本开场状态。' : '承接上一段结尾的人物姿态、走位、情绪和空间方向。',
            exitState:'为下一段保留清晰的人物位置、姿态、道具和情绪落点。',
            transitionIn:index === 0 ? '开场进入。' : '从上一段结尾自然接入。',
            transitionOut:index === chunks.length - 1 ? '本段收束。' : '向下一段动作或情绪推进。',
            assetUsage:{},
            notes:'本地兜底拆分，建议重新调用 LLM 生成更准确的剧情段落。'
        }));
    }

    function fallbackSections(scriptText){
        const units = paragraphUnits(scriptText);
        if(!units.length) return [];
        const targetChars = 900;
        const chunks = [];
        let current = '';
        units.forEach(unit => {
            const next = current ? `${current}\n${unit}` : unit;
            if(current && next.length > targetChars){
                chunks.push(current);
                current = unit;
            } else {
                current = next;
            }
        });
        if(current) chunks.push(current);
        return chunks.map((text, index) => ({
            id:`P${String(index + 1).padStart(2, '0')}`,
            title:`剧情段落 ${index + 1}`,
            originalText:text,
            entryState:index === 0 ? '承接长剧本开场状态。' : '承接上一剧情段落结尾的人物姿态、走位、情绪和空间方向。',
            exitState:'为下一剧情段落保留清晰的人物位置、姿态、道具和情绪落点。',
            transitionIn:index === 0 ? '开场进入。' : '从上一剧情段落自然接入。',
            transitionOut:index === chunks.length - 1 ? '本剧情段落收束。' : '向下一剧情段落推进。',
            assetUsage:{},
            notes:'本地兜底剧情段落拆分，建议重新调用 LLM。'
        }));
    }

    function normalizeContinuityBible(value){
        const bible = normalizeMap(value);
        return {
            characters:cleanList(bible.characters || bible.roles || bible.people || bible['角色']),
            wardrobe:cleanList(bible.wardrobe || bible.costumes || bible['服装']),
            props:cleanList(bible.props || bible.objects || bible['道具']),
            spaces:cleanList(bible.spaces || bible.locations || bible.scenes || bible['空间']),
            timeline:cleanList(bible.timeline || bible.beats || bible['时间线']),
            visualRules:cleanList(bible.visualRules || bible.styleRules || bible['视觉规则']),
            summary:cleanText(bible.summary || bible.overview || bible['摘要'])
        };
    }

    function normalizeSegment(item, index, bounds, scriptText){
        const fallback = fallbackSegments(scriptText, bounds)[index] || {};
        const raw = normalizeMap(item);
        const duration = numberValue(
            raw.targetDuration ?? raw.duration ?? raw.seconds ?? raw['目标时长'],
            fallback.targetDuration || bounds.min || DEFAULTS.segmentMinSeconds,
            3,
            bounds.max || DEFAULTS.segmentMaxSeconds
        );
        return {
            id:cleanText(raw.id || raw.segmentId || raw['段落ID']) || segmentId(index),
            title:cleanText(raw.title || raw.name || raw['标题']) || fallback.title || `第 ${index + 1} 段`,
            originalText:cleanText(raw.originalText || raw.sourceText || raw.excerpt || raw.text || raw['原文'] || raw['原文摘录']) || fallback.originalText || '',
            targetDuration:Number(duration.toFixed(1)),
            entryState:cleanText(raw.entryState || raw.startState || raw['入场状态']) || fallback.entryState || '',
            exitState:cleanText(raw.exitState || raw.endState || raw['出场状态']) || fallback.exitState || '',
            transitionIn:cleanText(raw.transitionIn || raw.previousLink || raw['入场衔接']) || fallback.transitionIn || '',
            transitionOut:cleanText(raw.transitionOut || raw.nextLink || raw['出场衔接']) || fallback.transitionOut || '',
            assetUsage:normalizeMap(raw.assetUsage || raw.imageUsage || raw['素材用途']),
            notes:cleanText(raw.notes || raw.reason || raw['说明']) || fallback.notes || ''
        };
    }

    function normalizeSection(item, index, scriptText){
        const fallback = fallbackSections(scriptText)[index] || {};
        const raw = normalizeMap(item);
        return {
            id:cleanText(raw.id || raw.sectionId || raw['段落ID']) || fallback.id || `P${String(index + 1).padStart(2, '0')}`,
            title:cleanText(raw.title || raw.name || raw['标题']) || fallback.title || `剧情段落 ${index + 1}`,
            originalText:cleanText(raw.originalText || raw.sourceText || raw.excerpt || raw.text || raw['原文'] || raw['原文摘录']) || fallback.originalText || '',
            entryState:cleanText(raw.entryState || raw.startState || raw['入场状态']) || fallback.entryState || '',
            exitState:cleanText(raw.exitState || raw.endState || raw['出场状态']) || fallback.exitState || '',
            transitionIn:cleanText(raw.transitionIn || raw.previousLink || raw['入场衔接']) || fallback.transitionIn || '',
            transitionOut:cleanText(raw.transitionOut || raw.nextLink || raw['出场衔接']) || fallback.transitionOut || '',
            assetUsage:normalizeMap(raw.assetUsage || raw.imageUsage || raw['素材用途']),
            notes:cleanText(raw.notes || raw.reason || raw['说明']) || fallback.notes || ''
        };
    }

    function normalizePlanResult(raw, options={}){
        const scriptText = cleanText(options.scriptText);
        const bounds = options.bounds || normalizeBounds(options.node || {});
        const warnings = [];
        let parsed = null;
        try {
            parsed = parseJsonBlock(raw);
        } catch(err) {
            warnings.push(`拆分 JSON 解析失败，已使用本地兜底拆分：${err.message}`);
            const segments = fallbackSegments(scriptText, bounds);
            return {
                continuityBible:normalizeContinuityBible({summary:'本地兜底：未获得可靠的全局连续性分析。'}),
                segments,
                warnings,
                raw:cleanText(raw),
                parseError:true
            };
        }
        const segmentItems = Array.isArray(parsed.segments) ? parsed.segments : Array.isArray(parsed['segments']) ? parsed['segments'] : Array.isArray(parsed['段落']) ? parsed['段落'] : [];
        const segments = segmentItems.map((item, index) => normalizeSegment(item, index, bounds, scriptText)).filter(seg => seg.originalText);
        if(!segments.length){
            warnings.push('LLM 未返回有效段落，已使用本地兜底拆分。');
            segments.push(...fallbackSegments(scriptText, bounds));
        }
        return {
            continuityBible:normalizeContinuityBible(parsed.continuityBible || parsed.bible || parsed['连续性总表'] || parsed),
            segments,
            warnings:[...warnings, ...cleanList(parsed.warnings || parsed['警告'])],
            raw:cleanText(raw),
            parseError:false
        };
    }

    function normalizeSectionPlanResult(raw, options={}){
        const scriptText = cleanText(options.scriptText);
        const warnings = [];
        let parsed = null;
        try {
            parsed = parseJsonBlock(raw);
        } catch(err) {
            warnings.push(`剧情段落 JSON 解析失败，已使用本地兜底拆分：${err.message}`);
            return {
                continuityBible:normalizeContinuityBible({summary:'本地兜底：未获得可靠的全局连续性分析。'}),
                sections:fallbackSections(scriptText),
                warnings,
                raw:cleanText(raw),
                parseError:true
            };
        }
        const sectionItems = Array.isArray(parsed.sections) ? parsed.sections : Array.isArray(parsed['剧情段落']) ? parsed['剧情段落'] : Array.isArray(parsed.segments) ? parsed.segments : [];
        const sections = sectionItems.map((item, index) => normalizeSection(item, index, scriptText)).filter(section => section.originalText);
        if(!sections.length){
            warnings.push('LLM 未返回有效剧情段落，已使用本地兜底拆分。');
            sections.push(...fallbackSections(scriptText));
        }
        return {
            continuityBible:normalizeContinuityBible(parsed.continuityBible || parsed.bible || parsed['连续性总表'] || parsed),
            sections,
            warnings:[...warnings, ...cleanList(parsed.warnings || parsed['警告'])],
            raw:cleanText(raw),
            parseError:false
        };
    }

    function normalizeGlobalAnalysis(raw){
        const warnings = [];
        try {
            const parsed = parseJsonBlock(raw);
            return {
                continuityBible:normalizeContinuityBible(parsed.continuityBible || parsed.bible || parsed['连续性总表'] || parsed),
                warnings:cleanList(parsed.warnings || parsed['警告']),
                raw:cleanText(raw),
                parseError:false
            };
        } catch(err) {
            warnings.push(`全局分析 JSON 解析失败：${err.message}`);
            return {
                continuityBible:normalizeContinuityBible({summary:cleanText(raw) || '全局分析未返回可靠 JSON。'}),
                warnings,
                raw:cleanText(raw),
                parseError:true
            };
        }
    }

    function normalizeSegmentDetail(raw, segment={}, options={}){
        let parsed = null;
        const warnings = [];
        try {
            parsed = parseJsonBlock(raw);
        } catch(err) {
            warnings.push(`分段细化 JSON 解析失败，已保留原始文本：${err.message}`);
            return {
                segmentId:segment.id || '',
                title:segment.title || '',
                originalText:segment.originalText || '',
                targetDuration:segment.targetDuration || options.targetDuration || DEFAULTS.segmentMaxSeconds,
                entryState:segment.entryState || '',
                exitState:segment.exitState || '',
                transitionIn:segment.transitionIn || '',
                transitionOut:segment.transitionOut || '',
                shotOutline:cleanText(raw) || segment.originalText || '',
                detailedScript:cleanText(raw) || segment.originalText || '',
                flowFrameBrief:cleanText(raw) || segment.originalText || '',
                assetUsage:segment.assetUsage || {},
                warnings,
                raw:cleanText(raw),
                parseError:true
            };
        }
        const detail = normalizeMap(parsed);
        return {
            segmentId:cleanText(detail.segmentId || detail.id || detail['段落ID']) || segment.id || '',
            title:cleanText(detail.title || detail['标题']) || segment.title || '',
            originalText:cleanText(detail.originalText || detail.sourceText || detail['原文']) || segment.originalText || '',
            targetDuration:numberValue(detail.targetDuration ?? detail.duration ?? detail['目标时长'], segment.targetDuration || options.targetDuration || DEFAULTS.segmentMaxSeconds, 3, DEFAULTS.segmentMaxSeconds),
            entryState:cleanText(detail.entryState || detail['入场状态']) || segment.entryState || '',
            exitState:cleanText(detail.exitState || detail['出场状态']) || segment.exitState || '',
            transitionIn:cleanText(detail.transitionIn || detail['入场衔接']) || segment.transitionIn || '',
            transitionOut:cleanText(detail.transitionOut || detail['出场衔接']) || segment.transitionOut || '',
            shotOutline:cleanText(detail.shotOutline || detail.storyboard || detail['分镜大纲']) || '',
            detailedScript:cleanText(detail.detailedScript || detail.scriptDetail || detail['详细脚本分镜']) || '',
            flowFrameBrief:cleanText(detail.flowFrameBrief || detail.promptBrief || detail['流帧心法输入']) || '',
            assetUsage:normalizeMap(detail.assetUsage || detail.imageUsage || segment.assetUsage),
            warnings:cleanList(detail.warnings || detail['警告']),
            raw:cleanText(raw),
            parseError:false
        };
    }

    function normalizeSectionSegmentResult(raw, options={}){
        const section = options.section || {};
        const bounds = options.bounds || normalizeBounds(options.node || {});
        const warnings = [];
        let parsed = null;
        try {
            parsed = parseJsonBlock(raw);
        } catch(err) {
            warnings.push(`小段 JSON 解析失败，已使用本地兜底拆分：${err.message}`);
            const segments = fallbackSegments(section.originalText || '', bounds).map((segment, index) => ({
                ...segment,
                id:`${section.id || 'P'}-S${String(index + 1).padStart(2, '0')}`,
                title:segment.title || `${section.title || '剧情段落'} 小段 ${index + 1}`,
                shotOutline:segment.notes || '',
                detailedScript:segment.originalText || '',
                flowFrameBrief:segment.originalText || '',
                warnings:[]
            }));
            return {segments, warnings, raw:cleanText(raw), parseError:true};
        }
        const items = Array.isArray(parsed.segments) ? parsed.segments : Array.isArray(parsed['小段']) ? parsed['小段'] : [];
        let segments = items.map((item, index) => {
            const base = normalizeSegment(item, index, bounds, section.originalText || '');
            const rawItem = normalizeMap(item);
            return {
                ...base,
                id:cleanText(base.id) || `${section.id || 'P'}-S${String(index + 1).padStart(2, '0')}`,
                title:base.title || `${section.title || '剧情段落'} 小段 ${index + 1}`,
                shotOutline:cleanText(rawItem.shotOutline || rawItem.storyboard || rawItem['分镜大纲']) || '',
                detailedScript:cleanText(rawItem.detailedScript || rawItem.scriptDetail || rawItem['详细脚本分镜']) || '',
                flowFrameBrief:cleanText(rawItem.flowFrameBrief || rawItem.promptBrief || rawItem['流帧心法输入']) || '',
                warnings:cleanList(rawItem.warnings || rawItem['警告'])
            };
        }).filter(segment => segment.originalText);
        if(!segments.length){
            warnings.push('LLM 未返回有效 10-15s 小段，已使用本地兜底拆分。');
            segments = fallbackSegments(section.originalText || '', bounds).map((segment, index) => ({
                ...segment,
                id:`${section.id || 'P'}-S${String(index + 1).padStart(2, '0')}`,
                title:segment.title || `${section.title || '剧情段落'} 小段 ${index + 1}`,
                shotOutline:segment.notes || '',
                detailedScript:segment.originalText || '',
                flowFrameBrief:segment.originalText || '',
                warnings:[]
            }));
        }
        return {
            segments,
            warnings:[...warnings, ...cleanList(parsed.warnings || parsed['警告'])],
            raw:cleanText(raw),
            parseError:false
        };
    }


    function assetLines(assets){
        const list = assets || [];
        if(!list.length) return '- 无参考素材';
        return list.map(asset => `- ${asset.tag || asset.id}：${asset.role || asset.name || ''}；文件：${asset.name || asset.sourceLabel || ''}${asset.included === false ? '（超出上限，未参与正式生成）' : ''}`).join('\n');
    }

    function promptSourceLines(sources){
        const prompts = (sources || []).filter(src => src?.prompt && !(src.refs || []).length).map(src => cleanText(src.prompt)).filter(Boolean);
        return prompts.length ? prompts.map((text, index) => `【上游文本 ${index + 1}】\n${text}`).join('\n\n') : '无';
    }

    function formatBible(bible){
        const normalized = normalizeContinuityBible(bible);
        return [
            normalized.summary ? `摘要：${normalized.summary}` : '',
            normalized.characters.length ? `角色：${normalized.characters.join('；')}` : '',
            normalized.wardrobe.length ? `服装：${normalized.wardrobe.join('；')}` : '',
            normalized.props.length ? `道具：${normalized.props.join('；')}` : '',
            normalized.spaces.length ? `空间：${normalized.spaces.join('；')}` : '',
            normalized.timeline.length ? `时间线：${normalized.timeline.join('；')}` : '',
            normalized.visualRules.length ? `视觉规则：${normalized.visualRules.join('；')}` : ''
        ].filter(Boolean).join('\n') || '暂无全局连续性总表。';
    }

    function buildGlobalAnalysisPrompt(options={}){
        const node = options.node || {};
        const scriptText = cleanText(options.scriptText);
        const assets = options.assets || [];
        return [
            '任务：你是长剧本到 Seedance / 即梦分段工作流的总规划师。',
            '请先阅读完整长剧本和参考素材，建立后续所有 10-15 秒分段共用的连续性总表。',
            '必须保留原文台词、标点和顺序；不要改写剧情，不要删除关键信息。',
            '重点分析：角色身份、服装、道具、姿态起点、空间布局、左右/前后关系、时间线、情绪线、光线气氛、参考图用途。',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"continuityBible":{"summary":"","characters":[""],"wardrobe":[""],"props":[""],"spaces":[""],"timeline":[""],"visualRules":[""]},"warnings":[""]}',
            '',
            `目标分段时长：${numberValue(node.segmentMinSeconds, DEFAULTS.segmentMinSeconds, 4, 15)}-${numberValue(node.segmentMaxSeconds, DEFAULTS.segmentMaxSeconds, 4, 20)} 秒`,
            '',
            '参考素材映射：',
            assetLines(assets),
            '',
            '上游文本：',
            promptSourceLines(options.sources || []),
            '',
            '完整长剧本：',
            scriptText || '未填写'
        ].join('\n');
    }

    function buildSectionPlanPrompt(options={}){
        const node = options.node || {};
        const scriptText = cleanText(options.scriptText);
        const assets = options.assets || [];
        return [
            '任务：把完整长剧本拆成几个“自然剧情段落”。',
            '注意：这里不是拆成 10-15 秒视频小段，而是先拆成可人工检查和修改的剧情段落，用于控制后续流程。',
            '按剧情转折、场景变化、人物目标变化、情绪阶段、动作阶段拆分；不要机械平均，不要改写原文，不要删减台词。',
            '每个剧情段落必须保留原文摘录、入场状态、出场状态、上下段衔接和参考图用途。',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"continuityBible":{"summary":"","characters":[""],"wardrobe":[""],"props":[""],"spaces":[""],"timeline":[""],"visualRules":[""]},"sections":[{"id":"P01","title":"","originalText":"","entryState":"","exitState":"","transitionIn":"","transitionOut":"","assetUsage":{"@image1":""},"notes":""}],"warnings":[""]}',
            '',
            '全局连续性总表：',
            formatBible(options.continuityBible),
            '',
            '参考素材映射：',
            assetLines(assets),
            '',
            '完整长剧本：',
            scriptText || '未填写'
        ].join('\n');
    }

    function buildSegmentPlanPrompt(options={}){
        const node = options.node || {};
        const scriptText = cleanText(options.scriptText);
        const assets = options.assets || [];
        const {min, max} = normalizeBounds(node);
        return [
            '任务：把完整长剧本拆分为多个适合 Seedance / 即梦生成的连续小段。',
            `每段目标 ${min}-${max} 秒；按剧情自然断点拆分，不要机械平均，不要固定模板。最后一段如果剧情自然结束可以略短。`,
            '必须覆盖完整原文，必须保留台词原文、标点和顺序，不要改写台词。',
            '每段必须能单独交给流帧心法生成电影镜头提示词，同时又能与上下段无缝衔接。',
            '拆分时必须记录：入场状态、出场状态、上一段衔接、下一段衔接、参考图用途。',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"continuityBible":{"summary":"","characters":[""],"wardrobe":[""],"props":[""],"spaces":[""],"timeline":[""],"visualRules":[""]},"segments":[{"id":"S01","title":"","originalText":"","targetDuration":12,"entryState":"","exitState":"","transitionIn":"","transitionOut":"","assetUsage":{"@image1":""},"notes":""}],"warnings":[""]}',
            '',
            '全局连续性总表：',
            formatBible(options.continuityBible),
            '',
            '参考素材映射：',
            assetLines(assets),
            '',
            '完整长剧本：',
            scriptText || '未填写'
        ].join('\n');
    }

    function buildSectionSegmentPlanPrompt(options={}){
        const node = options.node || {};
        const section = options.section || {};
        const assets = options.assets || [];
        const {min, max} = normalizeBounds(node);
        return [
            '任务：把一个已确认的剧情段落拆成多个可生成视频的 10-15 秒小段，并直接细化到分镜分析级别。',
            `每个小段目标 ${min}-${max} 秒；按剧情节奏自然拆分，不要机械平均。最后一段如果剧情自然结束可以略短。`,
            '必须保留原文台词、标点和顺序；不要改写台词，不要把上下文衔接写丢。',
            '每个小段必须能继续交给流帧心法生成电影镜头提示词，同时要承接上一小段和下一小段。',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"segments":[{"id":"S01","title":"","originalText":"","targetDuration":12,"entryState":"","exitState":"","transitionIn":"","transitionOut":"","shotOutline":"","detailedScript":"","flowFrameBrief":"","assetUsage":{"@image1":""},"warnings":[""]}],"warnings":[""]}',
            '',
            '全局连续性总表：',
            formatBible(options.continuityBible),
            '',
            '参考素材映射：',
            assetLines(assets),
            '',
            '上一段结尾状态：',
            cleanText(options.previousExitState) || section.transitionIn || '这是第一段或暂无上一段。',
            '',
            '下一段衔接意图：',
            cleanText(options.nextEntryState) || '这是最后一段或暂无下一段。',
            '',
            '当前剧情段落：',
            `ID：${section.id || ''}`,
            `标题：${section.title || ''}`,
            `入场状态：${section.entryState || ''}`,
            `出场状态：${section.exitState || ''}`,
            `入场衔接：${section.transitionIn || ''}`,
            `出场衔接：${section.transitionOut || ''}`,
            '原文：',
            section.originalText || ''
        ].join('\n');
    }

    function buildSegmentDetailPrompt(options={}){
        const segment = options.segment || {};
        const previous = options.previousDetail || {};
        const next = options.nextSegment || {};
        return [
            '任务：把一个长剧本分段细化为可交给流帧心法的详细脚本分镜。',
            '你必须结合完整连续性总表、上一段结尾、当前段原文、下一段意图，保证人物姿态、走位、空间方向、道具、情绪和光线连续。',
            '不要生成最终 Seedance 提示词；这里只做“分段脚本/分镜分析”，后续会交给流帧心法 agent。',
            '不要把镜头时间机械平均；本段内部的镜头节奏由动作、对白、情绪停顿和空间建立决定。',
            '必须保留当前段所有中文台词原文、标点和顺序。',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"segmentId":"","title":"","originalText":"","targetDuration":12,"entryState":"","exitState":"","transitionIn":"","transitionOut":"","shotOutline":"","detailedScript":"","flowFrameBrief":"","assetUsage":{"@image1":""},"warnings":[""]}',
            '',
            '全局连续性总表：',
            formatBible(options.continuityBible),
            '',
            '参考素材映射：',
            assetLines(options.assets || []),
            '',
            '上一段结尾状态：',
            cleanText(previous.exitState || previous.transitionOut || previous.detailedScript) || segment.transitionIn || '这是第一段或暂无上一段。',
            '',
            '当前段：',
            `ID：${segment.id || ''}`,
            `标题：${segment.title || ''}`,
            `目标时长：${segment.targetDuration || ''} 秒`,
            `入场状态：${segment.entryState || ''}`,
            `出场状态：${segment.exitState || ''}`,
            `入场衔接：${segment.transitionIn || ''}`,
            `出场衔接：${segment.transitionOut || ''}`,
            '原文：',
            segment.originalText || '',
            '',
            '下一段衔接意图：',
            next ? [
                `标题：${next.title || ''}`,
                `入场状态：${next.entryState || ''}`,
                `原文开头：${cleanText(next.originalText || '').slice(0, 220)}`
            ].join('\n') : '这是最后一段。',
            '',
            '请让 flowFrameBrief 成为可直接填入流帧心法“创作需求”的文本，必须包含：当前段原文、入场/出场状态、上下段衔接、人物走位、空间关系、参考图用途。'
        ].join('\n');
    }

    function formatSegmentPrompt(options={}){
        const segment = options.segment || {};
        const detail = options.detail || {};
        return [
            `【长剧本分段 ${segment.id || detail.segmentId || ''}】${segment.title || detail.title || ''}`,
            '',
            `目标时长：${detail.targetDuration || segment.targetDuration || ''} 秒`,
            '',
            '原文摘录：',
            detail.originalText || segment.originalText || '',
            '',
            '上下文衔接：',
            `入场状态：${detail.entryState || segment.entryState || ''}`,
            `出场状态：${detail.exitState || segment.exitState || ''}`,
            `入场衔接：${detail.transitionIn || segment.transitionIn || ''}`,
            `出场衔接：${detail.transitionOut || segment.transitionOut || ''}`,
            '',
            '详细脚本分镜：',
            detail.detailedScript || detail.shotOutline || segment.notes || '',
            '',
            '流帧心法输入重点：',
            detail.flowFrameBrief || detail.detailedScript || segment.originalText || '',
            '',
            '参考图用途：',
            Object.entries(detail.assetUsage || segment.assetUsage || {}).map(([key, value]) => `- ${key}：${value}`).join('\n') || '- 按长剧本拆分节点中的素材映射执行。'
        ].join('\n');
    }

    function formatSectionPrompt(options={}){
        const section = options.section || {};
        return [
            `【剧情段落 ${section.id || ''}】${section.title || ''}`,
            '',
            '原文摘录：',
            section.originalText || '',
            '',
            '上下文衔接：',
            `入场状态：${section.entryState || ''}`,
            `出场状态：${section.exitState || ''}`,
            `入场衔接：${section.transitionIn || ''}`,
            `出场衔接：${section.transitionOut || ''}`,
            '',
            '参考图用途：',
            Object.entries(section.assetUsage || {}).map(([key, value]) => `- ${key}：${value}`).join('\n') || '- 按长剧本拆分节点中的素材映射执行。',
            '',
            section.notes ? `说明：\n${section.notes}` : ''
        ].filter(Boolean).join('\n');
    }

    global.CanvasScriptPlanner = Object.freeze({
        DEFAULTS,
        normalizeBounds,
        normalizeGlobalAnalysis,
        normalizePlanResult,
        normalizeSectionPlanResult,
        normalizeSectionSegmentResult,
        normalizeSegmentDetail,
        buildGlobalAnalysisPrompt,
        buildSectionPlanPrompt,
        buildSegmentPlanPrompt,
        buildSectionSegmentPlanPrompt,
        buildSegmentDetailPrompt,
        formatSectionPrompt,
        formatSegmentPrompt,
        formatBible,
        assetLines,
        fallbackSections,
        fallbackSegments
    });
})(window);
