/*
 * Storyboard grid helper.
 *
 * Pure helpers for turning cinematic shot prompts into a multi-panel
 * storyboard image prompt plus a paired Seedance prompt.
 */
(function initCanvasStoryboardGrid(global){
    'use strict';

    const DEFAULTS = Object.freeze({
        layout:'auto',
        cellRatio:'16:9',
        resolution:'4k',
        quality:'high',
        maxShots:9
    });

    const LAYOUTS = Object.freeze({
        '1x1': {rows:1, cols:1, ratioLabel:'16:9', ratio:'wide', customRatio:'', fallbackRatio:'wide'},
        '1x2': {rows:1, cols:2, ratioLabel:'32:9', ratio:'custom', customRatio:'32:9', fallbackRatio:'4:1'},
        '1x3': {rows:1, cols:3, ratioLabel:'16:3', ratio:'custom', customRatio:'16:3', fallbackRatio:'4:1'},
        '2x2': {rows:2, cols:2, ratioLabel:'16:9', ratio:'wide', customRatio:'', fallbackRatio:'wide'},
        '2x3': {rows:2, cols:3, ratioLabel:'8:3', ratio:'custom', customRatio:'8:3', fallbackRatio:'21:9 / 2:1'},
        '3x3': {rows:3, cols:3, ratioLabel:'16:9', ratio:'wide', customRatio:'', fallbackRatio:'wide'}
    });

    function cleanText(value){
        return String(value ?? '').trim();
    }

    function clampNumber(value, fallback, min, max){
        const n = Number(value);
        if(!Number.isFinite(n)) return fallback;
        return Math.max(min, Math.min(max, n));
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

    function stableAssetId(source, ref, refIndex, kind, sequence){
        const base = source?.assetId || source?.imageId || source?.id || `${kind}:${sequence}`;
        const hasManyRefs = (source?.refs || []).length > 1;
        if(hasManyRefs) return `${base}:${ref?.url || refIndex}`;
        return String(base);
    }

    function fallbackAssetRole(kind, index){
        if(kind === 'video') return '视频动作、运动节奏和转场参考';
        if(kind === 'audio') return '音频节奏、情绪和氛围参考';
        if(index === 1) return '主角外观、身份锚点和关键造型参考';
        if(index === 2) return '场景空间、环境气氛和构图参考';
        if(index === 3) return '服装、道具、材质或角色细节参考';
        if(index === 4) return '光影、色彩和画面质感参考';
        return '补充角色、场景、道具或风格参考';
    }

    function parseAssetTag(tag){
        const match = cleanText(tag).toLowerCase().match(/^@(image|video|audio)(\d+)$/);
        return match ? {kind:match[1], index:Number(match[2]), tag:`@${match[1]}${Number(match[2])}`} : null;
    }

    function normalizeAssetName(value){
        return cleanText(value)
            .replace(/[?#].*$/, '')
            .replace(/^.*[\\/]/, '')
            .toLowerCase();
    }

    function normalizeAssetStem(value){
        return normalizeAssetName(value).replace(/\.[a-z0-9]+$/i, '');
    }

    function parseMappedRole(rawRole){
        let role = cleanText(rawRole);
        let name = '';
        const fileMatch = role.match(/[；;,，]?\s*(?:文件|file|filename)\s*[:：]\s*([^；;,，\n]+)/i);
        if(fileMatch){
            name = cleanText(fileMatch[1]);
            role = cleanText(role.replace(fileMatch[0], ''));
        }
        const parenFile = role.match(/[（(]([^()（）]+\.(?:jpe?g|png|webp|gif|bmp|mp4|mov|webm|mp3|wav|m4a|aac|flac))[）)]\s*$/i);
        if(parenFile){
            name = name || cleanText(parenFile[1]);
            role = cleanText(role.replace(parenFile[0], ''));
        }
        return {role, name};
    }

    function parseAssetMappings(text){
        const byTag = new Map();
        const byName = new Map();
        const byStem = new Map();
        function add(tagValue, rawRole){
            const parsedTag = parseAssetTag(tagValue);
            if(!parsedTag) return;
            const parsedRole = parseMappedRole(rawRole);
            if(!parsedRole.role) return;
            const entry = {...parsedTag, role:parsedRole.role, name:parsedRole.name};
            byTag.set(entry.tag, entry);
            const normalizedName = normalizeAssetName(parsedRole.name);
            if(normalizedName) byName.set(normalizedName, entry);
            const stem = normalizeAssetStem(parsedRole.name);
            if(stem) byStem.set(stem, entry);
        }
        String(text || '').split(/\r?\n/).forEach(line => {
            const clean = cleanText(line).replace(/^\s*[-*]\s*/, '');
            if(!clean) return;
            const direct = clean.match(/^(@(?:image|video|audio)\d+)\s*[：:]\s*(.+)$/i);
            if(direct){
                add(direct[1], direct[2]);
                return;
            }
            const usage = clean.matchAll(/(@(?:image|video|audio)\d+)\s*用于\s*([^@；;\n]+)/gi);
            for(const match of usage) add(match[1], match[2]);
        });
        return {byTag, byName, byStem};
    }

    function sourceMappingForRef(mappings, tag, ref, source){
        const tagMatch = mappings.byTag.get(cleanText(tag).toLowerCase());
        if(tagMatch) return tagMatch;
        const names = [
            ref?.name,
            source?.label,
            source?.sourceLabel,
            ref?.url,
            source?.preview
        ].map(normalizeAssetName).filter(Boolean);
        for(const name of names){
            if(mappings.byName.has(name)) return mappings.byName.get(name);
            const stem = normalizeAssetStem(name);
            if(stem && mappings.byStem.has(stem)) return mappings.byStem.get(stem);
        }
        return null;
    }

    function collectAssets(sources, assetRoles={}, sourceText=''){
        const counts = {image:0, video:0, audio:0};
        const assets = [];
        const mappings = parseAssetMappings(sourceText);
        let hasPromptMapping = false;
        (sources || []).forEach(source => {
            (source?.refs || []).forEach((ref, refIndex) => {
                if(!ref?.url) return;
                const kind = refKind(ref, source);
                counts[kind] = (counts[kind] || 0) + 1;
                const sourceId = source.id || `${kind}:${assets.length}`;
                const assetId = stableAssetId(source, ref, refIndex, kind, counts[kind]);
                const defaultTag = `@${kind}${counts[kind]}`;
                const mapped = sourceMappingForRef(mappings, defaultTag, ref, source);
                const mappedTag = mapped && mapped.kind === kind ? mapped.tag : defaultTag;
                if(mapped?.role) hasPromptMapping = true;
                const role = cleanText(assetRoles?.[assetId])
                    || cleanText(assetRoles?.[sourceId])
                    || cleanText(mapped?.role)
                    || cleanText(ref.role)
                    || cleanText(source.role)
                    || fallbackAssetRole(kind, counts[kind]);
                assets.push({
                    id:assetId,
                    sourceId,
                    sourceLabel:source.label || ref.name || `${kind}${counts[kind]}`,
                    kind,
                    index:parseAssetTag(mappedTag)?.index || counts[kind],
                    tag:mappedTag,
                    url:ref.url,
                    name:ref.name || source.label || `${kind}${counts[kind]}`,
                    role
                });
            });
        });
        if(!hasPromptMapping) return assets;
        const kindRank = {image:0, video:1, audio:2};
        return assets.slice().sort((a, b) => {
            const rank = (kindRank[a.kind] ?? 9) - (kindRank[b.kind] ?? 9);
            if(rank) return rank;
            return Number(a.index || 0) - Number(b.index || 0);
        });
    }

    function promptSources(sources){
        return (sources || [])
            .filter(source => source?.prompt && !(source.refs || []).length)
            .map(source => cleanText(source.prompt))
            .filter(Boolean);
    }

    function sourceTextFromSources(sources, manualText=''){
        return [cleanText(manualText), ...promptSources(sources)].filter(Boolean).join('\n\n').trim();
    }

    function normalizeTimecode(value){
        return cleanText(value).replace(/\s*[–—至到]\s*/g, '-').replace(/\s+/g, '');
    }

    function stripLeadingShotMarker(text){
        return cleanText(text)
            .replace(/^\s*(?:[-*]\s*)?(?:镜头|shot)\s*\d+\s*[:：.、-]?\s*/i, '')
            .replace(/^\s*(?:[-*]\s*)?\d+\s*[.、)]\s*/, '');
    }

    function parseShotLine(line, index){
        const raw = cleanText(line);
        if(!raw) return null;
        const time = raw.match(/(\d{1,2}:\d{2}(?:\.\d)?\s*[-–—至到]\s*\d{1,2}:\d{2}(?:\.\d)?)/);
        const marked = raw.match(/(?:^|\s)(?:镜头|shot)\s*(\d+)\s*[:：.、-]?/i);
        if(!time && !marked) return null;
        const timecode = time ? normalizeTimecode(time[1]) : '';
        let body = raw;
        if(time) body = body.replace(time[1], '');
        body = stripLeadingShotMarker(body);
        if(!body && time) body = stripLeadingShotMarker(raw.replace(time[1], ''));
        return {
            index:Number(marked?.[1] || index + 1),
            timecode,
            body:body || raw,
            title:`镜头${Number(marked?.[1] || index + 1)}`
        };
    }

    function parseShots(text, maxShots=DEFAULTS.maxShots){
        const lines = String(text || '')
            .split(/\r?\n+/)
            .map(line => line.trim())
            .filter(Boolean);
        const shots = [];
        lines.forEach(line => {
            const shot = parseShotLine(line, shots.length);
            if(shot) shots.push(shot);
        });
        if(!shots.length){
            const matches = [...String(text || '').matchAll(/(\d{1,2}:\d{2}(?:\.\d)?\s*[-–—至到]\s*\d{1,2}:\d{2}(?:\.\d)?)([\s\S]*?)(?=\d{1,2}:\d{2}(?:\.\d)?\s*[-–—至到]\s*\d{1,2}:\d{2}(?:\.\d)?|$)/g)];
            matches.forEach((match, i) => {
                const body = stripLeadingShotMarker(match[2] || '');
                shots.push({index:i + 1, timecode:normalizeTimecode(match[1]), body:body || `镜头${i + 1}`, title:`镜头${i + 1}`});
            });
        }
        return shots
            .filter(shot => cleanText(shot.body) || cleanText(shot.timecode))
            .slice(0, clampNumber(maxShots, DEFAULTS.maxShots, 1, DEFAULTS.maxShots))
            .map((shot, i) => ({...shot, index:i + 1, title:shot.title || `镜头${i + 1}`}));
    }

    function autoLayoutKey(shotCount){
        const count = clampNumber(shotCount, 1, 1, DEFAULTS.maxShots);
        if(count <= 1) return '1x1';
        if(count === 2) return '1x2';
        if(count === 3) return '1x3';
        if(count === 4) return '2x2';
        if(count <= 6) return '2x3';
        return '3x3';
    }

    function layoutKeyFor(value, shotCount){
        if(value && value !== 'auto' && LAYOUTS[value]) return value;
        return autoLayoutKey(shotCount);
    }

    function layoutSpec(value, shotCount){
        const key = layoutKeyFor(value, shotCount);
        return {key, ...LAYOUTS[key]};
    }

    function customRatioParts(customRatio){
        const [w, h] = String(customRatio || '').split(':').map(v => Number(v));
        return w > 0 && h > 0 ? {width:String(w), height:String(h)} : {width:'', height:''};
    }

    function generationSizeSettings(layout){
        if(layout.ratio !== 'custom'){
            return {ratio:layout.ratio || 'wide', customRatio:'', customRatioWidth:'', customRatioHeight:''};
        }
        const parts = customRatioParts(layout.customRatio);
        return {
            ratio:'custom',
            customRatio:layout.customRatio,
            customRatioWidth:parts.width,
            customRatioHeight:parts.height
        };
    }

    function assetMappingText(assets){
        if(!(assets || []).length) return '无上游参考素材。';
        return assets.map(asset => `- ${asset.tag}：${asset.role}（${asset.name || asset.sourceLabel || asset.tag}）`).join('\n');
    }

    function compactShotBody(body){
        const text = cleanText(body).replace(/\s+/g, ' ');
        return text.length > 220 ? `${text.slice(0, 218)}...` : text;
    }

    function shotsText(shots){
        return (shots || []).map(shot => {
            const time = shot.timecode ? `${shot.timecode} ` : '';
            return `${shot.index}. ${time}${compactShotBody(shot.body)}`;
        }).join('\n');
    }

    function buildGridImagePrompt({node={}, shots=[], assets=[], layout, sourceText=''}={}){
        const count = shots.length || 1;
        const safeLayout = layout || layoutSpec(node.layout || 'auto', count);
        const mapping = assetMappingText(assets);
        const shotLines = shotsText(shots.length ? shots : [{index:1, timecode:'', body:sourceText || '根据上游提示词生成电影分镜画面'}]);
        const ratioLine = safeLayout.ratio === 'custom'
            ? `${safeLayout.ratioLabel}（优先自定义 ${safeLayout.customRatio}，如模型不稳定可退到 ${safeLayout.fallbackRatio}）`
            : safeLayout.ratioLabel;
        return [
            '生成一张电影多宫格分镜图板，不是文字说明页。',
            `整体布局：${safeLayout.rows} 行 x ${safeLayout.cols} 列，共 ${count} 个镜头格。`,
            `整体画布比例：${ratioLine}。`,
            '每个单独镜头格必须严格保持 16:9，禁止拉伸、压扁、裁切变形；每格内部画面占主要面积。',
            '每格允许有清晰小号中文编号、时间码和极短镜头说明，但不能让文字压缩画面比例。',
            '所有镜头应具有电影感构图、自然主义光影、清晰空间关系、连续人物走位和统一色彩质感。',
            '不要生成角色设定表、定妆信息区、海报排版、漫画对白气泡、无关装饰边框。',
            '',
            '参考素材映射：',
            mapping,
            '',
            '镜头内容：',
            shotLines
        ].join('\n');
    }

    function buildSeedancePrompt({node={}, shots=[], assets=[], layout, sourceText=''}={}){
        const safeLayout = layout || layoutSpec(node.layout || 'auto', shots.length || 1);
        const shotLines = shotsText(shots.length ? shots : [{index:1, timecode:'', body:sourceText || '根据上游提示词生成视频'}]);
        return [
            '模式：多宫格分镜参考生成',
            '',
            '素材映射：',
            assetMappingText(assets),
            '- 多宫格分镜图：作为镜头构图、景别、空间关系和动作节奏参考；最终视频中不要出现分镜边框、编号或文字。',
            '',
            '正式提示词：',
            shotLines,
            '',
            '镜头规则：',
            '按多宫格分镜图的镜头顺序执行，保持人物身份、服装、道具、姿态、走位、视线方向和空间轴线连续。',
            '每个镜头只使用一种主运镜；景别变化必须有动机；不要机械平均节奏。',
            '',
            '摄影风格：',
            cleanText(node.styleText) || '罗杰·迪金斯 / Roger Deakins 风格：自然主义电影摄影，动机光源，低调光，克制运镜，清晰空间层次，真实胶片质感。',
            '',
            '负面约束：',
            cleanText(node.negativeText) || '无水印，无 logo，无字幕，无屏幕文字，无低清晰度，无塑料皮肤，无蜡像感，无面部变形，无肢体畸形，无闪烁，无过曝或欠曝。',
            '',
            '生成设置：',
            `分镜图布局：${safeLayout.key}，单格比例：16:9，整体比例：${safeLayout.ratioLabel}`,
            `时长：${cleanText(node.duration || '') || '按上游视频节点设置'}`,
            `画面比例：${cleanText(node.videoRatio || '') || '16:9'}`
        ].join('\n');
    }

    function extractJsonObject(text){
        const raw = String(text || '').trim();
        if(!raw) return null;
        try { return JSON.parse(raw); } catch(_) {}
        const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
        if(fenced){
            try { return JSON.parse(fenced[1]); } catch(_) {}
        }
        const first = raw.indexOf('{');
        const last = raw.lastIndexOf('}');
        if(first >= 0 && last > first){
            try { return JSON.parse(raw.slice(first, last + 1)); } catch(_) {}
        }
        return null;
    }

    function normalizeLLMShots(raw, fallbackText='', maxShots=DEFAULTS.maxShots){
        const parsed = extractJsonObject(raw);
        const source = Array.isArray(parsed?.shots) ? parsed.shots : (Array.isArray(parsed) ? parsed : []);
        const shots = source.map((item, i) => {
            if(typeof item === 'string') return {index:i + 1, timecode:'', body:item, title:`镜头${i + 1}`};
            return {
                index:Number(item.index || item.shot || i + 1),
                timecode:cleanText(item.timecode || item.time || ''),
                body:cleanText(item.body || item.description || item.prompt || item.text || ''),
                title:cleanText(item.title || `镜头${i + 1}`)
            };
        }).filter(shot => shot.body || shot.timecode);
        if(shots.length) return shots.slice(0, maxShots).map((shot, i) => ({...shot, index:i + 1, title:shot.title || `镜头${i + 1}`}));
        return parseShots(raw || fallbackText, maxShots);
    }

    function buildShotExtractionPrompt({sourceText='', maxShots=DEFAULTS.maxShots}={}){
        return [
            '请把下面的电影分镜/视频提示词拆成可用于多宫格分镜图的镜头列表。',
            `最多输出 ${maxShots} 个镜头；如果超过，请合并相近动作，只保留最关键镜头。`,
            '必须保留原有时间码、台词、动作顺序和空间逻辑。',
            '只输出 JSON，不要 Markdown，不要解释。',
            'JSON 格式：{"shots":[{"index":1,"timecode":"00:00.0-00:03.2","title":"镜头1","body":"景别、机位、主动作、光影、空间关系"}]}',
            '',
            '原文：',
            sourceText || '无'
        ].join('\n');
    }

    function buildDraft({node={}, sources=[]}={}){
        const sourceText = sourceTextFromSources(sources, node.manualPrompt || node.storyboardText || '');
        const maxShots = clampNumber(node.maxShots || DEFAULTS.maxShots, DEFAULTS.maxShots, 1, DEFAULTS.maxShots);
        const assets = collectAssets(sources, node.assetRoles || {}, sourceText);
        const parsedShots = parseShots(sourceText, maxShots);
        const layout = layoutSpec(node.layout || DEFAULTS.layout, parsedShots.length || 1);
        const size = generationSizeSettings(layout);
        return {
            sourceText,
            assets,
            shots:parsedShots,
            layout,
            size,
            gridImagePrompt:buildGridImagePrompt({node, shots:parsedShots, assets, layout, sourceText}),
            seedancePrompt:buildSeedancePrompt({node, shots:parsedShots, assets, layout, sourceText})
        };
    }

    global.CanvasStoryboardGrid = Object.freeze({
        DEFAULTS,
        LAYOUTS,
        collectAssets,
        parseShots,
        autoLayoutKey,
        layoutKeyFor,
        layoutSpec,
        generationSizeSettings,
        parseAssetMappings,
        buildGridImagePrompt,
        buildSeedancePrompt,
        buildShotExtractionPrompt,
        normalizeLLMShots,
        buildDraft
    });
})(window);
