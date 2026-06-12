/*
 * Flow frame prompt helper.
 *
 * Pure helpers for turning connected canvas sources into Seedance/Dreamina
 * cinematic shot prompts with stable multi-image mapping.
 */
(function initCanvasFlowFrame(global){
    'use strict';

    const DEFAULT_STYLE = '罗杰·迪金斯 / Roger Deakins 风格：自然主义电影摄影，动机光源，低调光，克制运镜，清晰空间层次，真实胶片质感。';
    const DEFAULT_NEGATIVE = '无水印，无 logo，无字幕，无屏幕文字，无低清晰度，无塑料皮肤，无蜡像感，无面部变形，无肢体畸形，无闪烁，无过曝或欠曝。';
    const IMAGE_LIMIT = 9;

    const DEFAULTS = Object.freeze({
        mode:'auto',
        aspectRatio:'16:9',
        duration:10,
        fps:24,
        styleText:DEFAULT_STYLE,
        negativeText:DEFAULT_NEGATIVE,
        cinemaProfile:'deakins',
        shotPacing:'auto',
        promptLanguage:'zh',
        useAiPlanning:true,
        reviewStrictness:'strict',
        imageLimit:IMAGE_LIMIT
    });

    const MODE_LABELS = Object.freeze({
        text:'纯文本',
        firstLast:'首尾帧',
        allReference:'全素材参考'
    });

    function cleanText(value){
        return String(value ?? '').trim();
    }

    function numberValue(value, fallback, min, max){
        const num = Number(value);
        if(!Number.isFinite(num)) return fallback;
        return Math.max(min, Math.min(max, num));
    }

    function isVideoUrl(url){
        return /\.(mp4|webm|mov|m4v|avi|mkv)$/i.test(String(url || '').split('?')[0]);
    }

    function isAudioUrl(url){
        return /\.(mp3|wav|ogg|m4a|flac|aac|wma|opus|aiff|aif|amr)$/i.test(String(url || '').split('?')[0]);
    }

    function refKind(ref, source){
        const role = cleanText(ref?.role || source?.role).toLowerCase();
        const url = ref?.url || source?.preview || '';
        if(role === 'video' || isVideoUrl(url)) return 'video';
        if(role === 'audio' || isAudioUrl(url)) return 'audio';
        return 'image';
    }

    function fallbackAssetRole(kind, index, mode){
        if(kind === 'video') return index === 1 ? '运动、镜头语言和转场节奏参考' : '视频参考';
        if(kind === 'audio') return index === 1 ? '节奏、情绪和氛围参考' : '音频参考';
        if(mode === 'firstLast' && index === 1) return '首帧、主体外观和身份锚点';
        if(mode === 'firstLast' && index === 2) return '尾帧、结束构图或场景空间';
        if(index === 1) return '主角外观、身份锚点和首帧参考';
        if(index === 2) return '场景空间、环境气氛和构图参考';
        if(index === 3) return '服装、道具、材质或角色细节参考';
        if(index === 4) return '光影、色彩和画面质感参考';
        return '补充角色、场景、道具或风格参考';
    }

    function stableAssetId(source, ref, refIndex, kind, sequence){
        const base = source?.assetId || source?.imageId || source?.id || `${kind}:${sequence}`;
        const hasManyRefs = (source?.refs || []).length > 1;
        if(hasManyRefs) return `${base}:${ref?.url || refIndex}`;
        return String(base);
    }

    function collectAssets(sources, assetRoles, modeHint='auto', imageLimit=IMAGE_LIMIT){
        const counts = {image:0, video:0, audio:0};
        const assets = [];
        (sources || []).forEach(source => {
            (source?.refs || []).forEach((ref, refIndex) => {
                if(!ref?.url) return;
                const kind = refKind(ref, source);
                counts[kind] = (counts[kind] || 0) + 1;
                const sourceId = source.id || `${kind}:${assets.length}`;
                const assetId = stableAssetId(source, ref, refIndex, kind, counts[kind]);
                const included = kind !== 'image' || counts[kind] <= imageLimit;
                const role = cleanText(assetRoles?.[assetId])
                    || cleanText(assetRoles?.[sourceId])
                    || cleanText(ref.role)
                    || cleanText(source.role)
                    || fallbackAssetRole(kind, counts[kind], modeHint);
                assets.push({
                    id:assetId,
                    sourceId,
                    sourceLabel:source.label || ref.name || `${kind} ${counts[kind]}`,
                    kind,
                    index:counts[kind],
                    tag:`@${kind}${counts[kind]}`,
                    url:ref.url,
                    name:ref.name || source.label || `${kind}${counts[kind]}`,
                    role,
                    included,
                    omittedReason:included ? '' : `超过 Seedance 图片上限 ${imageLimit} 张`
                });
            });
        });
        return assets;
    }

    function inferMode(assets){
        const included = (assets || []).filter(asset => asset.included !== false);
        if(!included.length) return 'text';
        const imageCount = included.filter(asset => asset.kind === 'image').length;
        const hasMediaBeyondImages = included.some(asset => asset.kind === 'video' || asset.kind === 'audio');
        if(!hasMediaBeyondImages && imageCount === 1) return 'firstLast';
        return 'allReference';
    }

    function normalizedMode(mode, assets){
        if(['text','firstLast','allReference'].includes(mode)) return mode;
        return inferMode(assets);
    }

    function promptSources(sources){
        return (sources || [])
            .filter(source => source?.prompt && !(source.refs || []).length)
            .map(source => cleanText(source.prompt))
            .filter(Boolean);
    }

    function hasActualTimecode(text){
        return /(?:\d+\s*[-–—~到]\s*\d+\s*秒|\d{1,2}:\d{2}(?:\.\d)?\s*[-–—~到]\s*\d{1,2}:\d{2}(?:\.\d)?)/.test(String(text || ''));
    }

    function hasShotStructure(text){
        return /(?:第\s*\d+\s*[段幕镜]|镜头\s*\d+|^\s*\d+[\.、])/m.test(String(text || ''));
    }

    function splitNarrativeLine(line){
        const text = cleanText(line).replace(/^\s*[-*•]\s*/, '');
        if(!text) return [];
        if(/^(negative|负面约束|生成设置|素材映射|模式|正式提示词|摄影风格|镜头策略|画面比例|帧率|时长)[:：]/i.test(text)) return [];
        const arrowParts = text.split(/\s*(?:→|->|=>)\s*/).map(cleanText).filter(Boolean);
        if(arrowParts.length > 1) return arrowParts;
        if(/[「“"].*[」”"]/.test(text)) return [text];
        const sentenceParts = text.match(/[^。！？!?；;]+[。！？!?；;]?/g);
        if(sentenceParts && sentenceParts.length > 1) return sentenceParts.map(cleanText).filter(Boolean);
        return [text];
    }

    function narrativeUnits(text){
        return String(text || '')
            .split(/\n+/)
            .flatMap(splitNarrativeLine)
            .filter(Boolean);
    }

    function mergeUnits(units, maxCount){
        if(units.length <= maxCount) return units;
        const merged = [];
        for(let i = 0; i < maxCount; i += 1){
            const start = Math.floor(i * units.length / maxCount);
            const end = Math.floor((i + 1) * units.length / maxCount);
            merged.push(units.slice(start, Math.max(start + 1, end)).join(' / '));
        }
        return merged;
    }

    function formatClock(seconds){
        const value = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(value / 60);
        const rest = value - minutes * 60;
        return `${String(minutes).padStart(2, '0')}:${rest.toFixed(1).padStart(4, '0')}`;
    }

    function parseClock(value){
        const match = String(value || '').match(/^(\d{1,2}):(\d{2})(?:\.(\d))?$/);
        if(!match) return NaN;
        return Number(match[1]) * 60 + Number(match[2]) + Number(match[3] || 0) / 10;
    }

    function shortBeat(text){
        const flat = cleanText(text).replace(/\s+/g, ' ');
        return flat.length > 120 ? `${flat.slice(0, 118)}…` : flat;
    }

    function classifyStory(userText, shotPacing='auto'){
        const text = cleanText(userText);
        if(/一镜到底|长镜头|不中断|无剪辑|连续镜头/.test(text) || shotPacing === 'oneTake'){
            return {
                type:'一镜到底',
                minShotSeconds:8,
                maxShots:1,
                guidance:'使用单一连续镜头完成空间推进，强调调度、景深层次和动机光源变化。'
            };
        }
        if(/打斗|搏斗|追逐|奔跑|冲刺|爆炸|躲避|攻击|战斗|动作戏|快速|枪|剑|跳|摔|翻/.test(text) || shotPacing === 'action'){
            return {
                type:'动作 / 追逐 / 打斗',
                minShotSeconds:1.4,
                maxShots:8,
                guidance:'允许较快切镜头，但每个镜头仍必须有清晰景别、单一主运镜和可读动作。'
            };
        }
        if(/[「“"].+[」”"]/.test(text) || /对白|对话|说：|他说|她说|问道|回答|沉默|眼神|情绪|表情/.test(text) || shotPacing === 'dialogue'){
            return {
                type:'对话 / 情绪戏',
                minShotSeconds:3,
                maxShots:4,
                guidance:'以中近景、过肩、特写和克制推镜为主，让情绪和表演承载节奏。'
            };
        }
        if(/氛围|场景|环境|废墟|森林|山谷|黄昏|清晨|雨|雾|光影|静|凝视|眺望/.test(text) || shotPacing === 'atmosphere'){
            return {
                type:'氛围 / 空间建立',
                minShotSeconds:4,
                maxShots:3,
                guidance:'以较长镜头建立空间、光线和人物位置，运镜保持克制。'
            };
        }
        return {
            type:'叙事 / 混合节奏',
            minShotSeconds:2.4,
            maxShots:5,
            guidance:'根据剧情转折安排镜头长短，避免平均分配时长。'
        };
    }

    function beatWeight(beat, index, strategy){
        const text = cleanText(beat);
        const base = Math.max(0.85, Math.min(2.4, text.length / 42));
        const patternMap = {
            '动作 / 追逐 / 打斗':[0.55, 1.45, 0.72, 1.7, 0.82, 1.22, 0.62, 1.38],
            '对话 / 情绪戏':[1.75, 1.05, 1.9, 0.82, 1.35],
            '氛围 / 空间建立':[1.85, 0.92, 1.42],
            '叙事 / 混合节奏':[1.55, 0.82, 1.7, 0.72, 1.24]
        };
        const pattern = patternMap[strategy.type] || patternMap['叙事 / 混合节奏'];
        const dialogueBoost = /[「“"].+[」”"]/.test(text) ? 1.18 : 1;
        return base * pattern[index % pattern.length] * dialogueBoost;
    }

    function shotLineWeight(line, index, strategy){
        const text = cleanText(line).replace(/\d{1,2}:\d{2}(?:\.\d)?\s*[-–—~到]\s*\d{1,2}:\d{2}(?:\.\d)?/g, '');
        let weight = beatWeight(text || line, index, strategy);
        if(/[「“"].+[」”"]|对白|回答|问|说/.test(text)) weight *= 1.22;
        if(/特写|凝视|停顿|沉默|表情|眼神|反应/.test(text)) weight *= 1.16;
        if(/远景|建立|空间|环境|废墟|森林|山谷|河沟/.test(text)) weight *= 1.12;
        if(/冲|跳|闪|躲|击|砍|跑|追|摔|爆|快速/.test(text)) weight *= strategy.type === '动作 / 追逐 / 打斗' ? 0.82 : 0.95;
        if(/收束|结束|落点|定格|停在|望向/.test(text)) weight *= 1.08;
        return Math.max(0.35, weight);
    }

    function timeRanges(beats, total, strategy){
        if(!beats.length) return [];
        if(beats.length === 1) return [{start:0, end:total, beat:beats[0]}];
        const weights = beats.map((beat, index) => beatWeight(beat, index, strategy));
        const weightTotal = weights.reduce((sum, value) => sum + value, 0) || beats.length;
        let cursor = 0;
        return beats.map((beat, index) => {
            const start = cursor;
            const rawDuration = total * weights[index] / weightTotal;
            const end = index === beats.length - 1 ? total : Math.max(start + 0.8, Math.min(total, start + rawDuration));
            cursor = end;
            return {start, end, beat};
        });
    }

    function distributeDurations(items, total, strategy){
        const count = items.length;
        if(!count) return [];
        if(count === 1) return [total];
        const minShot = Math.min(Math.max(0.55, Number(strategy.minShotSeconds || 1.2) * 0.42), total / count * 0.52);
        const weights = items.map((item, index) => shotLineWeight(item, index, strategy));
        const weightTotal = weights.reduce((sum, value) => sum + value, 0) || count;
        const remaining = Math.max(0, total - minShot * count);
        const raw = weights.map(weight => minShot + remaining * weight / weightTotal);
        const avg = total / count;
        const contrast = strategy.type === '动作 / 追逐 / 打斗' ? 1.75 : 1.62;
        const floor = Math.min(Math.max(0.55, total / count * 0.34), total / count * 0.6);
        const contrasted = raw.map(duration => Math.max(floor, avg + (duration - avg) * contrast));
        const contrastedTotal = contrasted.reduce((sum, value) => sum + value, 0) || total;
        return contrasted.map(duration => duration * total / contrastedTotal);
    }

    function promptTimeRanges(prompt){
        const text = String(prompt || '');
        const rangePattern = /(\d{1,2}:\d{2}(?:\.\d)?)\s*[-–—~到]\s*(\d{1,2}:\d{2}(?:\.\d)?)/g;
        const ranges = [];
        let match;
        while((match = rangePattern.exec(text))){
            const start = parseClock(match[1]);
            const end = parseClock(match[2]);
            if(!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
            const lineStart = text.lastIndexOf('\n', match.index) + 1;
            const lineEndIndex = text.indexOf('\n', match.index);
            const lineEnd = lineEndIndex === -1 ? text.length : lineEndIndex;
            ranges.push({
                raw:match[0],
                start,
                end,
                duration:end - start,
                line:text.slice(lineStart, lineEnd)
            });
        }
        return ranges;
    }

    function uniformTimingIssue(prompt, totalDuration){
        const ranges = promptTimeRanges(prompt);
        if(ranges.length < 3) return {uniform:false, ranges};
        const total = Number(totalDuration) || ranges[ranges.length - 1].end;
        const durations = ranges.map(range => range.duration);
        const avg = durations.reduce((sum, value) => sum + value, 0) / durations.length;
        const variance = durations.reduce((sum, value) => sum + Math.pow(value - avg, 2), 0) / durations.length;
        const std = Math.sqrt(variance);
        const maxDiff = Math.max(...durations) - Math.min(...durations);
        const looksLikeEqualGrid = ranges.every((range, index) => Math.abs(range.start - (index * total / ranges.length)) <= 0.45)
            && ranges.every((range, index) => Math.abs(range.end - ((index + 1) * total / ranges.length)) <= 0.45);
        const tooEven = avg > 0 && std / avg < 0.18 && maxDiff < Math.max(1.05, avg * 0.38);
        return {uniform:looksLikeEqualGrid || tooEven, ranges};
    }

    function repairUniformTimecodes(prompt, options={}){
        const text = String(prompt || '');
        const total = numberValue(options.duration, DEFAULTS.duration, 4, 15);
        const userText = cleanText(options.userText);
        if(hasActualTimecode(userText)) return {prompt:text, changed:false, reason:'user-timecodes'};
        const issue = uniformTimingIssue(text, total);
        if(!issue.uniform || issue.ranges.length < 3) return {prompt:text, changed:false, reason:''};
        const strategy = classifyStory(`${userText}\n${text}`, options.shotPacing || DEFAULTS.shotPacing);
        const durations = distributeDurations(issue.ranges.map(range => range.line), total, strategy);
        let cursor = 0;
        const replacements = durations.map((duration, index) => {
            const start = cursor;
            const end = index === durations.length - 1 ? total : Math.min(total, cursor + duration);
            cursor = end;
            return `${formatClock(start)}-${formatClock(end)}`;
        });
        let replacementIndex = 0;
        const repaired = text.replace(/(\d{1,2}:\d{2}(?:\.\d)?)\s*[-–—~到]\s*(\d{1,2}:\d{2}(?:\.\d)?)/g, () => {
            const next = replacements[replacementIndex];
            replacementIndex += 1;
            return next || replacements[replacements.length - 1] || '';
        });
        return {prompt:repaired, changed:repaired !== text, reason:'uniform-timecodes'};
    }

    function shotLanguage(strategy, index){
        if(strategy.type === '一镜到底') return '连续长镜头，前景遮挡与景深层次推动空间，镜头缓慢跟随或横移。';
        if(strategy.type === '动作 / 追逐 / 打斗'){
            const options = ['中景跟拍，保持动作方向清晰', '低机位侧向跟拍，强调速度和重心变化', '特写切入关键动作，随后快速回到中景', '远景交代空间关系，短暂推近到冲突中心'];
            return options[index % options.length];
        }
        if(strategy.type === '对话 / 情绪戏'){
            const options = ['中近景静观，轻微推镜捕捉表情变化', '过肩镜头建立人物关系，背景保持浅景深', '面部特写，眼神和停顿成为节奏核心', '双人中景，保留空间压迫感和沉默'];
            return options[index % options.length];
        }
        if(strategy.type === '氛围 / 空间建立'){
            const options = ['远景缓慢推近，先建立地形和光线方向', '固定机位中景，主体在环境中产生细微动作', '低角度或侧逆光构图，突出剪影和空间深度'];
            return options[index % options.length];
        }
        const options = ['远景建立空间后缓慢推近', '中景跟随主体动作，保持运动连贯', '特写捕捉关键道具、表情或手部动作', '拉远或固定机位形成收束'];
        return options[index % options.length];
    }

    function targetShotCount(units, total, strategy){
        if(strategy.type === '一镜到底') return 1;
        const byDuration = Math.max(1, Math.floor(total / Math.max(1, strategy.minShotSeconds)));
        const byUnits = Math.max(1, units.length || 1);
        return Math.max(1, Math.min(strategy.maxShots, byDuration, byUnits));
    }

    function timingPlan(userText, duration, strategy){
        const total = numberValue(duration, DEFAULTS.duration, 4, 15);
        if(hasActualTimecode(userText)){
            return [
                '时间码编排：',
                '- 保留用户原有时间码作为主线；在每个时间段内补强景别、主运镜、主体动作、动机光源和空间关系，不重新平均分配。'
            ].join('\n');
        }
        const units = narrativeUnits(userText);
        const seedUnits = units.length ? units : ['根据创作需求自然安排镜头节奏，建立主体、空间关系、动作变化和收束画面。'];
        const count = hasShotStructure(userText)
            ? Math.min(seedUnits.length, Math.max(1, Math.floor(total / Math.max(1, strategy.minShotSeconds))))
            : targetShotCount(seedUnits, total, strategy);
        const beats = mergeUnits(seedUnits, count);
        const lines = timeRanges(beats, total, strategy).map((range, index) => {
            return `- ${formatClock(range.start)}-${formatClock(range.end)}｜镜头${index + 1}：${shortBeat(range.beat)}。镜头语言：${shotLanguage(strategy, index)}`;
        });
        return [
            '时间码编排：',
            ...lines,
            '说明：时间码按剧情节奏分配，不做机械等分；如用户已有镜头要求，以用户要求为准。'
        ].join('\n');
    }

    function modeGuidance(mode, assets){
        if(mode === 'text') return '无参考素材时，完整描述原创主体、场景、镜头、动作节奏和视觉风格。';
        if(mode === 'firstLast'){
            const hasSecondImage = assets.filter(asset => asset.kind === 'image').length >= 2;
            return hasSecondImage
                ? '使用 @image1 作为首帧和身份锚点，以 @image2 的构图作为结束画面；镜头变化必须保持主体身份、空间方向和光线连续。'
                : '使用 @image1 作为首帧和身份锚点，后续动作必须保持外观、光照和空间方向连续。';
        }
        return '按素材映射使用所有参考：每张图片必须用对应 @imageN 精确指代，视频继承运动和镜头语言，音频继承节奏和情绪。';
    }

    function buildMapping(assets, omittedAssets=[]){
        const lines = assets.length ? assets.map(asset => `- ${asset.tag}：${asset.role || asset.name}`) : ['- 无'];
        const omittedImages = omittedAssets.filter(asset => asset.kind === 'image');
        if(omittedImages.length){
            lines.push(`- 未参与：${omittedImages.map(asset => asset.tag).join('、')}（超过 Seedance 图片上限 ${IMAGE_LIMIT} 张，本次不写入正式生成映射）`);
        }
        return lines.join('\n');
    }

    function buildAssetUseLine(assets, omittedAssets=[]){
        if(!assets.length) return '素材使用：无参考素材，按纯文本生成，提示词必须完整承载主体、场景、动作、镜头和风格。';
        const parts = assets.map(asset => `${asset.tag} 用于${asset.role || asset.name}`);
        const omitted = omittedAssets.length ? `；${omittedAssets.map(asset => asset.tag).join('、')} 超出上限，仅作为人工参考，不进入正式生成映射` : '';
        return `素材使用：${parts.join('；')}${omitted}。`;
    }

    function buildCinematography(styleText){
        const custom = cleanText(styleText) || DEFAULT_STYLE;
        return [
            custom,
            '摄影要求：自然主义动机光源，低调光与柔和高光控制，人物可形成清晰剪影；镜头运动克制，避免炫技式推拉摇移堆叠；构图强调前中后景层次、真实空气感和胶片质感。'
        ].join('\n');
    }

    function buildPrompt(options={}){
        const sourceNode = options.node || {};
        const sources = options.sources || [];
        const assetRoles = sourceNode.assetRoles || {};
        const imageLimit = numberValue(sourceNode.imageLimit, DEFAULTS.imageLimit, 1, DEFAULTS.imageLimit);
        const roughAssets = collectAssets(sources, assetRoles, sourceNode.mode || DEFAULTS.mode, imageLimit);
        const mode = normalizedMode(sourceNode.mode || DEFAULTS.mode, roughAssets);
        const allAssets = collectAssets(sources, assetRoles, mode, imageLimit);
        const assets = allAssets.filter(asset => asset.included !== false);
        const omittedAssets = allAssets.filter(asset => asset.included === false);
        const promptInputs = promptSources(sources);
        const aspectRatio = cleanText(sourceNode.aspectRatio) || DEFAULTS.aspectRatio;
        const duration = numberValue(sourceNode.duration, DEFAULTS.duration, 4, 15);
        const fps = numberValue(sourceNode.fps, DEFAULTS.fps, 1, 120);
        const style = cleanText(sourceNode.styleText) || DEFAULT_STYLE;
        const brief = cleanText(sourceNode.briefText);
        const negative = cleanText(sourceNode.negativeText) || DEFAULT_NEGATIVE;
        const userText = [brief, ...promptInputs].filter(Boolean).join('\n\n');
        const strategy = classifyStory(userText, sourceNode.shotPacing || DEFAULTS.shotPacing);
        const mainPrompt = [
            `${aspectRatio}，${duration}秒，${fps}fps，全中文电影镜头提示词。`,
            buildAssetUseLine(assets, omittedAssets),
            modeGuidance(mode, assets),
            userText ? `用户需求 / 上游文本：\n${userText}` : '用户需求 / 上游文本：\n请根据素材映射设计一个连续、稳定、可生成的视频镜头。',
            timingPlan(userText, duration, strategy),
            '对白规则：如包含台词，必须使用中文引号「」逐句保留原文、标点和顺序，不删减、不合并、不改写，并放入对应时间码镜头。',
            'Seedance 约束：每个镜头只指定一种主运镜，动作具体到身体部位、速度、幅度和承接关系；避免模糊诗意描述。'
        ].join('\n');
        const shotAnalysis = `${strategy.type}：${strategy.guidance}`;
        return {
            mode,
            modeLabel:MODE_LABELS[mode] || MODE_LABELS.allReference,
            assets,
            allAssets,
            omittedAssets,
            userText,
            shotAnalysis,
            prompt:`模式：${MODE_LABELS[mode] || MODE_LABELS.allReference}

素材映射：
${buildMapping(assets, omittedAssets)}

镜头策略：
${shotAnalysis}

正式提示词：
${mainPrompt}

摄影风格：
${buildCinematography(style)}

负面约束：
${negative}

生成设置：
时长：${duration}秒
画面比例：${aspectRatio}
帧率：${fps}fps`
        };
    }

    function buildLLMUserPrompt(options={}){
        const draft = options.draft || buildPrompt(options);
        const node = options.node || {};
        const polish = Boolean(options.polish);
        const assets = draft.allAssets || draft.assets || [];
        const settings = [
            `时长：${numberValue(node.duration, DEFAULTS.duration, 4, 15)}秒`,
            `画面比例：${cleanText(node.aspectRatio) || DEFAULTS.aspectRatio}`,
            `帧率：${numberValue(node.fps, DEFAULTS.fps, 1, 120)}fps`,
            `风格：${cleanText(node.styleText) || DEFAULT_STYLE}`,
            `负面约束：${cleanText(node.negativeText) || DEFAULT_NEGATIVE}`
        ].join('\n');
        const assetLines = assets.length
            ? assets.map(asset => `- ${asset.tag}${asset.included === false ? '（未参与正式映射）' : ''}：${asset.role || asset.name}；文件：${asset.name || asset.sourceLabel || asset.tag}`).join('\n')
            : '- 无';
        const draftReference = polish
            ? draft.prompt
            : [
                `模式初判：${draft.modeLabel || MODE_LABELS[draft.mode] || MODE_LABELS.allReference}`,
                `镜头策略初判：${draft.shotAnalysis || '根据剧本重新判断镜头节奏。'}`,
                '首次生成时必须重新规划镜头数量和时间码，不得复用本地兜底模板。'
            ].join('\n');
        return [
            `任务：${polish ? '在不改变素材编号和台词原文的前提下，二次强化已有电影镜头提示词。' : '先分析剧本节奏和多图素材用途，再生成电影镜头提示词。'}`,
            '输出语言：全中文，必要专有名词可保留英文。',
            '摄影风格：必须明确写“罗杰·迪金斯 / Roger Deakins”，并用自然主义动机光源、低调光、剪影、克制运镜、空间层次、胶片质感来具体化，不要只写“电影感”。',
            '时间码：必须输出严格时间码，格式为 00:00.0-00:04.5。镜头数量和时长由剧情决定，禁止机械平均分配。',
            '硬性禁止：不要输出 15 秒 5 镜时每镜约 3 秒、15 秒 4 镜时每镜约 3.75 秒、或任何接近等分的时间表。每个镜头时长必须因动作、对白、情绪停顿、空间建立而明显不同。',
            '内部节奏参考：文戏偏少而长，动作/追逐可更快切，空间氛围可更少更长，一镜到底只输出一个连续镜头。这个参考只用于分析，禁止照抄进最终输出。',
            '镜头策略必须是对当前剧本的单一判断和理由，不要输出“对话几镜、动作几镜、空间建立几镜”这种通用分类菜单。',
            '多图规则：每张图必须逐项映射为 @imageN。正式提示词引用图片时必须写对应 @imageN，禁止只写“参考图/素材图”。超过 9 张图片时，只使用前 9 张并说明其余未参与。',
            '镜头语言：每个镜头必须包含景别、机位/角度、主运镜、主体动作、光影、空间关系；每个镜头只指定一种主运镜。',
            '对白规则：所有中文台词必须完整保留原文、标点和顺序，并放入对应时间码镜头。',
            '',
            '节点设置：',
            settings,
            '',
            '素材映射候选：',
            assetLines,
            '',
            '剧本 / 用户需求：',
            draft.userText || cleanText(node.briefText) || '请根据素材设计一个电影镜头。',
            '',
            polish ? '已有提示词：' : '本地结构摘要（不含兜底时间码，仅供理解字段）：',
            draftReference,
            '',
            '最终输出必须包含这些一级标题：模式、素材映射、镜头策略、正式提示词、摄影风格、负面约束、生成设置。不要输出解释或 Markdown 代码块。'
        ].join('\n');
    }

    function assetAuditLines(draft){
        const assets = draft?.allAssets || draft?.assets || [];
        return assets.length
            ? assets.map(asset => `- ${asset.tag}${asset.included === false ? '（未参与正式映射）' : ''}：${asset.role || asset.name}；文件：${asset.name || asset.sourceLabel || asset.tag}`).join('\n')
            : '- 无';
    }

    function buildReviewPrompt(options={}){
        const draft = options.draft || buildPrompt(options);
        const node = options.node || {};
        const prompt = cleanText(options.prompt);
        const phase = cleanText(options.phase) || '初审';
        return [
            `任务：${phase}。你是流帧心法 Agent 的严格审核员，只审核并指出可执行修复意见，不重新生成全文。`,
            '请结合剧本、素材映射、Seedance 2.0 提示词指南和流帧心法连续性要求审核。',
            '必须重点检查：',
            '1. 剧情因果：前一镜头站立，后一镜头不能无理由变成趴地起身；不能跳过必要动作承接。',
            '2. 人物连续：身份、服装、道具、姿态、动作起势/承接/落点、视线方向必须前后一致。',
            '3. 走位与空间：左右关系、前后距离、进出画方向、镜头轴线、人物与场景位置不能互相矛盾。',
            '4. 镜头逻辑：景别变化要有动机；每个镜头只保留一种主运镜；禁止乱切、重复模板和机械平均时间码。',
            '5. 素材映射：正式提示词必须准确引用 @image1/@image2/@video1/@audio1，不能写模糊的“参考图/素材图”。',
            '6. 台词/音效：中文台词必须保留原文、标点和顺序，并放入合理的镜头时间段。',
            '7. Seedance 约束：主体定义清楚、动作细到肢体部位、负面约束完整、避免固定 0-3/3-7/7-10 分段模板。',
            '8. 多图顺序：group 内和画布输入顺序已在素材映射中确定，审核时不得重新编号，只检查是否被正确使用。',
            '',
            '输出必须是严格 JSON，不要 Markdown，不要解释。字段固定为：',
            '{"pass":boolean,"blockingIssues":["..."],"warnings":["..."],"continuityMap":{"characters":["..."],"space":["..."],"props":["..."],"motion":["..."]},"fixInstructions":["..."]}',
            'pass 只有在没有阻塞问题时才为 true；blockingIssues 必须写具体镜头或时间码的问题；fixInstructions 必须可直接指导重写。',
            '',
            '节点设置：',
            `时长：${numberValue(node.duration, DEFAULTS.duration, 4, 15)}秒`,
            `比例：${cleanText(node.aspectRatio) || DEFAULTS.aspectRatio}`,
            `帧率：${numberValue(node.fps, DEFAULTS.fps, 1, 120)}fps`,
            `审核强度：${cleanText(node.reviewStrictness) || DEFAULTS.reviewStrictness}`,
            '',
            '素材映射候选：',
            assetAuditLines(draft),
            '',
            '剧本 / 用户需求：',
            draft.userText || cleanText(node.briefText) || '未填写',
            '',
            '待审核提示词：',
            prompt || draft.prompt || ''
        ].join('\n');
    }

    function buildRevisionPrompt(options={}){
        const draft = options.draft || buildPrompt(options);
        const node = options.node || {};
        const prompt = cleanText(options.prompt);
        const review = options.review || {};
        const blocking = (review.blockingIssues || []).join('\n- ');
        const warnings = (review.warnings || []).join('\n- ');
        const fixes = (review.fixInstructions || []).join('\n- ');
        return [
            '任务：根据严格审核意见，自动修复流帧心法电影镜头提示词。',
            '你必须保留素材编号、台词原文、画面比例、时长、帧率和最终结构；只修复逻辑冲突、走位冲突、空间关系冲突、时间节奏模板化和 Seedance 不友好表达。',
            '禁止新增审核报告，禁止解释过程，最终只输出修复后的完整提示词。',
            '修复重点：',
            '- 前后镜头姿态必须有动作承接，不能站立后突然趴地起身。',
            '- 人物走位、视线方向、左右关系、镜头轴线、道具位置必须连续。',
            '- 每个镜头只指定一种主运镜，时间码不得机械等分。',
            '- 多图引用必须准确使用 @imageN，不得改编号。',
            '- 台词必须保留原文、标点和顺序。',
            '',
            '审核阻塞问题：',
            blocking ? `- ${blocking}` : '- 无',
            '',
            '审核警告：',
            warnings ? `- ${warnings}` : '- 无',
            '',
            '修复指令：',
            fixes ? `- ${fixes}` : '- 根据审核结果提升连续性和可生成性。',
            '',
            '素材映射候选：',
            assetAuditLines(draft),
            '',
            '剧本 / 用户需求：',
            draft.userText || cleanText(node.briefText) || '未填写',
            '',
            '待修复提示词：',
            prompt || draft.prompt || '',
            '',
            '最终输出必须包含这些一级标题：模式、素材映射、镜头策略、正式提示词、摄影风格、负面约束、生成设置。不要输出解释或 Markdown 代码块。'
        ].join('\n');
    }

    function cleanReviewList(value){
        if(Array.isArray(value)) return value.map(item => cleanText(item)).filter(Boolean);
        const text = cleanText(value);
        return text ? [text] : [];
    }

    function parseReviewJson(raw){
        const text = cleanText(raw);
        if(!text) throw new Error('empty review');
        const unfenced = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
        try { return JSON.parse(unfenced); } catch(_err) {}
        const start = unfenced.indexOf('{');
        const end = unfenced.lastIndexOf('}');
        if(start >= 0 && end > start) return JSON.parse(unfenced.slice(start, end + 1));
        throw new Error('invalid review json');
    }

    function normalizeReviewResult(raw){
        const text = cleanText(raw);
        try {
            const parsed = parseReviewJson(text);
            const blockingIssues = cleanReviewList(parsed.blockingIssues);
            const warnings = cleanReviewList(parsed.warnings);
            const fixInstructions = cleanReviewList(parsed.fixInstructions);
            const continuityMap = parsed.continuityMap && typeof parsed.continuityMap === 'object' && !Array.isArray(parsed.continuityMap)
                ? parsed.continuityMap
                : {};
            return {
                pass:Boolean(parsed.pass) && !blockingIssues.length,
                blockingIssues,
                warnings,
                continuityMap,
                fixInstructions,
                raw:text,
                parseError:false
            };
        } catch(err) {
            return {
                pass:false,
                blockingIssues:['审核格式异常，无法可靠判断是否通过。'],
                warnings:[text || err.message || '审核模型未返回内容。'],
                continuityMap:{},
                fixInstructions:['按严格连续性清单重新检查并修复前后镜头动作、人物走位、空间关系和素材引用。'],
                raw:text,
                parseError:true
            };
        }
    }

    global.CanvasFlowFrame = Object.freeze({
        DEFAULTS,
        MODE_LABELS,
        buildPrompt,
        buildLLMUserPrompt,
        buildReviewPrompt,
        buildRevisionPrompt,
        normalizeReviewResult,
        promptTimeRanges,
        uniformTimingIssue,
        repairUniformTimecodes
    });
})(window);
