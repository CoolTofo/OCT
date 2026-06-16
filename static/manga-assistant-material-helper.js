(function(){
    const COLLECTOR_RULES = Object.freeze({
        oiioii: {
            label:'Oiioii 素材采集',
            domains:['oiioii.ai'],
            selectors:['.hogi-image-thumb img', 'img'],
            transform:'oiioii',
        },
        liblib: {
            label:'LibLib 图片采集',
            domains:['liblib.tv', 'liblib.art'],
            selectors:['img.h-full.w-full.object-cover', 'img.object-cover', 'img'],
            transform:'image',
        },
    });

    function ruleForSite(site={}){
        const id = String(site.id || '').toLowerCase();
        if(id.includes('oiioii')) return COLLECTOR_RULES.oiioii;
        if(id.includes('liblib')) return COLLECTOR_RULES.liblib;
        const url = String(site.url || '').toLowerCase();
        return Object.values(COLLECTOR_RULES).find(rule => rule.domains.some(domain => url.includes(domain))) || null;
    }

    function collectorScript(site={}){
        const rule = ruleForSite(site);
        const selectors = JSON.stringify(rule?.selectors || ['img']);
        const transform = JSON.stringify(rule?.transform || 'image');
        return `(() => {
  const selectors = ${selectors};
  const transform = ${transform};
  const normalize = value => {
    if(!value) return '';
    try {
      const raw = String(value).trim().replaceAll('&amp;', '&');
      if(!raw || raw.startsWith('data:') || raw.startsWith('blob:')) return '';
      const absolute = raw.startsWith('//') ? location.protocol + raw : new URL(raw, location.href).href;
      const url = new URL(absolute);
      if(!['http:', 'https:'].includes(url.protocol)) return '';
      if(transform === 'oiioii' && url.href.includes('://api.oiioii.ai/res/read_file?uri=')){
        const uri = String(url.searchParams.get('uri') || '').trim();
        if(uri && /\\.webp$/i.test(uri)) url.searchParams.set('uri', uri.replace(/\\.webp$/i, '.jpg'));
        const minLongLength = Number(url.searchParams.get('minLongLength') || 0);
        if(!Number.isFinite(minLongLength) || minLongLength < 4096) url.searchParams.set('minLongLength', '4096');
        return url.href;
      }
      return /\\.(png|jpe?g|gif|bmp|webp|tiff?|avif|apng|svg|ico|jfif)(?=$|[?#&])/i.test(url.href) ? url.href : '';
    } catch {
      return '';
    }
  };
  const urls = [];
  const seen = new Set();
  for(const selector of selectors){
    for(const img of document.querySelectorAll(selector)){
      const value = img.currentSrc || img.src || img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original') || img.getAttribute('data-lazy-src') || '';
      const url = normalize(value);
      if(url && !seen.has(url)){
        seen.add(url);
        urls.push(url);
      }
    }
  }
  if(!urls.length){
    alert('没有找到可采集的图片 URL');
    return [];
  }
  const text = urls.join('\\n');
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(() => alert('已复制 ' + urls.length + ' 个图片 URL')).catch(() => {
      prompt('复制下面的图片 URL', text);
    });
  } else {
    prompt('复制下面的图片 URL', text);
  }
  return urls;
})();`;
    }

    function bookmarklet(site={}){
        return `javascript:${encodeURIComponent(collectorScript(site))}`;
    }

    window.MangaAssistantMaterialHelper = {
        COLLECTOR_RULES,
        ruleForSite,
        collectorScript,
        bookmarklet,
    };
})();
