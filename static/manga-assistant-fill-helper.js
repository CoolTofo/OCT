(function(){
    const CHAT_SELECTORS = Object.freeze([
        'div[role="textbox"][contenteditable="true"]',
        'div.ProseMirror[contenteditable="true"]',
        'div.tiptap[contenteditable="true"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="消息"]',
        'textarea[placeholder*="输入"]',
        'textarea[placeholder*="提问"]',
        '[class*="input"] textarea',
        '[class*="editor"] textarea',
        'textarea',
    ]);

    const PROMPT_SELECTORS = Object.freeze([
        'div[role="textbox"][contenteditable="true"]',
        'div.ProseMirror[contenteditable="true"]',
        'div.tiptap[contenteditable="true"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="提示词"]',
        'textarea[placeholder*="提示"]',
        'textarea[placeholder*="描述"]',
        '.prompt-input textarea',
        '#prompt-textarea',
        '[data-testid="prompt-input"]',
        '[data-testid="chat-input"] textarea',
        'textarea',
    ]);

    const SITE_FILL_RULES = Object.freeze({
        vidu: {domain:'vidu.cn', selectors:PROMPT_SELECTORS, kind:'prompt'},
        seedance: {domain:'seedance.io', selectors:PROMPT_SELECTORS, kind:'prompt'},
        'volcengine-seedance': {domain:'volcengine.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        deepseek: {domain:'deepseek.com', selectors:CHAT_SELECTORS, kind:'chat'},
        chatgpt: {domain:'chatgpt.com', selectors:CHAT_SELECTORS, kind:'chat'},
        claude: {domain:'claude.ai', selectors:CHAT_SELECTORS, kind:'chat'},
        kimi: {domain:'kimi.com', selectors:CHAT_SELECTORS, kind:'chat'},
        tongyi: {domain:'tongyi.aliyun.com', selectors:CHAT_SELECTORS, kind:'chat'},
        qianwen: {domain:'qianwen.com', selectors:CHAT_SELECTORS, kind:'chat'},
        chatglm: {domain:'chatglm.cn', selectors:CHAT_SELECTORS, kind:'chat'},
        yiyan: {domain:'yiyan.baidu.com', selectors:CHAT_SELECTORS, kind:'chat'},
        doubao: {domain:'doubao.com', selectors:CHAT_SELECTORS, kind:'chat'},
        gemini: {domain:'gemini.google.com', selectors:CHAT_SELECTORS, kind:'chat'},
        jimeng: {domain:'jimeng.jianying.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        kling: {domain:'klingai.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        pai: {domain:'pai.video', selectors:PROMPT_SELECTORS, kind:'prompt'},
        runway: {domain:'runwayml.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        grok: {domain:'grok.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        peiyinshenqi: {domain:'peiyinshenqi.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        minimax: {domain:'minimaxi.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
        noiz: {domain:'noiz.ai', selectors:PROMPT_SELECTORS, kind:'prompt'},
        youmind: {domain:'youmind.com', selectors:PROMPT_SELECTORS, kind:'prompt'},
    });

    function ruleForSite(site={}){
        const id = String(site.id || '').trim();
        if(id && SITE_FILL_RULES[id]) return SITE_FILL_RULES[id];
        const url = String(site.url || '');
        return Object.values(SITE_FILL_RULES).find(rule => url.includes(rule.domain)) || null;
    }

    function supportedSiteIds(){
        return Object.keys(SITE_FILL_RULES);
    }

    function runtimeFillScript(text, selectors){
        const payload = JSON.stringify(String(text || ''));
        const selectorPayload = JSON.stringify([...(selectors || PROMPT_SELECTORS)]);
        return `(() => {
  const text = ${payload};
  const selectors = ${selectorPayload};
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const editable = el => {
    if(!el) return false;
    if(el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') return !el.disabled && !el.readOnly;
    const ce = el.getAttribute('contenteditable');
    return el.isContentEditable || ce === 'true' || ce === 'plaintext-only' || ce === '';
  };
  const appendText = (oldText, next, separator='\\n') => {
    if(!oldText) return next;
    if(!next) return oldText;
    return /\\s$/.test(oldText) || /^\\s/.test(next) ? oldText + next : oldText + separator + next;
  };
  const setNativeValue = (el, value) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if(setter) setter.call(el, value);
    else el.value = value;
  };
  const moveCaretEnd = el => {
    const selection = getSelection();
    if(!selection || !document.createRange) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  };
  const emit = el => {
    try { el.dispatchEvent(new InputEvent('input', {bubbles:true, cancelable:true, inputType:'insertText', data:text})); }
    catch { el.dispatchEvent(new Event('input', {bubbles:true, cancelable:true})); }
    el.dispatchEvent(new Event('change', {bubbles:true, cancelable:true}));
  };
  const editorKind = el => {
    const quill = el.__quill || el.closest?.('.ql-container')?.__quill;
    if(quill && typeof quill.getText === 'function' && typeof quill.setText === 'function') return 'quill';
    if(el.hasAttribute('data-slate-editor') || el.closest?.('[data-slate-editor]')) return 'slate';
    if(el.classList?.contains('ProseMirror') || el.classList?.contains('tiptap')) return 'prosemirror';
    return 'contenteditable';
  };
  const fillRichText = el => {
    const kind = editorKind(el);
    if(kind === 'quill'){
      const quill = el.__quill || el.closest?.('.ql-container')?.__quill;
      const current = String(quill.getText?.() || '').replace(/\\n$/, '');
      const next = appendText(current, text, '\\n');
      quill.setText(next);
      quill.focus?.();
      quill.setSelection?.(next.length, 0, 'silent');
      return true;
    }
    const oldText = el.innerText || el.textContent || '';
    const insert = oldText ? appendText('', text, '\\n') : text;
    el.focus();
    moveCaretEnd(el);
    let ok = false;
    try { ok = document.execCommand && document.execCommand('insertText', false, insert); }
    catch { ok = false; }
    if(!ok){
      el.textContent = appendText(oldText, text, '\\n');
      moveCaretEnd(el);
    }
    return true;
  };
  for(const selector of selectors){
    for(const el of document.querySelectorAll(selector)){
      if(!visible(el) || !editable(el)) continue;
      el.focus();
      if(el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'){
        setNativeValue(el, appendText(el.value || '', text, el.tagName === 'INPUT' ? ' ' : '\\n'));
        if(typeof el.selectionStart === 'number') el.setSelectionRange(el.value.length, el.value.length);
      } else {
        fillRichText(el);
      }
      emit(el);
      alert('已填充提示词');
      return true;
    }
  }
  alert('没有找到可填充的输入框');
  return false;
})();`;
    }

    function buildConsoleScript(text, site={}){
        const rule = ruleForSite(site);
        return runtimeFillScript(text, rule?.selectors || PROMPT_SELECTORS);
    }

    function buildBookmarklet(text, site={}){
        return `javascript:${encodeURIComponent(buildConsoleScript(text, site))}`;
    }

    window.MangaAssistantFillHelper = {
        CHAT_SELECTORS,
        PROMPT_SELECTORS,
        SITE_FILL_RULES,
        ruleForSite,
        supportedSiteIds,
        buildConsoleScript,
        buildBookmarklet,
    };
})();
